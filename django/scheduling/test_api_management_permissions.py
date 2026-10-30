from datetime import timedelta

from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from scheduling.models import Appointment,Customer,Professional,Service
from tenants.models import Tenant


@override_settings(CACHES={"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache"}})
class AppointmentManagementAPIPermissionTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='API empresa',slug='api-management-permissions',status=Tenant.Status.ACTIVE)
        self.customer=Customer.objects.create(tenant=self.tenant,name='Cliente')
        self.professional=Professional.objects.create(tenant=self.tenant,name='Profissional')
        self.service=Service.objects.create(tenant=self.tenant,name='Corte',duration_minutes=30,price=40)
        start=timezone.now()+timedelta(days=2)
        self.appointment=Appointment.objects.create(tenant=self.tenant,customer=self.customer,
            professional=self.professional,service=self.service,starts_at=start,
            ends_at=start+timedelta(minutes=30))
        self.list_url=reverse('appointment-list')
        self.detail_url=reverse('appointment-detail',args=[self.appointment.pk])

    def login_role(self,role):
        user=User.objects.create_user(email=role+'-agenda-api@example.test',password='test-password',
            tenant=self.tenant,role=role)
        self.client.force_login(user)
        return user

    def test_professional_cannot_read_or_modify_general_appointment_api(self):
        user=self.login_role('professional')
        self.professional.user=user
        self.professional.save(update_fields=['user'])
        for url in (self.list_url,self.detail_url):
            self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.patch(self.detail_url,{'notes':'alterado'},content_type='application/json').status_code,403)
        self.assertEqual(self.client.delete(self.detail_url).status_code,403)
        self.assertEqual(self.client.post(self.list_url,{},content_type='application/json').status_code,403)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.notes,'')

    def test_finance_role_cannot_access_appointment_management(self):
        self.login_role('finance')
        self.assertEqual(self.client.get(self.list_url).status_code,403)
        self.assertEqual(self.client.delete(self.detail_url).status_code,403)

    def test_agenda_management_roles_retain_access(self):
        for role in ('owner','manager','reception'):
            with self.subTest(role=role):
                self.login_role(role)
                self.assertEqual(self.client.get(self.list_url).status_code,200)
                self.assertEqual(self.client.get(self.detail_url).status_code,200)

    def test_other_company_appointment_remains_inaccessible(self):
        other=Tenant.objects.create(name='Outra',slug='other-api-permissions',status=Tenant.Status.ACTIVE)
        user=User.objects.create_user(email='other-api-owner@example.test',password='test-password',tenant=other,role='owner')
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.detail_url).status_code,404)
        self.assertEqual(self.client.delete(self.detail_url).status_code,404)
