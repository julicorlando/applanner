from datetime import datetime,time,timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.test import TestCase,Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from auto.models import Job,AutoCommand,Vehicle
from billing.models import Module,TenantModule
from finance.models import Product,FinancialTransaction,ProfessionalCommission
from scheduling.models import Appointment,Professional,ProfessionalAvailability,Service
from tenants.models import Tenant


class AutoAnonymousJourneyTests(TestCase):
    def test_public_vehicle_booking_to_delivery_stock_commission_and_finance(self):
        tenant=Tenant.objects.create(name="Auto QA",slug="auto-journey",category="auto",public_enabled=True,status="active")
        for slug in ("products","stock","finance"):
            module=Module.objects.create(slug=slug,name=slug)
            TenantModule.objects.create(tenant=tenant,module=module,enabled=True)
        owner=User.objects.create_user(email="auto-journey@example.test",tenant=tenant,role="auto-manager")
        prof=Professional.objects.create(tenant=tenant,name="Técnico QA",commission_percent=20)
        service=Service.objects.create(tenant=tenant,name="Lavagem QA",duration_minutes=60,price=100)
        prof.services.add(service)
        day=timezone.localdate()+timedelta(days=2)
        ProfessionalAvailability.objects.create(tenant=tenant,professional=prof,weekday=day.isoweekday(),start_time=time(8),end_time=time(18))
        start=datetime.combine(day,time(10),tzinfo=ZoneInfo(tenant.timezone))
        self.assertEqual(self.client.get(reverse("portal-home")).status_code,302)
        self.assertContains(self.client.get(reverse("tenant-public",args=[tenant.slug])),"Placa do veículo")
        data={"service_id":service.pk,"professional_id":prof.pk,"starts_at":start.isoformat(),
            "name":"Cliente Auto QA","phone":"81900000000","vehicle_plate":"ABC1D23","vehicle_model":"Onix","payment_choice":"on_site"}
        response=self.client.post(reverse("public-booking",args=[tenant.slug]),data,content_type="application/json")
        self.assertEqual(response.status_code,201,response.content)
        appointment=Appointment.objects.get()
        self.assertEqual(appointment.vehicle.plate,"ABC1D23")
        self.assertEqual(appointment.customer.email,"")
        manager=Client()
        manager.force_login(owner)
        agenda=manager.get(reverse("portal-resource-list",args=["agenda","agendamentos"]),{"q":prof.name})
        self.assertEqual([r["obj"].pk for r in agenda.context["rows"]],[appointment.pk])
        response=manager.post(reverse("portal-resource-create",args=["auto","ordens"]),{
            "appointment":appointment.pk,"vehicle":Vehicle.objects.get().pk,"assigned_professional":prof.pk,
            "status":"scheduled","fuel_level":"unknown"})
        self.assertEqual(response.status_code,302,response.content)
        job=Job.objects.get(appointment=appointment)
        action=reverse("auto-job-action",args=[job.pk])
        self.assertEqual(manager.post(action,{"action":"open_command"}).status_code,302)
        command=AutoCommand.objects.get(job=job)
        command_action=reverse("auto-command-action",args=[command.pk])
        product=Product.objects.create(tenant=tenant,name="Cera QA",sku="QA",sale_price=20,stock=3)
        for values in (
            {"action":"service","service":service.pk,"professional":prof.pk,"quantity":1,"unit_price":100,"discount":0},
            {"action":"product","product":product.pk,"quantity":1,"unit_price":20,"discount":0},
            {"action":"payment","payment_method":"cash","amount":120},
            {"action":"close"},
        ):
            self.assertEqual(manager.post(command_action,values).status_code,302)
        command.refresh_from_db(); job.refresh_from_db(); appointment.refresh_from_db(); product.refresh_from_db()
        self.assertEqual(command.status,"closed")
        self.assertEqual(job.status,Job.Status.DELIVERED)
        self.assertEqual(appointment.status,"completed")
        self.assertEqual(product.stock,Decimal("2"))
        self.assertEqual(FinancialTransaction.objects.get(tenant=tenant,source_type="auto_command").amount,Decimal("120"))
        self.assertEqual(ProfessionalCommission.objects.get(tenant=tenant,source_type="auto_service").commission_amount,Decimal("20"))
        self.assertEqual(self.client.get(reverse("auto-job-detail",args=[job.pk])).status_code,302)
