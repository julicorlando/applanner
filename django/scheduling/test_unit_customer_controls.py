"""Customer management must honor the appointment's unit, not global defaults."""
import hashlib
from datetime import time,timedelta

from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone

from scheduling.models import Appointment,Customer,Professional,ProfessionalAvailability,Service,TenantScheduleSettings
from tenants.models import Tenant,Unit


@override_settings(CACHES={"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache"}},STORAGES={"default":{"BACKEND":"django.core.files.storage.FileSystemStorage"},
    "staticfiles":{"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage"}})
class UnitCustomerControlsTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Rede',slug='unit-customer-controls',status=Tenant.Status.ACTIVE)
        TenantScheduleSettings.objects.create(tenant=self.tenant,customer_can_cancel=True,
            customer_can_reschedule=True,cancel_notice_minutes=0)
        self.unit=Unit.objects.create(tenant=self.tenant,name='Centro',active=True,
            schedule_overrides={'customer_can_cancel':False,'customer_can_reschedule':False})
        self.other_unit=Unit.objects.create(tenant=self.tenant,name='Bairro',active=True)
        self.professional=Professional.objects.create(tenant=self.tenant,unit=self.unit,name='Ana')
        self.other_professional=Professional.objects.create(tenant=self.tenant,unit=self.other_unit,name='Bia')
        self.service=Service.objects.create(tenant=self.tenant,name='Corte',duration_minutes=30,price=40)
        self.customer=Customer.objects.create(tenant=self.tenant,name='Cliente',phone='5581999991234')
        self.start=timezone.now()+timedelta(days=2)
        self.start=self.start.replace(hour=12,minute=0,second=0,microsecond=0)
        for professional in (self.professional,self.other_professional):
            ProfessionalAvailability.objects.create(tenant=self.tenant,professional=professional,
                weekday=self.start.astimezone(timezone.get_current_timezone()).isoweekday(),
                start_time=time(0),end_time=time(23,59))
        self.token='unit-customer-management-test'
        self.appointment=Appointment.objects.create(tenant=self.tenant,unit=self.unit,
            customer=self.customer,professional=self.professional,service=self.service,
            starts_at=self.start,ends_at=self.start+timedelta(minutes=30),
            status=Appointment.Status.CONFIRMED,
            customer_manage_token_hash=hashlib.sha256(self.token.encode()).hexdigest())
        self.api_url=reverse('public-appointment-manage',args=[self.token])
        self.page_url=reverse('public-appointment-page',args=[self.token])

    def test_unit_disables_actions_despite_enabled_global_defaults(self):
        response=self.client.get(self.api_url)
        self.assertFalse(response.json()['can_cancel'])
        self.assertFalse(response.json()['can_reschedule'])
        self.assertEqual(self.client.delete(self.api_url).status_code,403)
        self.assertEqual(self.client.patch(self.api_url,{'starts_at':(self.start+timedelta(hours=1)).isoformat()},
            content_type='application/json').status_code,403)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,Appointment.Status.CONFIRMED)
        self.assertEqual(self.appointment.starts_at,self.start)

    def test_unit_enables_actions_despite_disabled_global_defaults(self):
        TenantScheduleSettings.objects.filter(tenant=self.tenant).update(customer_can_cancel=False,
            customer_can_reschedule=False)
        self.unit.schedule_overrides={'customer_can_cancel':True,'customer_can_reschedule':True,'cancel_notice_minutes':0}
        self.unit.save(update_fields=['schedule_overrides'])
        response=self.client.get(self.api_url)
        self.assertTrue(response.json()['can_cancel'])
        self.assertTrue(response.json()['can_reschedule'])
        new_start=self.start+timedelta(hours=1)
        self.assertEqual(self.client.patch(self.api_url,{'starts_at':new_start.isoformat(),
            'professional_id':self.professional.pk},content_type='application/json').status_code,200)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.starts_at,new_start)
        self.assertEqual(self.client.delete(self.api_url).status_code,204)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,Appointment.Status.CANCELLED)

    def test_unit_notice_blocks_actions_before_its_deadline(self):
        self.unit.schedule_overrides={'customer_can_cancel':True,'customer_can_reschedule':True,
            'cancel_notice_minutes':60*24*3}
        self.unit.save(update_fields=['schedule_overrides'])
        response=self.client.get(self.api_url)
        self.assertFalse(response.json()['can_cancel'])
        self.assertFalse(response.json()['can_reschedule'])
        self.assertEqual(self.client.delete(self.api_url).status_code,403)

    def test_public_management_page_cannot_move_booking_to_another_unit(self):
        self.unit.schedule_overrides={'customer_can_cancel':True,'customer_can_reschedule':True}
        self.unit.save(update_fields=['schedule_overrides'])
        page=self.client.get(self.page_url)
        self.assertEqual([row.pk for row in page.context['professionals']],[self.professional.pk])
        self.assertEqual(self.client.post(self.page_url,{'action':'reschedule',
            'starts_at':(self.start+timedelta(hours=1)).isoformat(),
            'professional_id':self.other_professional.pk}).status_code,302)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.professional_id,self.professional.pk)
        self.assertEqual(self.appointment.unit_id,self.unit.pk)
        self.assertEqual(self.appointment.starts_at,self.start)
