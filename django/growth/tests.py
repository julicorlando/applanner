from django.test import TestCase
from django.urls import reverse

from billing.models import Module
from commercial.models import Lead
from .models import AcquisitionEvent


class AttributionTests(TestCase):
    def test_custom_plan_records_utm_without_marketing_consent_for_meta(self):
        module=Module.objects.create(name="Agenda",slug="agenda-attribution")
        url=reverse("billing-custom-plan")
        self.client.get(url+"?utm_source=campanha&utm_medium=email&utm_campaign=outono")
        response=self.client.post(url,{"name":"Cliente","business_type":"Barbearia",
            "email":"lead-growth@test.local","phone":"5581999999999","modules":[module.pk],"consent":"on"})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Lead.objects.count(),1)
        event=AcquisitionEvent.objects.get()
        self.assertEqual((event.source,event.medium,event.campaign),("campanha","email","outono"))
        self.assertFalse(event.marketing_consent)
