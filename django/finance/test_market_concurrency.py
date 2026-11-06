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

    def test_online_card_and_manual_cash_cannot_charge_the_appointment_twice(self):
        from unittest.mock import patch, Mock
        from django.test import Client
        from django.urls import reverse
        from django.core.cache import cache
        import hashlib
        from core.crypto import encrypt_json
        from billing.models import TenantPaymentConnection, TenantPaymentTransaction
        from scheduling.models import TenantScheduleSettings

        cache.clear()
        self.customer.email = "parallel-card@example.test"
        self.customer.save()
        token = "parallel-booking-card-token"
        self.appt.customer_manage_token_hash = hashlib.sha256(
            token.encode()
        ).hexdigest()
        self.appt.starts_at = timezone.now() + timedelta(days=1)
        self.appt.ends_at = self.appt.starts_at + timedelta(minutes=30)
        self.appt.booking_payment = "full"
        self.appt.booking_payment_amount = 50
        self.appt.save()
        TenantScheduleSettings.objects.update_or_create(
            tenant=self.tenant,
            defaults={
                "online_booking_payments_enabled": True,
                "card_booking_payments_enabled": True,
            },
        )
        TenantPaymentConnection.objects.create(
            tenant=self.tenant,
            environment="sandbox",
            status="connected",
            metadata={"public_key": "TEST-parallel-public-key", "user_id": 123},
            credentials_encrypted=encrypt_json(
                {
                    "access_token": "TEST-only-synthetic-private-key",
                    "webhook_secret": "test-only-webhook",
                }
            ),
        )
        command = open_command(
            tenant=self.tenant, user=self.owner, appointment=self.appt
        )
        add_service_item(command=command, service=self.service, professional=self.pro)
        provider = Mock()
        provider.create_tokenized_card_payment.side_effect = lambda **kwargs: {
            "id": "card-parallel",
            "status": "approved",
            "transaction_amount": 50,
            "fee_amount": Decimal("1"),
            "net_received_amount": Decimal("49"),
            "currency_id": "BRL",
            "live_mode": False,
            "collector_id": 123,
            "external_reference": kwargs["external_reference"],
        }

        def action(index):
            if index == 1:
                return (
                    Client()
                    .post(
                        reverse("public-appointment-card-submit", args=[token]),
                        {
                            "card_token": "synthetic-card-token",
                            "payment_method_id": "visa",
                            "installments": 1,
                            "attempt_id": "parallel-card-attempt",
                        },
                        content_type="application/json",
                    )
                    .status_code
                )
            try:
                register_payment(
                    command=command, user=self.owner, method="cash", amount=50
                )
            except ValidationError:
                return "denied"
            return "cash"

        with patch("billing.payment_services.tenant_provider", return_value=provider):
            results = self.run_pair(action)
        paid = TenantPaymentTransaction.objects.filter(
            tenant=self.tenant, status="paid"
        ).aggregate(
            v=__import__("django.db.models", fromlist=["Sum"]).Sum("gross_amount")
        )["v"] or Decimal(0)
        cash = command.payments.filter(method="cash").aggregate(
            v=__import__("django.db.models", fromlist=["Sum"]).Sum("amount")
        )["v"] or Decimal(0)
        self.assertEqual(paid + cash, 50, results)

    def test_sale_cancellation_and_new_sale_do_not_invert_tenant_stock_locks(self):
        from finance.services import cancel_sale

        product = Product.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            name="Revenda concorrente",
            kind="retail",
            stock=10,
            sale_price=10,
        )
        sale = create_sale(
            tenant=self.tenant,
            user=self.owner,
            unit=self.unit,
            items=[{"product_id": product.pk, "quantity": 1}],
            payment_method="cash",
            idempotency_key="before-cancel",
        )

        def action(index):
            if index == 1:
                cancel_sale(sale=sale, user=self.owner, reason="Correção")
            else:
                create_sale(
                    tenant=self.tenant,
                    user=self.owner,
                    unit=self.unit,
                    items=[{"product_id": product.pk, "quantity": 1}],
                    payment_method="cash",
                    idempotency_key="after-cancel",
                )
            return "ok"

        self.assertEqual(self.run_pair(action), ["ok", "ok"])
        product.refresh_from_db()
        self.assertEqual(product.stock, 9)
