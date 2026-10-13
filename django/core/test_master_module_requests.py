from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from billing.models import Module,ModuleRequest
from tenants.models import Tenant


class MasterModuleRequestPageTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email="master-module-page@example.test",password="StrongPassword123!")
        self.tenant=Tenant.objects.create(name="Empresa de teste",slug="empresa-modulos")
        self.module=Module.objects.create(name="WhatsApp",slug="whatsapp",active=True)
        self.client.force_login(self.master)
        self.url=reverse("master-resource-create",args=["solicitacoes-modulos"])

    def test_old_new_request_url_guides_master_to_selected_tenant(self):
        self.assertRedirects(self.client.get(self.url),reverse("portal-home"),fetch_redirect_response=False)
        session=self.client.session
        session["portal_tenant_id"]=self.tenant.pk
        session.save()
        self.assertRedirects(self.client.get(self.url),reverse("tenant-whatsapp-settings"),fetch_redirect_response=False)
        self.assertRedirects(self.client.post(self.url,{
            "tenant":self.tenant.pk,"module":self.module.pk,"quoted_monthly_price":"0", "status":"pending",
        }),reverse("tenant-whatsapp-settings"),fetch_redirect_response=False)
        self.assertFalse(ModuleRequest.objects.exists())

    def test_requests_list_has_no_generic_create_or_edit(self):
        response=self.client.get(reverse("master-resource-list",args=["solicitacoes-modulos"]))
        self.assertContains(response,"Solicitações de contratação são abertas pela empresa")
        self.assertNotContains(response,"Novo cadastro")
        self.assertNotContains(response,"/master/solicitacoes-modulos/novo/")
