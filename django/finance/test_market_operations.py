from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from finance import test_advanced_operations
from finance.models import (
    CommissionPolicy,
    CommissionTier,
    CommissionSnapshot,
    ProfessionalCommission,
    FinancialCategory,
    FinancialTransaction,
    GiftCardEntry,
)
from finance.giftcards import issue, redeem, reverse as reverse_gift
from finance.advanced_services import consume_material, cash_balance
from finance.dre import report
from finance.services import pay_commission
from scheduling.models import Appointment
from scheduling.settlement import settle_appointment
from barber.services import open_command, add_service_item, close_command


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class MarketOperationsTests(TestCase):
    def setUp(self):
        test_advanced_operations.AdvancedOperationsTests.setUp(self)

    def policy(self):
        policy = CommissionPolicy.objects.create(
            tenant=self.tenant,
            name="Meta mensal",
            professional=self.pro,
            starts_on=timezone.localdate(),
            deduct_materials=True,
        )
        CommissionTier.objects.create(policy=policy, threshold=0, rate=30)
        CommissionTier.objects.create(policy=policy, threshold=80, rate=40)
        return policy

    def test_monthly_tier_and_material_deduction_are_snapshotted(self):
        policy = self.policy()
        consume_material(
            tenant=self.tenant,
            product_id=self.product.pk,
            quantity=2,
            user=self.owner,
            key="material-meta",
            appointment=self.appt,
        )
        settle_appointment(
            appointment_id=self.appt.pk,
            professional=self.pro,
            user=self.owner,
            attended=True,
            payment_method="cash",
        )
        first = ProfessionalCommission.objects.get(
            source_id=self.appt.pk, source_type="appointment"
        )
        self.assertEqual(first.commission_amount, Decimal("13.80"))
        self.assertEqual(
            Decimal(first.calculation.details["materials"]), Decimal("4.00")
        )
        second = Appointment.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            professional=self.pro,
            service=self.service,
            customer=self.customer,
            starts_at=timezone.now() - timedelta(hours=2),
            ends_at=timezone.now() - timedelta(hours=1),
        )
        settle_appointment(
            appointment_id=second.pk,
            professional=self.pro,
            user=self.owner,
            attended=True,
            payment_method="cash",
        )
        later = ProfessionalCommission.objects.get(
            source_id=second.pk, source_type="appointment"
        )
        self.assertEqual(later.commission_amount, Decimal("20"))
        policy.tiers.all().update(rate=90)
        first.refresh_from_db()
        self.assertEqual(first.commission_amount, Decimal("13.80"))
        self.assertEqual(first.calculation.details["rate"], "30.00")

    def test_missing_initial_tier_rolls_back_closing(self):
        policy = CommissionPolicy.objects.create(
            tenant=self.tenant,
            name="Inválida",
            professional=self.pro,
            starts_on=timezone.localdate(),
        )
        CommissionTier.objects.create(policy=policy, threshold=100, rate=30)
        with self.assertRaises(ValidationError):
            settle_appointment(
                appointment_id=self.appt.pk,
                professional=self.pro,
                user=self.owner,
                attended=True,
                payment_method="cash",
            )
        self.assertFalse(FinancialTransaction.objects.exists())
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "pending")

    def test_zero_percent_events_still_advance_the_monthly_goal(self):
        policy = self.policy()
        policy.tiers.filter(threshold=0).update(rate=0)
        settle_appointment(
            appointment_id=self.appt.pk,
            professional=self.pro,
            user=self.owner,
            attended=True,
            payment_method="cash",
        )
        self.assertEqual(CommissionSnapshot.objects.get().details["gross"], "50.00")
        self.assertEqual(ProfessionalCommission.objects.get().commission_amount, 0)

    def test_dre_recognizes_costs_and_not_duplicate_paid_commission(self):
        day = timezone.localdate()
        revenue = FinancialCategory.objects.create(
            tenant=self.tenant,
            name="Serviços",
            type="income",
            statement_line="gross_revenue",
        )
        expense = FinancialCategory.objects.create(
            tenant=self.tenant,
            name="Aluguel",
            type="expense",
            statement_line="operating_expenses",
            expense_nature="fixed",
        )
        FinancialTransaction.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            type="income",
            category=revenue,
            description="Receita",
            amount=100,
            status="paid",
            competence_at=day,
        )
        FinancialTransaction.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            type="expense",
            category=expense,
            description="Aluguel",
            amount=10,
            status="pending",
            competence_at=day,
        )
        commission = ProfessionalCommission.objects.create(
            tenant=self.tenant,
            professional=self.pro,
            source_type="appointment",
            source_id=self.appt.pk,
            gross_amount=100,
            commission_amount=5,
        )
        consume_material(
            tenant=self.tenant,
            product_id=self.product.pk,
            quantity=2,
            user=self.owner,
            key="dre-material",
            appointment=self.appt,
        )
        result = report(self.tenant, day, day, self.unit)
        self.assertEqual(result["result"], 81)
        pay_commission(commission=commission, user=self.owner)
        self.assertEqual(report(self.tenant, day, day, self.unit)["result"], 81)

    def test_gift_issue_and_use_are_idempotent_and_do_not_double_count_cash(self):
        card, code = issue(
            tenant=self.tenant,
            unit=self.unit,
            user=self.owner,
            amount=50,
            method="cash",
            key="gift-issue",
        )
        same, replayed = issue(
            tenant=self.tenant,
            unit=self.unit,
            user=self.owner,
            amount=50,
            method="cash",
            key="gift-issue",
        )
        self.assertEqual(card.pk, same.pk)
        self.assertIsNone(replayed)
        command = open_command(
            tenant=self.tenant, user=self.owner, appointment=self.appt
        )
        add_service_item(command=command, service=self.service, professional=self.pro)
        entry = redeem(
            tenant=self.tenant,
            user=self.owner,
            code=code,
            command=command,
            key="gift-use",
            amount=50,
        )
        self.assertEqual(
            entry.pk,
            redeem(
                tenant=self.tenant,
                user=self.owner,
                code=code,
                command=command,
                key="gift-use",
                amount=50,
            ).pk,
        )
        close_command(command=command, user=self.owner)
        card.refresh_from_db()
        self.assertEqual(card.balance, 0)
        self.assertEqual(cash_balance(self.session), 150)
        self.assertEqual(
            FinancialTransaction.objects.get(source_type="barber_command").amount, 50
        )
        self.assertEqual(GiftCardEntry.objects.count(), 2)

    def test_gift_reversal_keeps_payment_history_and_refunds_balance_once(self):
        card, code = issue(
            tenant=self.tenant,
            unit=self.unit,
            user=self.owner,
            amount=100,
            method="pix",
            key="gift-return",
        )
        command = open_command(
            tenant=self.tenant, user=self.owner, appointment=self.appt
        )
        add_service_item(command=command, service=self.service)
        entry = redeem(
            tenant=self.tenant,
            user=self.owner,
            code=code,
            command=command,
            key="gift-applied",
            amount=50,
        )
        reverse_gift(
            tenant=self.tenant, user=self.owner, entry_id=entry.pk, key="gift-refund"
        )
        reverse_gift(
            tenant=self.tenant, user=self.owner, entry_id=entry.pk, key="gift-refund"
        )
        card.refresh_from_db()
        entry.payment.refresh_from_db()
        self.assertEqual(card.balance, 100)
        self.assertIsNotNone(entry.payment.voided_at)
        with self.assertRaises(ValidationError):
            close_command(command=command, user=self.owner)

    def test_gift_and_commission_configuration_reject_professional_access(self):
        with self.assertRaises(PermissionDenied):
            issue(
                tenant=self.tenant,
                user=self.pro_user,
                amount=20,
                method="pix",
                key="forbidden",
            )
        self.client.force_login(self.pro_user)
        self.assertEqual(self.client.get(reverse("finance-policies")).status_code, 403)

    def test_gift_cannot_overpay_and_generic_payment_cannot_forge_gift_credit(self):
        from barber.services import register_payment

        card, code = issue(
            tenant=self.tenant,
            user=self.owner,
            amount=100,
            method="pix",
            key="overpay-card",
        )
        command = open_command(
            tenant=self.tenant, user=self.owner, appointment=self.appt
        )
        add_service_item(command=command, service=self.service, professional=self.pro)
        with self.assertRaises(ValidationError):
            redeem(
                tenant=self.tenant,
                user=self.owner,
                code=code,
                command=command,
                key="overpay",
                amount=60,
            )
        with self.assertRaises(ValidationError):
            register_payment(
                command=command, user=self.owner, method="gift_card", amount=50
            )
        card.refresh_from_db()
        self.assertEqual(card.balance, 100)

    def test_gift_receipt_enters_flow_only_at_issue_and_not_as_dre_revenue(self):
        from finance.dre import cash_flow

        day = timezone.localdate()
        issue(
            tenant=self.tenant,
            user=self.owner,
            unit=self.unit,
            amount=30,
            method="cash",
            key="flow-gift",
        )
        self.assertEqual(cash_flow(self.tenant, day, day, self.unit)["income"], 30)
        self.assertEqual(report(self.tenant, day, day, self.unit)["result"], 0)

    def test_reception_can_apply_existing_gift_without_access_to_issue_or_finance(self):
        from accounts.models import User

        self.tenant.category = "barbearia"
        self.tenant.save()
        card, code = issue(
            tenant=self.tenant,
            user=self.owner,
            amount=50,
            method="pix",
            key="reception-gift",
        )
        command = open_command(
            tenant=self.tenant, user=self.owner, appointment=self.appt
        )
        add_service_item(command=command, service=self.service, professional=self.pro)
        reception = User.objects.create_user(
            email="gift-reception@example.test", tenant=self.tenant, role="reception"
        )
        self.client.force_login(reception)
        url = reverse("barber-command-gift", args=[command.pk])
        result = self.client.post(
            url,
            {
                "command": command.pk,
                "code": code,
                "amount": "50",
                "key": "reception-use",
            },
        )
        self.assertEqual(result.status_code, 302, result.content)
        card.refresh_from_db()
        self.assertEqual(card.balance, 0)
        self.assertEqual(self.client.get(reverse("finance-gifts")).status_code, 403)
