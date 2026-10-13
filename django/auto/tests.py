from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from finance.models import FinancialTransaction,Product
from scheduling.models import Appointment,Customer,Professional,Service
from tenants.models import Tenant

from .models import AutoCommand,AutoCommandItem,AutoCommandPayment,Estimate,Job,JobStep,ServiceStep,Vehicle
from .services import add_estimate_item,close_command,create_estimate,respond_estimate,send_estimate,update_job_step


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


class AutoEstimateAndStepsTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(
            name="Auto Flow",slug="auto-flow",status=Tenant.Status.ACTIVE
        )
        self.user=User.objects.create_user(
            email="flow@example.com",password="StrongPassword!123",
            tenant=self.tenant,role="manager"
        )
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        self.professional=Professional.objects.create(tenant=self.tenant,name="Técnico")
        self.service=Service.objects.create(
            tenant=self.tenant,name="Polimento",duration_minutes=60,price=Decimal("150")
        )
        now=timezone.now()
        self.appointment=Appointment.objects.create(
            tenant=self.tenant,customer=self.customer,professional=self.professional,
            service=self.service,starts_at=now,ends_at=now+timedelta(hours=1),
            status=Appointment.Status.CONFIRMED,created_by=self.user,
        )
        self.vehicle=Vehicle.objects.create(
            tenant=self.tenant,customer=self.customer,plate="XYZ1A23",model="SUV"
        )
        self.job=Job.objects.create(
            tenant=self.tenant,appointment=self.appointment,vehicle=self.vehicle
        )

    def test_public_estimate_approval_creates_command_item(self):
        estimate,token=create_estimate(job=self.job,user=self.user)
        add_estimate_item(
            estimate=estimate,service=self.service,quantity=1,unit_price=Decimal("150")
        )
        send_estimate(estimate=estimate)
        respond_estimate(token=token,approved=True,customer_note="Aprovado")
        estimate.refresh_from_db()
        self.assertEqual(estimate.status,Estimate.Status.APPROVED)
        self.assertTrue(
            AutoCommandItem.objects.filter(
                command__job=self.job,approved_estimate=estimate
            ).exists()
        )

    def test_job_step_flow(self):
        template=ServiceStep.objects.create(
            tenant=self.tenant,service=self.service,name="Polir",sort_order=1
        )
        step=JobStep.objects.create(
            tenant=self.tenant,job=self.job,service_step=template,name="Polir"
        )
        update_job_step(
            step=step,status=JobStep.Status.IN_PROGRESS,professional=self.professional
        )
        step.refresh_from_db()
        self.assertIsNotNone(step.started_at)
        update_job_step(
            step=step,status=JobStep.Status.COMPLETED,professional=self.professional
        )
        step.refresh_from_db()
        self.assertIsNotNone(step.completed_at)
