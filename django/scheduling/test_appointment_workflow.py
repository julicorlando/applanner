import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.signing import dumps
from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from communications.models import Notification,TenantWhatsAppConnection,WhatsAppConversation,WhatsAppMessage
from finance.models import FinancialTransaction,Product,ProfessionalCommission,Sale
from scheduling.models import Appointment,AppointmentRating,AppointmentSettlement,Customer,Professional,Service
from scheduling.settlement import settle_appointment
from tenants.models import Tenant


@override_settings(PUBLIC_BASE_URL="https://applanner.example.test",MASTER_WHATSAPP_GATEWAY_TOKEN="testing-gateway-secret")
class AppointmentWorkflowTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Barbearia",slug="barbearia-workflow",status=Tenant.Status.ACTIVE)
        self.other=Tenant.objects.create(name="Outra",slug="outra-workflow",status=Tenant.Status.ACTIVE)
        self.owner=User.objects.create_user(email="owner-workflow@example.test",password="StrongPassword123!",
            tenant=self.tenant,role="owner")
        self.prof_user=User.objects.create_user(email="prof-workflow@example.test",password="StrongPassword123!",
            tenant=self.tenant,role="professional")
        self.professional=Professional.objects.create(tenant=self.tenant,user=self.prof_user,name="Ana",
            commission_percent=Decimal("40"))
        self.customer=Customer.objects.create(tenant=self.tenant,name="Júlio Cliente",phone="5581999999999",
            email="cliente-workflow@example.test")
        self.service=Service.objects.create(tenant=self.tenant,name="Corte",duration_minutes=30,price=Decimal("80"))
        start=timezone.now()-timedelta(hours=2)
        self.appointment=Appointment.objects.create(tenant=self.tenant,customer=self.customer,
            professional=self.professional,service=self.service,starts_at=start,
            ends_at=start+timedelta(minutes=30),service_price_snapshot=Decimal("80"),status=Appointment.Status.CONFIRMED)

    def test_professional_closes_service_and_product_exactly_once(self):
        product=Product.objects.create(tenant=self.tenant,name="Pomada",sale_price=Decimal("30"),
            stock=Decimal("4"),commission_type=Product.CommissionType.PERCENT,commission_value=Decimal("10"))
        self.client.force_login(self.prof_user)
        url=reverse("professional-appointment",args=[self.appointment.pk])
        post={"outcome":"completed","payment_method":"pix","product":product.pk,"quantity":"2"}
        self.assertEqual(self.client.post(url,post).status_code,302)
        self.appointment.refresh_from_db();product.refresh_from_db()
        self.assertEqual(self.appointment.status,Appointment.Status.COMPLETED)
        self.assertEqual(product.stock,Decimal("2"))
        settlement=AppointmentSettlement.objects.get(appointment=self.appointment)
        self.assertEqual(settlement.sale.total,Decimal("60"))
        self.assertEqual(FinancialTransaction.objects.get(appointment=self.appointment).amount,Decimal("80"))
        self.assertEqual(set(ProfessionalCommission.objects.filter(tenant=self.tenant).values_list("commission_amount",flat=True)),
            {Decimal("32"),Decimal("6")})
        self.assertEqual(self.client.post(url,post).status_code,200)
        self.assertEqual(Sale.objects.count(),1)
        self.assertEqual(ProfessionalCommission.objects.count(),2)

    def test_no_show_and_other_professional_are_restricted(self):
        another=Professional.objects.create(tenant=self.tenant,name="Bia")
        other_appt=Appointment.objects.create(tenant=self.tenant,customer=self.customer,professional=another,
            service=self.service,starts_at=self.appointment.starts_at,ends_at=self.appointment.ends_at,
            status=Appointment.Status.CONFIRMED)
        self.client.force_login(self.prof_user)
        self.assertEqual(self.client.get(reverse("professional-appointment",args=[other_appt.pk])).status_code,404)
        self.client.post(reverse("professional-appointment",args=[self.appointment.pk]),
            {"outcome":"no_show","payment_method":"","quantity":"1"})
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,Appointment.Status.NO_SHOW)
        self.assertFalse(FinancialTransaction.objects.filter(appointment=self.appointment).exists())

    def test_rating_is_1_to_5_only_once_and_tenant_scoped(self):
        settle_appointment(appointment_id=self.appointment.pk,professional=self.professional,
            user=self.prof_user,attended=True,payment_method="cash")
        token=dumps({"appointment":self.appointment.pk},salt="appointment-rating")
        url=reverse("public-appointment-rating",args=[token])
        self.assertContains(self.client.get(url),"Como foi o atendimento?")
        self.client.post(url,{"score":"6"})
        self.assertFalse(AppointmentRating.objects.exists())
        self.client.post(url,{"score":"5"})
        self.client.post(url,{"score":"1"})
        self.assertEqual(AppointmentRating.objects.get().score,5)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("tenant-ratings")),"Ana")
        self.assertContains(self.client.get(reverse("tenant-ratings")),"5,0")
        response=self.client.get(reverse("tenant-ratings"))
        self.assertContains(response,'role="meter"')
        self.assertContains(response,'aria-valuenow="5.0"')
        self.assertContains(response,"Muito satisfeito")
        self.assertEqual(response.context["professionals"][0].satisfaction_position,100)
        Professional.objects.create(tenant=self.tenant,name="Sem avaliações")
        response=self.client.get(reverse("tenant-ratings"))
        self.assertContains(response,'role="meter"',count=1)
        self.assertContains(response,"Aguardando a primeira avaliação")

    def test_qr_gateway_callback_requests_cancellation_and_staff_releases_slot(self):
        TenantWhatsAppConnection.objects.create(tenant=self.tenant,enabled=True)
        number=self.customer.phone
        conversation=WhatsAppConversation.objects.create(tenant=self.tenant,customer=self.customer,
            appointment=self.appointment,wa_id=number,last_message_at=timezone.now())
        url=reverse("tenant-whatsapp-receive")
        data={"tenant_id":self.tenant.pk,"from":number+"@s.whatsapp.net","id":"inbound-1",
              "text":"Quero cancelar meu horário"}
        self.assertEqual(self.client.post(url,json.dumps(data),content_type="application/json").status_code,403)
        self.assertEqual(self.client.post(url,json.dumps(data),content_type="application/json",
            HTTP_AUTHORIZATION="Bearer testing-gateway-secret").status_code,200)
        conversation.refresh_from_db()
        self.assertEqual(conversation.context["cancel_requested_appointment_id"],self.appointment.pk)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse("communications-conversation-action",args=[conversation.pk]),
            {"action":"cancel_appointment"}).status_code,302)
        self.appointment.refresh_from_db();conversation.refresh_from_db()
        self.assertEqual(self.appointment.status,Appointment.Status.CANCELLED)
        self.assertEqual(conversation.status,WhatsAppConversation.Status.CLOSED)
        with patch("communications.tenant_whatsapp.gateway") as gateway:
            self.client.post(reverse("communications-conversation-action",args=[conversation.pk]),
                {"action":"prepared","kind":"reminder"})
            gateway.assert_not_called()

    def test_appointment_notification_uses_only_correct_tenant_gateway(self):
        TenantWhatsAppConnection.objects.create(tenant=self.tenant,enabled=True)
        from communications.tenant_whatsapp import queue_appointment_whatsapp,send_appointment_notification
        notification=queue_appointment_whatsapp(self.appointment,"confirmation")
        self.assertEqual(notification.destination,self.customer.phone)
        with patch("communications.tenant_whatsapp.gateway",return_value={"id":"outbound-test"}) as gateway:
            self.assertEqual(send_appointment_notification(notification),"outbound-test")
            self.assertEqual(gateway.call_args.args[0],self.tenant)
        conversation=WhatsAppConversation.objects.get(tenant=self.tenant,wa_id=self.customer.phone)
        self.assertEqual(conversation.appointment,self.appointment)
        self.assertEqual(WhatsAppMessage.objects.get(conversation=conversation).body.count("Júlio"),1)
        self.assertFalse(WhatsAppConversation.objects.filter(tenant=self.other).exists())

    def test_completion_asks_for_rating_over_connected_whatsapp_and_closes_chat(self):
        TenantWhatsAppConnection.objects.create(tenant=self.tenant,enabled=True)
        conversation=WhatsAppConversation.objects.create(tenant=self.tenant,customer=self.customer,
            appointment=self.appointment,wa_id=self.customer.phone,last_message_at=timezone.now())
        settle_appointment(appointment_id=self.appointment.pk,professional=self.professional,
            user=self.prof_user,attended=True,payment_method="pix")
        conversation.refresh_from_db()
        self.assertEqual(conversation.status,WhatsAppConversation.Status.CLOSED)
        invitation=Notification.objects.get(template_key="appointment_feedback")
        self.assertIn("nota de 1 a 5",invitation.payload["text"])
        with patch("communications.tenant_whatsapp.gateway",return_value={"id":"rating-invite"}):
            from communications.tenant_whatsapp import send_appointment_notification
            self.assertEqual(send_appointment_notification(invitation),"rating-invite")
        conversation.refresh_from_db()
        self.assertEqual(conversation.status,WhatsAppConversation.Status.CLOSED)
