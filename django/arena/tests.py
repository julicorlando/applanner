from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase

from tenants.models import Tenant
from .models import Court, CourtHours, PriceRule, Reservation
from .services import ArenaReservationService


class ArenaReservationServiceTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Arena Demo",slug="arena-demo",status=Tenant.Status.ACTIVE)
        self.court=Court.objects.create(
            tenant=self.tenant,name="Quadra 1",slug="quadra-1",minimum_minutes=60,maximum_minutes=120
        )
        CourtHours.objects.create(
            tenant=self.tenant,court=self.court,weekday=1,start_time=time(8,0),end_time=time(22,0)
        )
        PriceRule.objects.create(
            tenant=self.tenant,court=self.court,weekday=1,
            start_time=time(8,0),end_time=time(22,0),
            price_per_hour=Decimal("100.00"),priority=10,
        )
        self.service=ArenaReservationService()
        self.tz=ZoneInfo("America/Recife")

    def test_quote_and_reservation_conflict(self):
        start=datetime(2030,1,7,10,0,tzinfo=self.tz)
        end=datetime(2030,1,7,11,0,tzinfo=self.tz)

        quote=self.service.quote(self.tenant,self.court,start,end)
        self.assertEqual(quote["total"],Decimal("100.00"))

        reservation,token=self.service.create_reservation(
            tenant=self.tenant,court=self.court,start=start,end=end,
            customer_name="Cliente",customer_phone="81999999999",
            payment_method="onsite",public_rules=False,
        )
        self.assertTrue(token)
        self.assertEqual(reservation.status,Reservation.Status.CONFIRMED)

        with self.assertRaises(ValidationError):
            self.service.create_reservation(
                tenant=self.tenant,court=self.court,start=start,end=end,
                customer_name="Outro",customer_phone="81888888888",
                payment_method="onsite",public_rules=False,
            )
