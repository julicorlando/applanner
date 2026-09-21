from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from finance.models import FinancialTransaction,Product
from scheduling.models import Appointment,Customer,Professional,Service
from tenants.models import Tenant

from .models import AutoCommand,AutoCommandItem,AutoCommandPayment,Job,Vehicle
from .services import close_command


class AutoCommandTests(TestCase):
    def test_close_command_posts_finance_and_stock(self):
        tenant=Tenant.objects.create(name="Auto",slug="auto-test",status=Tenant.Status.ACTIVE)
        user=User.objects.create_user(email="auto@example.com",password="StrongPassword!123",tenant=tenant)
        customer=Customer.objects.create(tenant=tenant,name="Cliente")
        professional=Professional.objects.create(tenant=tenant,name="Técnico",commission_percent=Decimal("20"))
        service=Service.objects.create(tenant=tenant,name="Detailing",duration_minutes=60,price=Decimal("100"))
        now=timezone.now()
        appointment=Appointment.objects.create(
            tenant=tenant,customer=customer,professional=professional,service=service,
            starts_at=now,ends_at=now+timedelta(hours=1),status=Appointment.Status.CONFIRMED,created_by=user,
        )
        vehicle=Vehicle.objects.create(tenant=tenant,customer=customer,plate="ABC1D23",model="Sedan")
        job=Job.objects.create(tenant=tenant,appointment=appointment,vehicle=vehicle,assigned_professional=professional)
        command=AutoCommand.objects.create(
            tenant=tenant,job=job,appointment=appointment,customer=customer,vehicle=vehicle,
            opened_by=user,opened_at=now,
        )
        product=Product.objects.create(
            tenant=tenant,name="Cera",sku="CERA",sale_price=Decimal("20"),
            cost_price=Decimal("5"),stock=Decimal("3"),
        )
        AutoCommandItem.objects.create(
            command=command,tenant=tenant,item_type=AutoCommandItem.Type.SERVICE,
            service=service,professional=professional,description="Detailing",
            quantity=1,unit_price=Decimal("100"),total_amount=Decimal("100"),
        )
        AutoCommandItem.objects.create(
            command=command,tenant=tenant,item_type=AutoCommandItem.Type.PRODUCT,
            product=product,description="Cera",quantity=1,unit_price=Decimal("20"),
            total_amount=Decimal("20"),cost_snapshot=Decimal("5"),
        )
        AutoCommandPayment.objects.create(
            command=command,tenant=tenant,payment_method="pix",amount=Decimal("120"),
            received_by=user,received_at=now,
        )

        close_command(command=command,user=user)
        product.refresh_from_db()
        command.refresh_from_db()
        appointment.refresh_from_db()

        self.assertEqual(product.stock,Decimal("2"))
        self.assertEqual(command.status,AutoCommand.Status.CLOSED)
        self.assertEqual(appointment.status,Appointment.Status.COMPLETED)
        self.assertTrue(FinancialTransaction.objects.filter(
            tenant=tenant,source_type="auto_command",source_id=command.pk,status="paid"
        ).exists())
