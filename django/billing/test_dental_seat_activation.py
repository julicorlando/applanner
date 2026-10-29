from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from . import test_professional_capacity_addons as fixtures
from .models import Module, Payment, TenantModuleAddon
from .module_services import request_module,review_module_request,activate_module_request


class DentalSeatActivationTests(TestCase):
    def setUp(self):
        fixtures.ProfessionalCapacityAddonTests.setUp(self)
        self.extra,_=Module.objects.get_or_create(slug="dental-professional-extra",defaults={"name":"Dentista adicional"})
        self.extra.active=True
        self.extra.addon_sellable=True
        self.extra.addon_monthly_price=Decimal("7.50")
        self.extra.save()
        self.request=request_module(tenant=self.tenant,module=self.extra,user=self.owner,note="Vaga adicional")
        review_module_request(module_request=self.request,user=self.master,approved=True,note="Aprovado")
        self.request.refresh_from_db()

    def payment(self,**overrides):
        data=dict(tenant=self.tenant,subscription=self.subscription,purpose="dental-seat",reference_id=self.request.pk,
                  provider="mercadopago",provider_payment_id="dental-test-payment",environment="sandbox",
                  amount=self.request.quoted_monthly_price,status=Payment.Status.PAID,paid_at=timezone.now())
        data.update(overrides)
        return Payment.objects.create(**data)

    def test_approval_without_paid_evidence_does_not_activate(self):
        with self.assertRaises(ValidationError):
            activate_module_request(module_request=self.request,user=self.master)
        self.assertFalse(TenantModuleAddon.objects.filter(module=self.extra).exists())
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.contracted_price,Decimal("29.90"))

    def test_pending_or_wrong_amount_or_wrong_request_payment_is_rejected(self):
        for changes in ({"status":"pending"},{"amount":Decimal("0.01")},{"reference_id":99999}):
            payment=self.payment(provider_payment_id=str(changes),**changes)
            with self.subTest(changes=changes),self.assertRaises(ValidationError):
                activate_module_request(module_request=self.request,user=self.master,financial_payment=payment)
        self.assertFalse(TenantModuleAddon.objects.filter(module=self.extra).exists())

    def test_paid_evidence_activates_using_original_quote(self):
        payment=self.payment()
        self.extra.addon_monthly_price=Decimal("99.00")
        self.extra.save()
        adjustment=activate_module_request(module_request=self.request,user=self.master,financial_payment=payment)
        self.assertEqual(adjustment.status,"applied")
        self.assertEqual(TenantModuleAddon.objects.get(module=self.extra).monthly_price,Decimal("7.50"))
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.contracted_price,Decimal("37.40"))

    def test_explicit_master_waiver_is_attributed_and_audited(self):
        activate_module_request(module_request=self.request,user=self.master,waiver_reason="Homologação autorizada")
        self.request.refresh_from_db()
        self.assertIn("Homologação autorizada",self.request.master_note)
        self.assertEqual(self.request.reviewed_by_id,self.master.pk)
        self.assertEqual(TenantModuleAddon.objects.get(module=self.extra).quantity,1)
        from core.models import AuditLog
        audit=AuditLog.objects.get(action="dental.seat.activated",entity_id=self.request.pk)
        self.assertEqual(audit.after["waiver_reason"],"Homologação autorizada")
        self.assertEqual(audit.user_id,self.master.pk)

    def test_long_prior_note_cannot_hide_waiver_reason(self):
        self.request.master_note="x"*500
        self.request.save()
        activate_module_request(module_request=self.request,user=self.master,waiver_reason="Motivo integral")
        self.request.refresh_from_db()
        self.assertIn("Motivo integral",self.request.master_note)

    def test_repeated_activation_does_not_add_another_seat(self):
        payment=self.payment()
        activate_module_request(module_request=self.request,user=self.master,financial_payment=payment)
        with self.assertRaises(ValidationError):
            activate_module_request(module_request=self.request,user=self.master,financial_payment=payment)
        self.assertEqual(TenantModuleAddon.objects.get(module=self.extra).quantity,1)
