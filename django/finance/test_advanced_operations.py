from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant, Unit
from scheduling.models import Customer, Professional, Service, Appointment
from finance.models import (
    Product,
    CashSession,
    CashMovement,
    MaterialConsumption,
    ServiceMaterial,
    FinancialTransaction,
)
from finance.advanced_services import (
    consume_material,
    consume_recipe,
    move_cash,
    cash_balance,
)
from finance.services import close_cash_session, create_sale


class AdvancedOperationsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Empresa", slug="advanced-ops")
        self.unit = Unit.objects.create(tenant=self.tenant, name="Centro")
        self.owner = User.objects.create_user(
            email="advanced@example.test", tenant=self.tenant, role="owner"
        )
        self.pro_user = User.objects.create_user(
            email="advanced-pro@example.test", tenant=self.tenant, role="professional"
        )
        self.customer = Customer.objects.create(tenant=self.tenant, name="Cliente")
        self.pro = Professional.objects.create(
            tenant=self.tenant, unit=self.unit, name="Ana", user=self.pro_user
        )
        self.service = Service.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            name="Corte",
            duration_minutes=30,
            price=50,
        )
        self.appt = Appointment.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            professional=self.pro,
            customer=self.customer,
            service=self.service,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() - timedelta(minutes=30),
        )
        self.product = Product.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            name="Insumo",
            kind="internal",
            stock=10,
            cost_price=2,
            sale_price=0,
        )
        self.session = CashSession.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            opened_by=self.owner,
            opening_amount=100,
            opened_at=timezone.now() - timedelta(hours=1),
        )

    def consume(self, **extra):
        return consume_material(
            tenant=self.tenant,
            product_id=self.product.pk,
            quantity=2,
            user=self.owner,
            key="material-test",
            appointment=self.appt,
            **extra,
        )

    def test_consumption_is_idempotent_and_does_not_create_revenue(self):
        one = self.consume()
        two = self.consume()
        self.assertEqual(one.pk, two.pk)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)
        self.assertEqual(one.cost_snapshot, 4)
        self.assertEqual(FinancialTransaction.objects.count(), 0)

    def test_internal_stock_cannot_be_sold(self):
        with self.assertRaises(ValidationError):
            create_sale(
                tenant=self.tenant,
                user=self.owner,
                items=[{"product_id": self.product.pk, "quantity": 1}],
                payment_method="cash",
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_insufficient_stock_rolls_back(self):
        with self.assertRaises(ValidationError):
            consume_material(
                tenant=self.tenant,
                product_id=self.product.pk,
                quantity=11,
                user=self.owner,
                key="too-many",
                appointment=self.appt,
            )
        self.assertEqual(MaterialConsumption.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_other_unit_material_is_rejected(self):
        other = Unit.objects.create(tenant=self.tenant, name="Outra")
        self.product.unit = other
        self.product.save()
        with self.assertRaises(ValidationError):
            self.consume()

    def test_professional_cannot_consume_without_own_appointment(self):
        with self.assertRaises(PermissionDenied):
            consume_material(
                tenant=self.tenant,
                product_id=self.product.pk,
                quantity=1,
                user=self.pro_user,
                key="manual-pro",
            )

    def test_recipe_consumption_happens_once(self):
        ServiceMaterial.objects.create(
            tenant=self.tenant,
            service=self.service,
            product=self.product,
            quantity=Decimal("0.5"),
        )
        consume_recipe(self.appt, self.owner)
        consume_recipe(self.appt, self.owner)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, Decimal("9.5"))

    def test_cash_moves_are_not_sales_and_close_uses_ledger(self):
        move_cash(
            session=self.session,
            user=self.owner,
            kind="supply",
            amount=20,
            reason="Troco",
            key="supply",
        )
        move_cash(
            session=self.session,
            user=self.owner,
            kind="withdrawal",
            amount=30,
            reason="Cofre",
            key="withdrawal",
        )
        self.assertEqual(cash_balance(self.session), 90)
        self.assertEqual(FinancialTransaction.objects.count(), 0)
        close_cash_session(session=self.session, user=self.owner, closing_amount=90)
        self.session.refresh_from_db()
        self.assertEqual(self.session.difference_amount, 0)

    def test_replayed_cash_move_only_counts_once_and_changed_amount_rejected(self):
        for _ in range(2):
            move_cash(
                session=self.session,
                user=self.owner,
                kind="supply",
                amount=20,
                reason="Troco",
                key="replay",
            )
        self.assertEqual(CashMovement.objects.count(), 1)
        with self.assertRaises(ValidationError):
            move_cash(
                session=self.session,
                user=self.owner,
                kind="supply",
                amount=21,
                reason="Troco",
                key="replay",
            )

    def test_cash_withdrawal_cannot_exceed_balance_or_modify_closed_session(self):
        with self.assertRaises(ValidationError):
            move_cash(
                session=self.session,
                user=self.owner,
                kind="withdrawal",
                amount=101,
                reason="Cofre",
                key="excess",
            )
        self.session.status = "closed"
        self.session.save()
        with self.assertRaises(ValidationError):
            move_cash(
                session=self.session,
                user=self.owner,
                kind="supply",
                amount=1,
                reason="Troco",
                key="closed",
            )

    def test_cash_other_company_and_professional_are_denied(self):
        tenant = Tenant.objects.create(name="Outra", slug="other-advanced")
        user = User.objects.create_user(
            email="other-advanced@example.test", tenant=tenant, role="owner"
        )
        for actor in [user, self.pro_user]:
            with self.assertRaises(PermissionDenied):
                move_cash(
                    session=self.session,
                    user=actor,
                    kind="supply",
                    amount=1,
                    reason="Troco",
                    key="denied",
                )

    def test_service_specific_commission_is_honored_by_appointment_closing(self):
        from barber.models import ProfessionalServiceCommission
        from finance.models import ProfessionalCommission
        from scheduling.settlement import settle_appointment

        ProfessionalServiceCommission.objects.create(
            tenant=self.tenant,
            professional=self.pro,
            service=self.service,
            commission_type="fixed",
            commission_value=12,
            active=True,
        )
        settle_appointment(
            appointment_id=self.appt.pk,
            professional=self.pro,
            user=self.owner,
            attended=True,
            payment_method="cash",
        )
        self.assertEqual(
            ProfessionalCommission.objects.get(
                source_type="appointment"
            ).commission_amount,
            12,
        )

    def test_sub_precision_consumption_is_rejected_without_stock_loss(self):
        with self.assertRaises(ValidationError):
            consume_material(
                tenant=self.tenant,
                product_id=self.product.pk,
                quantity="0.0001",
                user=self.owner,
                key="precision",
            )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
