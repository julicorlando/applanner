from datetime import timedelta
from decimal import Decimal
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.core.exceptions import ValidationError
from django.utils import timezone
from finance import test_advanced_operations
from core.test_release_concurrency import ParallelActions
from finance.models import (
    CommissionPolicy,
    CommissionTier,
    ProfessionalCommission,
    ServiceMaterial,
    Product,
    FinancialTransaction,
)
from finance.giftcards import issue, redeem
from finance.services import create_sale
from scheduling.models import Appointment
from scheduling.settlement import settle_appointment
from barber.services import (
    open_command,
    add_service_item,
    register_payment,
    close_command,
)


@skipUnlessDBFeature("has_select_for_update")
class MarketConcurrencyTests(ParallelActions, TransactionTestCase):
    def setUp(self):
        test_advanced_operations.AdvancedOperationsTests.setUp(self)

    def test_two_commands_cannot_spend_the_same_gift_balance(self):
        card, code = issue(
            tenant=self.tenant,
            user=self.owner,
            amount=60,
            method="pix",
            key="parallel-issue",
            unit=self.unit,
        )
        commands = []
        for i in range(2):
            command = open_command(
                tenant=self.tenant,
                user=self.owner,
                professional=self.pro,
                customer=self.customer,
            )
            add_service_item(
                command=command, service=self.service, professional=self.pro
            )
            commands.append(command)

        def action(index):
            try:
                redeem(
                    tenant=self.tenant,
                    user=self.owner,
                    code=code,
                    command=commands[index - 1],
                    key=f"parallel-redeem-{index}",
                    amount=50,
                )
                return "ok"
            except ValidationError:
                return "denied"

        self.assertEqual(sorted(self.run_pair(action)), ["denied", "ok"])
        card.refresh_from_db()
        self.assertEqual(card.balance, 10)

    def test_monthly_goal_progress_is_serialized_and_snapshots_do_not_race(self):
        policy = CommissionPolicy.objects.create(
            tenant=self.tenant,
            name="Meta",
            professional=self.pro,
            starts_on=timezone.localdate(),
        )
        CommissionTier.objects.create(policy=policy, threshold=0, rate=30)
        CommissionTier.objects.create(policy=policy, threshold=80, rate=40)
        second = Appointment.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            professional=self.pro,
            customer=self.customer,
            service=self.service,
            starts_at=timezone.now() - timedelta(hours=3),
            ends_at=timezone.now() - timedelta(hours=2),
        )

        def action(index):
            row = self.appt if index == 1 else second
            settle_appointment(
                appointment_id=row.pk,
                professional=self.pro,
                user=self.owner,
                attended=True,
                payment_method="cash",
            )
            return ProfessionalCommission.objects.get(
                tenant=self.tenant, source_type="appointment", source_id=row.pk
            ).commission_amount

        self.assertEqual(sorted(self.run_pair(action)), [Decimal("15"), Decimal("20")])

    def test_appointment_and_command_closing_cannot_create_duplicate_revenue(self):
        command = open_command(
            tenant=self.tenant, user=self.owner, appointment=self.appt
        )
        add_service_item(command=command, service=self.service, professional=self.pro)
        register_payment(command=command, user=self.owner, method="cash", amount=50)

        def action(index):
            if index == 1:
                try:
                    settle_appointment(
                        appointment_id=self.appt.pk,
                        professional=self.pro,
                        user=self.owner,
                        attended=True,
                        payment_method="cash",
                    )
                except ValidationError:
                    return "denied"
                return "unexpected"
            close_command(command=command, user=self.owner)
            return "closed"

        self.assertEqual(sorted(self.run_pair(action)), ["closed", "denied"])
        self.assertEqual(
            FinancialTransaction.objects.filter(
                tenant=self.tenant, type="income"
            ).count(),
            1,
        )

    def test_recipe_and_retail_sale_follow_the_same_stock_lock_order(self):
        retail = Product.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            name="Revenda",
            kind="retail",
            stock=10,
            sale_price=10,
        )
        ServiceMaterial.objects.create(
            tenant=self.tenant, service=self.service, product=self.product, quantity=1
        )

        def action(index):
            if index == 1:
                settle_appointment(
                    appointment_id=self.appt.pk,
                    professional=self.pro,
                    user=self.owner,
                    attended=True,
                    payment_method="cash",
                    product_id=retail.pk,
                    quantity=1,
                )
            else:
                create_sale(
                    tenant=self.tenant,
                    user=self.owner,
                    professional=self.pro,
                    unit=self.unit,
                    items=[{"product_id": retail.pk, "quantity": 1}],
                    payment_method="cash",
                    idempotency_key="parallel-pos",
                )
            return "ok"

        self.assertEqual(self.run_pair(action), ["ok", "ok"])
        retail.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(retail.stock, 8)
        self.assertEqual(self.product.stock, 9)
