from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from finance.models import FinancialTransaction, Product, ProductStockMovement, ProfessionalCommission
from scheduling.models import Appointment, Customer, Professional, Service
from tenants.models import Tenant

from .models import BarberCommand
from .services import (
    add_product_item, add_service_item, close_command, open_command,
    register_payment, start_service,
)


class BarberCommandFlowTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Barbearia",slug="barbearia",status=Tenant.Status.ACTIVE)
        self.user=User.objects.create(email="barber@example.com",tenant=self.tenant)
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        self.professional=Professional.objects.create(
            tenant=self.tenant,name="Barbeiro",commission_percent=Decimal("40.00")
        )
        self.service=Service.objects.create(
            tenant=self.tenant,name="Corte",duration_minutes=30,price=Decimal("40.00")
        )
        self.product=Product.objects.create(
            tenant=self.tenant,name="Pomada",sku="POMADA",cost_price=Decimal("10.00"),
            sale_price=Decimal("20.00"),stock=Decimal("5.000"),
            commission_type=Product.CommissionType.PERCENT,commission_value=Decimal("10.00"),
        )
        from django.utils import timezone
        now=timezone.now()
        self.appointment=Appointment.objects.create(
            tenant=self.tenant,customer=self.customer,professional=self.professional,
            service=self.service,starts_at=now,ends_at=now+__import__("datetime").timedelta(minutes=30),
            status=Appointment.Status.CONFIRMED,created_by=self.user,
        )

    def test_close_command_updates_stock_finance_commission_and_appointment(self):
        start_service(self.appointment)
        command=open_command(
            tenant=self.tenant,user=self.user,appointment=self.appointment
        )
        add_service_item(command=command,service=self.service,primary=True)
        add_product_item(command=command,product=self.product,quantity=1)
        command.refresh_from_db()
        self.assertEqual(command.total_amount,Decimal("60.00"))

        register_payment(command=command,user=self.user,method="pix",amount="60.00")
        close_command(command=command,user=self.user)

        self.product.refresh_from_db()
        self.appointment.refresh_from_db()
        command.refresh_from_db()

        self.assertEqual(command.status,BarberCommand.Status.CLOSED)
        self.assertEqual(self.product.stock,Decimal("4.000"))
        self.assertEqual(self.appointment.status,Appointment.Status.COMPLETED)
        self.assertTrue(ProductStockMovement.objects.filter(type="command").exists())
        self.assertTrue(FinancialTransaction.objects.filter(source_type="barber_command",status="paid").exists())
        self.assertGreaterEqual(ProfessionalCommission.objects.count(),2)
