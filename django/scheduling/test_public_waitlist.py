from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from tenants.models import Tenant
from engagement.models import WaitlistEntry
from .models import Service


class PublicWaitlistTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Agenda',slug='agenda-wait',public_slug='agenda-wait',
            public_enabled=True,public_booking_enabled=True,status=Tenant.Status.ACTIVE)
        self.service=Service.objects.create(tenant=self.tenant,name='Corte',duration_minutes=30,price=20)
        self.day=timezone.localdate()+timedelta(days=2)
        self.url='/api/public/agenda-wait/waitlist/'
        self.payload={'service_id':self.service.pk,'date':self.day.isoformat(),
            'name':'Cliente Teste','phone':'5581999999999'}

    def test_no_slots_allows_entry_once(self):
        first=self.client.post(self.url,self.payload,content_type='application/json')
        second=self.client.post(self.url,self.payload,content_type='application/json')
        self.assertEqual(first.status_code,201,first.content)
        self.assertEqual(second.status_code,200,second.content)
        self.assertEqual(WaitlistEntry.objects.filter(tenant=self.tenant,status='waiting').count(),1)

    def test_rejects_past_day(self):
        payload={**self.payload,'date':(timezone.localdate()-timedelta(days=1)).isoformat()}
        self.assertEqual(self.client.post(self.url,payload,content_type='application/json').status_code,400)
