from django.test import TestCase

from accounts.models import User
from billing.models import Module,TenantModule
from scheduling.models import Customer,Professional
from tenants.models import Tenant

from .services import create_record,read_record


class MedicalRecordTests(TestCase):
    def test_record_is_encrypted_at_rest_and_readable(self):
        tenant=Tenant.objects.create(name="Clínica",slug="health-test",status=Tenant.Status.ACTIVE)
        module=Module.objects.create(slug="medical_records-test",name="Prontuários Test")
        # Entitlement helper uses the canonical slug.
        module.slug="medical_records"
        module.save(update_fields=["slug"])
        TenantModule.objects.create(tenant=tenant,module=module,enabled=True)
        user=User.objects.create_user(
            email="doctor@example.com",password="StrongPassword!123",tenant=tenant
        )
        customer=Customer.objects.create(tenant=tenant,name="Paciente")
        professional=Professional.objects.create(tenant=tenant,user=user,name="Dra. Teste")
        content="Informação clínica sensível"
        entry=create_record(
            tenant=tenant,customer=customer,professional=professional,
            title="Evolução",content=content,user=user,
        )
        self.assertNotIn(content,entry.content_encrypted)
        self.assertEqual(read_record(entry=entry,user=user),content)
        self.assertEqual(entry.access_log.count(),2)
