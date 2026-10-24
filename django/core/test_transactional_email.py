import hashlib
from datetime import timedelta

from django.core import mail
from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import EmailVerificationToken,User
from applanner.transactional_email import render_email
from communications.models import Notification
from communications.tasks import send_notification
from operations.models import PlatformEmailTemplate
from scheduling.models import Appointment,Customer,Service
from tenants.models import Tenant


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TransactionalEmailTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email="master@example.test",password="StrongPassword123!")
        self.tenant=Tenant.objects.create(name="Empresa X",slug="empresa-x",status=Tenant.Status.ACTIVE)
        self.owner=User.objects.create_user(email="owner@example.test",password="StrongPassword123!",
            first_name="Júlio",tenant=self.tenant,role="owner")

    def test_only_master_edits_and_required_link_cannot_be_removed(self):
        url=reverse("master-email-template-edit",args=["email_verification"])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code,403)
        self.client.force_login(self.master)
        response=self.client.post(url,{"subject":"Confirme a conta","body":"Olá {nome}"})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"{url_confirmacao}")
        self.assertFalse(PlatformEmailTemplate.objects.exists())
        self.assertEqual(self.client.post(url,{"subject":"Conta","body":"Link literal: {{url_confirmacao}}"}).status_code,200)
        self.assertFalse(PlatformEmailTemplate.objects.exists())
        response=self.client.post(url,{"subject":"Olá {nome}","body":"Acesse {url_confirmacao}"})
        self.assertEqual(response.status_code,302)
        subject,text,html=render_email("email_verification",{
            "nome":"Júlio","url_confirmacao":"https://example.test/verify/",
        })
        self.assertEqual(subject,"Olá Júlio")
        self.assertIn("https://example.test/verify/",text)
        self.assertIn('href="https://example.test/verify/"',html)
        self.client.post(url,{"action":"reset"})
        self.assertFalse(PlatformEmailTemplate.objects.exists())

    def test_html_escapes_customer_data_and_rejects_attribute_access(self):
        with self.assertRaises(ValueError):
            from applanner.transactional_email import validate_copy
            validate_copy("booking_confirmation","Olá {nome.__class__}","{servico} {data_hora}")
        _,_,html=render_email("booking_confirmation",{
            "nome":"<script>alert(1)</script>","empresa":"Empresa X",
            "servico":"Corte","profissional":"Ana","data_hora":"29/09/2026 às 14:00",
        })
        self.assertNotIn("<script>",html)

    def test_password_reset_uses_custom_copy(self):
        PlatformEmailTemplate.objects.create(key="password_reset",subject="Recuperar acesso, {nome}",
            body="Clique em {url_redefinicao}")
        response=self.client.post(reverse("accounts:password-reset-request"),{"email":self.owner.email})
        self.assertEqual(response.status_code,302)
        self.assertEqual(len(mail.outbox),1)
        self.assertEqual(mail.outbox[0].subject,"Recuperar acesso, Júlio")
        self.assertIn("/account/password-reset/",mail.outbox[0].body)

    def test_verified_account_and_confirmed_booking_queue_once(self):
        raw="verification-test-token"
        EmailVerificationToken.objects.create(user=self.owner,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),expires_at=timezone.now()+timedelta(hours=1))
        self.assertEqual(self.client.get(reverse("accounts:verify-email",args=[raw])).status_code,302)
        self.assertEqual(Notification.objects.filter(template_key="account_confirmed").count(),1)
        customer=Customer.objects.create(tenant=self.tenant,name="Cliente",email="cliente@example.test")
        service=Service.objects.create(tenant=self.tenant,name="Corte",duration_minutes=30,price=50)
        start=timezone.now()+timedelta(days=2)
        appointment=Appointment.objects.create(tenant=self.tenant,customer=customer,service=service,
            starts_at=start,ends_at=start+timedelta(minutes=30),status=Appointment.Status.PENDING)
        self.assertFalse(Notification.objects.filter(template_key="booking_confirmation").exists())
        appointment.status=Appointment.Status.CONFIRMED
        appointment.save(update_fields=["status"])
        appointment.save(update_fields=["notes"])
        notification=Notification.objects.get(template_key="booking_confirmation")
        self.assertEqual(notification.destination,customer.email)
        self.assertIn("Corte",notification.payload["text"])
        send_notification(notification.pk)
        notification.refresh_from_db()
        self.assertEqual(notification.status,Notification.Status.SENT)
        self.assertEqual(mail.outbox[-1].to,[customer.email])
        self.assertEqual(len(mail.outbox[-1].alternatives),1)
