from datetime import datetime,time,timedelta
from zoneinfo import ZoneInfo
from django.core.exceptions import ValidationError
from django.test import TestCase,Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from billing.models import Plan,Subscription,Module,PlanModule
from arena.models import Court,CourtHours,PriceRule,Reservation
from tenants.models import Tenant


class ArenaJourneyAndLimitsTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Arena QA",slug="arena-quota",category="arena",public_enabled=True,status="active")
        plan=Plan.objects.create(name="Arena QA",slug="arena-quota-plan",features={"segments":["arena"],"courts":1,"reservations":1})
        Subscription.objects.create(tenant=self.tenant,plan=plan,status="active",started_at=timezone.now())
        module=Module.objects.create(slug="sports_courts",name="Arena")
        PlanModule.objects.create(plan=plan,module=module,enabled=True)
        self.court=Court.objects.create(tenant=self.tenant,name="Quadra QA",slug="quadra")
        self.day=timezone.localdate()+timedelta(days=2)
        CourtHours.objects.create(tenant=self.tenant,court=self.court,weekday=self.day.isoweekday(),start_time=time(8),end_time=time(18))
        PriceRule.objects.create(tenant=self.tenant,court=self.court,price_per_hour=80)
        self.slots=reverse("public-arena-slots",args=[self.tenant.slug])
        self.book=reverse("public-arena-book",args=[self.tenant.slug])
        self.owner=User.objects.create_user(email="arena-owner@example.test",tenant=self.tenant,role="owner")

    def reserve(self,hour=10):
        start=datetime.combine(self.day,time(hour),tzinfo=ZoneInfo(self.tenant.timezone))
        return self.client.post(self.book,{"court_id":self.court.pk,"starts_at":start.isoformat(),"duration":60,
            "name":"Cliente Arena QA","phone":"81900000000","payment":"onsite"},content_type="application/json")

    def test_anonymous_booking_manager_search_cancel_and_monthly_limit(self):
        self.assertEqual(self.client.get(reverse("portal-home")).status_code,302)
        self.assertContains(self.client.get(reverse("tenant-public",args=[self.tenant.slug])),self.court.name)
        response=self.reserve()
        self.assertEqual(response.status_code,201,response.content)
        manage=response.json()["manage_url"]
        row=Reservation.objects.get()
        manager=Client()
        manager.force_login(self.owner)
        url=reverse("portal-resource-list",args=["arena","reservas"])
        response=manager.get(url,{"q":self.court.name,"period":"upcoming"})
        self.assertEqual([r["obj"].pk for r in response.context["rows"]],[row.pk])
        rejected=self.reserve(12)
        self.assertEqual(rejected.status_code,409,rejected.content)
        self.assertIn("Limite de 1 reserva",str(rejected.json()))
        self.assertEqual(Reservation.objects.count(),1)
        self.client.post(manage,{"action":"cancel"})
        row.refresh_from_db()
        self.assertEqual(row.status,"cancelled")
        self.assertContains(self.client.get(manage),"reserva está cancelada")
        self.assertEqual(self.reserve(12).status_code,201)

    def test_active_court_limit_preserves_existing_and_master_release(self):
        self.court.full_clean()
        extra=Court(tenant=self.tenant,name="Segunda quadra",slug="segunda")
        with self.assertRaises(ValidationError): extra.full_clean()
        extra.active=False
        extra.full_clean()
        self.tenant.metadata={"courts_limit_override":0,"reservations_limit_override":0}
        self.tenant.save()
        extra.active=True
        extra.full_clean()
        extra.save()
        self.assertEqual(self.reserve().status_code,201)
        self.assertEqual(self.reserve(12).status_code,201)

    def test_month_uses_tenant_timezone_and_keeps_tenants_isolated(self):
        from billing.entitlements import validate_reservation_capacity
        self.assertEqual(self.reserve().status_code,201)
        start=datetime.combine(self.day.replace(day=1),time(0),tzinfo=ZoneInfo(self.tenant.timezone))
        next_month=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
        validate_reservation_capacity(self.tenant,next_month)
        other=Tenant.objects.create(name="Outra Arena",slug="outra-arena")
        validate_reservation_capacity(other,start)

    def test_started_reservation_hides_cancel_and_explains_reason(self):
        response=self.reserve()
        row=Reservation.objects.get()
        row.starts_at=timezone.now()-timedelta(hours=2)
        row.ends_at=timezone.now()-timedelta(hours=1)
        row.save()
        page=self.client.get(response.json()["manage_url"])
        self.assertContains(page,"horário desta reserva já começou")
        self.assertNotContains(page,'value="cancel"')
