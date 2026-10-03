from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Module, TenantModule, TenantPaymentConnection, TenantPaymentTransaction
from communications.models import Notification, TenantWhatsAppConnection
from legal.models import LegalDocument
from scheduling.models import Appointment, Professional, ProfessionalAvailability, Service, TenantScheduleSettings
from tenants.models import Tenant


class PublicBookingPaymentTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Clínica",slug="clinica-pix",public_slug="clinica-pix",
            public_enabled=True,status=Tenant.Status.ACTIVE)
        self.service=Service.objects.create(tenant=self.tenant,name="Consulta",duration_minutes=30,price=Decimal("100"))
        self.professional=Professional.objects.create(tenant=self.tenant,name="Dra. Ana")
        self.professional.services.add(self.service)
        day=timezone.localdate()+timedelta(days=2)
        self.day=day
        ProfessionalAvailability.objects.create(tenant=self.tenant,professional=self.professional,
            weekday=day.isoweekday(),start_time=time(8),end_time=time(18))
        self.settings=TenantScheduleSettings.objects.create(tenant=self.tenant,allow_partial_payment=True,
            allow_full_payment=True,deposit_percent=25,online_booking_payments_enabled=True)
        self.url=reverse("public-booking",args=[self.tenant.slug])

    def book(self,**kwargs):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        data={"service_id":self.service.pk,"professional_id":self.professional.pk,
            "starts_at":datetime.combine(self.day,time(9),tzinfo=ZoneInfo(self.tenant.timezone)).isoformat(),
            "name":"Cliente","phone":"(81) 99999-9999","email":"cliente@example.test",**kwargs}
        return self.client.post(self.url,data,content_type="application/json")

    @patch("billing.payment_services.has_connected_tenant_gateway",return_value=True)
    def test_partial_pix_is_snapshotted_and_confirmation_queued(self,_gateway):
        TenantWhatsAppConnection.objects.create(tenant=self.tenant,enabled=True)
        response=self.book(payment_choice="partial")
        self.assertEqual(response.status_code,201,response.content)
        appointment=Appointment.objects.get(pk=response.json()["id"])
        self.assertEqual(appointment.booking_payment_amount,Decimal("25.00"))
        self.assertEqual(Notification.objects.filter(template_key="appointment_confirmation",
            destination="5581999999999").count(),1)
        self.settings.deposit_percent=90
        self.settings.save()
        with patch("billing.payment_services.has_connected_tenant_gateway",return_value=True),\
             patch("billing.payment_services.create_tenant_pix") as pix:
            manage=reverse("public-appointment-page",args=[response.json()["manage_token"]])
            self.assertContains(self.client.get(manage),"R$ 25,00")
            self.assertEqual(self.client.post(manage,{"action":"pay"}).status_code,302)
            self.assertEqual(pix.call_args.kwargs["amount"],Decimal("25.00"))

    def test_online_choice_needs_gateway_and_email(self):
        self.assertEqual(self.book(payment_choice="partial").status_code,400)
        self.assertFalse(Appointment.objects.exists())
        with patch("billing.payment_services.has_connected_tenant_gateway",return_value=True):
            self.assertEqual(self.book(payment_choice="partial",email="").status_code,400)
        self.assertEqual(self.book(payment_choice="on_site").status_code,201)


class MasterTermsAndAccessTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email="master-terms@example.test",password="StrongPassword123!")
        self.tenant=Tenant.objects.create(name="Empresa",slug="empresa-terms",status=Tenant.Status.ACTIVE)
        self.owner=User.objects.create_user(email="owner-terms@example.test",password="StrongPassword123!",
            tenant=self.tenant,role="owner")
        self.module=Module.objects.create(name="WhatsApp",slug="whatsapp",active=True)
        self.client.force_login(self.master)

    def test_master_controls_tenant_module_and_queues_terms(self):
        url=reverse("master-tenant-access",args=[self.tenant.pk])
        self.assertContains(self.client.get(url),"Acessos")
        self.client.post(url,{"modules":[str(self.module.pk)]})
        self.assertTrue(TenantModule.objects.get(tenant=self.tenant,module=self.module).enabled)
        self.client.post(url,{})
        self.assertFalse(TenantModule.objects.get(tenant=self.tenant,module=self.module).enabled)
        LegalDocument.objects.create(type=LegalDocument.Type.TERMS,version="test-v1",
            title="Termos",content="Texto",status=LegalDocument.Status.PUBLISHED,published_at=timezone.now())
        # The new document requires acceptance before the Master may send invitations.
        self.assertEqual(self.client.get(reverse("legal-accept")).status_code,200)
        self.client.post(reverse("legal-accept"),{"accept":"yes"})
        self.assertEqual(self.client.post(reverse("master-send-tenant-terms",args=[self.tenant.pk])).status_code,302)
        notice=Notification.objects.get(template_key="tenant_terms_acceptance")
        self.assertEqual(notice.destination,self.owner.email)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/").status_code,302)


class AutoPublicBookingTests(PublicBookingPaymentTests):
    def setUp(self):
        super().setUp()
        self.tenant.category="auto"
        self.tenant.save(update_fields=["category"])

    def book(self,**kwargs):
        return super().book(vehicle_plate="ABC1D23",vehicle_model="Onix",**kwargs)

    def test_vehicle_is_required_and_linked_only_to_its_owner(self):
        from auto.models import Vehicle
        page=self.client.get(reverse("tenant-public",args=[self.tenant.slug]))
        self.assertContains(page,"Placa do veículo")
        self.assertEqual(super().book().status_code,400)
        response=self.book()
        self.assertEqual(response.status_code,201,response.content)
        appointment=Appointment.objects.get(pk=response.json()["id"])
        self.assertEqual(appointment.vehicle.plate,"ABC1D23")
        self.assertEqual(Vehicle.objects.count(),1)


class ProfessionalPrepaidTests(TestCase):
    setUp=PublicBookingPaymentTests.setUp
    book=PublicBookingPaymentTests.book
    def test_paid_deposit_is_visible_and_balance_method_is_recorded(self):
        with patch("billing.payment_services.has_connected_tenant_gateway",return_value=True):
            response=self.book(payment_choice="partial")
        appointment=Appointment.objects.get(pk=response.json()["id"])
        connection=TenantPaymentConnection.objects.create(tenant=self.tenant,environment="sandbox",
            status=TenantPaymentConnection.Status.CONNECTED)
        TenantPaymentTransaction.objects.create(tenant=self.tenant,connection=connection,
            reference_type="appointment",reference_id=appointment.pk,external_reference="DEPOSIT-1",
            idempotency_key="deposit-1",method="pix",gross_amount=Decimal("25"),net_amount=Decimal("25"),
            status=TenantPaymentTransaction.Status.PAID)
        appointment.starts_at=timezone.now()-timedelta(hours=1)
        appointment.ends_at=timezone.now()-timedelta(minutes=30)
        appointment.save(update_fields=["starts_at","ends_at"])
        user=User.objects.create_user(email="prof-prepaid@example.test",password="StrongPassword123!",
            tenant=self.tenant,role="professional")
        self.professional.user=user
        self.professional.save(update_fields=["user"])
        self.client.force_login(user)
        url=reverse("professional-appointment",args=[appointment.pk])
        self.assertContains(self.client.get(url),"Sinal pago online")
        self.assertEqual(self.client.post(url,{"outcome":"completed","payment_method":"cash","quantity":"1"}).status_code,302)
        from finance.models import FinancialTransaction
        finance=FinancialTransaction.objects.get(appointment=appointment)
        self.assertEqual(finance.amount,Decimal("100"))
        self.assertEqual(finance.payment_method,"pix+cash")
