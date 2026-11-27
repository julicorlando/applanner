from django.test import TestCase
from accounts.models import User
from tenants.models import Tenant
from commercial.models import Lead
from .models import MasterWhatsAppConversation


class MasterContactsTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email='master-contact@teste.local',password='SenhadeTeste123!')
        self.tenant=Tenant.objects.create(name='Empresa',slug='empresa-contato',phone='5581999999999')
        self.optin=Lead.objects.create(name='Com permissão',phone='5581888888888',email='opt@test.local',business_type='Empresa',consent_granted=True)
        self.blocked=Lead.objects.create(name='Bloqueado',phone='5581777777777',email='blocked@test.local',business_type='Empresa',consent_granted=True,do_not_contact=True)
        self.client.force_login(self.master)

    def test_lists_and_opens_only_eligible_contacts(self):
        response=self.client.get('/master/whatsapp/')
        self.assertContains(response,'Com permissão')
        self.assertNotContains(response,'Bloqueado')
        self.assertContains(response,'Empresa')
        self.assertEqual(self.client.post('/master/whatsapp/',{'lead_id':str(self.blocked.pk)}).status_code,302)
        self.assertFalse(MasterWhatsAppConversation.objects.exists())
        response=self.client.post('/master/whatsapp/',{'tenant_id':str(self.tenant.pk)})
        self.assertEqual(response.status_code,302)
        self.assertEqual(MasterWhatsAppConversation.objects.get().tenant,self.tenant)
