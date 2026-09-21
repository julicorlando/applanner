from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase

from billing.models import Module, TenantModule
from finance.models import FinancialTransaction
from scheduling.models import Customer
from tenants.models import Tenant
from .membership import generate_membership
from .models import Court, CourtHours, Membership, MembershipReservation, PriceRule, Reservation
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


class ArenaMembershipTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.tenant=Tenant.objects.create(name="Arena Membership",slug="arena-membership",status=Tenant.Status.ACTIVE)
        self.customer=Customer.objects.create(
            tenant=self.tenant,name="Mensalista",phone="81999999999",email="mensalista@example.com"
        )
        self.court=Court.objects.create(
            tenant=self.tenant,name="Quadra Mensalista",slug="quadra-mensalista",
            minimum_minutes=60,maximum_minutes=120
        )
        today=timezone.localdate()
        CourtHours.objects.create(
            tenant=self.tenant,court=self.court,weekday=today.isoweekday(),
            start_time=time(8,0),end_time=time(22,0)
        )
        PriceRule.objects.create(
            tenant=self.tenant,court=self.court,weekday=today.isoweekday(),
            start_time=time(8,0),end_time=time(22,0),
            price_per_hour=Decimal("100.00"),priority=10
        )
        finance=Module.objects.create(slug="finance-test",name="Finance Test")
        TenantModule.objects.create(tenant=self.tenant,module=finance,enabled=True)

    def test_membership_generates_reservation_and_advances_cursor(self):
        from django.utils import timezone
        today=timezone.localdate()
        membership=Membership.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            court=self.court,
            name="Horário fixo",
            frequency=Membership.Frequency.WEEKLY,
            weekday=today.isoweekday(),
            start_time=time(10,0),
            duration_minutes=60,
            monthly_amount=Decimal("200.00"),
            start_date=today,
            generate_days_ahead=7,
            status=Membership.Status.ACTIVE,
        )

        result=generate_membership(membership)
        membership.refresh_from_db()

        self.assertGreaterEqual(result["generated"],1)
        self.assertTrue(MembershipReservation.objects.filter(membership=membership).exists())
        self.assertIsNotNone(membership.next_generation_date)
