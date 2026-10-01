from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Module, Plan, Subscription, TenantModule
from billing.segment_access import segment_enabled
from arena.models import Court, CourtHours, PriceRule, Reservation, SportsSettings
from scheduling.models import TenantScheduleSettings
from tenants.models import Tenant


class ArenaPublicBookingTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Arena Centro",slug="arena-centro",category="arena",
            public_enabled=True,public_booking_enabled=True,status=Tenant.Status.ACTIVE)
        self.court=Court.objects.create(tenant=self.tenant,name="Quadra Azul",slug="azul",
            minimum_minutes=60,maximum_minutes=120)
        today=timezone.now().astimezone(ZoneInfo(self.tenant.timezone)).date()
        self.day=today+timedelta(days=(7-today.weekday()) % 7+7)
        CourtHours.objects.create(tenant=self.tenant,court=self.court,weekday=self.day.isoweekday(),
            start_time=time(8),end_time=time(12))
        PriceRule.objects.create(tenant=self.tenant,court=self.court,weekday=self.day.isoweekday(),
            start_time=time(8),end_time=time(12),price_per_hour=Decimal("80.00"))
        self.slots=reverse("public-arena-slots",args=[self.tenant.slug])
        self.book=reverse("public-arena-book",args=[self.tenant.slug])

    def test_public_page_uses_courts_without_professionals_or_services(self):
        page=self.client.get(reverse("tenant-public",args=[self.tenant.slug]))
        self.assertContains(page,"Quadra Azul")
        self.assertContains(page,"Escolha quadra, data e horário")
        self.assertNotContains(page,"booking-professional")
        self.assertNotContains(page,"booking-service")
        self.assertNotContains(page,"Sinal por Pix")

    def test_unlicensed_arena_never_falls_back_to_professional_booking(self):
        plan=Plan.objects.create(name="Básico",slug="basico-arena",features={"segments":["barbearia"]})
        Subscription.objects.create(tenant=self.tenant,plan=plan,status=Subscription.Status.ACTIVE,
            started_at=timezone.now())
        page=self.client.get(reverse("tenant-public",args=[self.tenant.slug]))
        self.assertContains(page,"reservas online desta arena ainda não estão disponíveis")
        self.assertNotContains(page,"booking-professional")
        self.assertNotContains(page,'id="arena-booking"')
        self.assertEqual(self.client.get(self.slots,{"court_id":self.court.pk,"date":self.day}).status_code,404)

        module=Module.objects.create(slug="sports_courts",name="Arena")
        TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        self.assertTrue(segment_enabled(self.tenant,"arena"))
        page=self.client.get(reverse("tenant-public",args=[self.tenant.slug]))
        self.assertContains(page,'id="arena-booking"')
        self.assertEqual(self.client.get(self.slots,{"court_id":self.court.pk,"date":self.day}).status_code,200)

    def test_slots_booking_conflict_and_confirmation_page(self):
        response=self.client.get(self.slots,{"court_id":self.court.pk,"date":self.day.isoformat(),"duration":60})
        self.assertEqual(response.status_code,200)
        slots=response.json()["slots"]
        self.assertTrue(slots)
        start=next(row for row in slots if row["value"].startswith(f"{self.day}T10:00"))
        data={"court_id":self.court.pk,"starts_at":start["value"],"duration":60,
              "name":"Cliente Teste","phone":"81999999999","payment":"onsite"}
        response=self.client.post(self.book,data,content_type="application/json")
        self.assertEqual(response.status_code,201)
        manage_url=response.json()["manage_url"]
        self.assertEqual(response.json()["court"],self.court.name)
        self.assertEqual(response.json()["starts_at"],start["value"])
        self.assertIn("total",response.json())
        self.assertEqual(response.json()["timezone"],"America/Recife")
        reservation=Reservation.objects.get(tenant=self.tenant)
        self.assertIsNotNone(reservation.customer_id)
        self.assertEqual(reservation.customer.phone,"5581999999999")
        self.assertEqual(reservation.status,Reservation.Status.CONFIRMED)
        self.assertEqual(reservation.deposit_amount,Decimal("0"))
        self.assertContains(self.client.get(manage_url),"Pagamento na unidade")
        self.assertEqual(self.client.post(self.book,data,content_type="application/json").status_code,409)
        later=self.client.get(self.slots,{"court_id":self.court.pk,"date":self.day.isoformat(),"duration":60})
        self.assertNotIn(start["value"],[row["value"] for row in later.json()["slots"]])
        self.client.post(manage_url,{"action":"cancel"})
        reservation.refresh_from_db()
        self.assertEqual(reservation.status,Reservation.Status.CANCELLED)
        freed=self.client.get(self.slots,{"court_id":self.court.pk,"date":self.day.isoformat(),"duration":60})
        self.assertIn(start["value"],[row["value"] for row in freed.json()["slots"]])

    def test_deposit_is_optional_and_requires_connected_payment(self):
        SportsSettings.objects.create(tenant=self.tenant,require_deposit=True,
            deposit_type=SportsSettings.DepositType.FIXED,deposit_value=Decimal("20.00"))
        TenantScheduleSettings.objects.create(tenant=self.tenant,online_booking_payments_enabled=True)
        page=self.client.get(reverse("tenant-public",args=[self.tenant.slug]))
        self.assertNotContains(page,"Sinal por Pix")
        start=datetime.combine(self.day,time(10),ZoneInfo(self.tenant.timezone)).isoformat()
        data={"court_id":self.court.pk,"starts_at":start,"duration":60,
              "name":"Cliente Teste","phone":"81999999999","email":"cliente@example.test","payment":"pix"}
        self.assertEqual(self.client.post(self.book,data,content_type="application/json").status_code,400)
        data["payment"]="onsite"
        self.assertEqual(self.client.post(self.book,data,content_type="application/json").status_code,201)
        self.assertEqual(Reservation.objects.get().deposit_amount,Decimal("0"))

    @patch("arena.public.create_tenant_pix")
    @patch("arena.public.has_connected_tenant_gateway",return_value=True)
    def test_opted_in_pix_creates_pending_reservation(self,connected,pix):
        SportsSettings.objects.create(tenant=self.tenant,require_deposit=True,
            deposit_type=SportsSettings.DepositType.FIXED,deposit_value=Decimal("20.00"))
        TenantScheduleSettings.objects.create(tenant=self.tenant,online_booking_payments_enabled=True)
        page=self.client.get(reverse("tenant-public",args=[self.tenant.slug]))
        self.assertContains(page,"Sinal por Pix")
        start=datetime.combine(self.day,time(10),ZoneInfo(self.tenant.timezone)).isoformat()
        response=self.client.post(self.book,{"court_id":self.court.pk,"starts_at":start,
            "name":"Cliente Teste","phone":"81999999999","email":"cliente@example.test","payment":"pix"},content_type="application/json")
        self.assertEqual(response.status_code,201)
        reservation=Reservation.objects.get()
        self.assertEqual(reservation.status,Reservation.Status.PENDING_PAYMENT)
        self.assertEqual(reservation.deposit_amount,Decimal("20.00"))
        pix.assert_called_once()

    def test_agenda_list_includes_automatic_update(self):
        user=User.objects.create_superuser(email="master-arena@example.test",password="SenhaForte123!")
        self.client.force_login(user)
        session=self.client.session
        session["portal_tenant_id"]=self.tenant.pk
        session.save()
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["agenda","agendamentos"])).status_code,403)
        home=self.client.get(reverse("portal-home"))
        self.assertContains(home,"Nova reserva")
        self.assertNotContains(home,"Novo agendamento")
        self.assertNotContains(home,"Profissionais")
        arena_list=self.client.get(reverse("portal-resource-list",args=["arena","reservas"]))
        self.assertContains(arena_list,'data-live-agenda="agendamentos"')
        owner=User.objects.create_user(email="owner-arena@example.test",password="SenhaForte123!",
            tenant=self.tenant,role="owner")
        self.client.force_login(owner)
        dashboard=self.client.get(reverse("home"))
        self.assertContains(dashboard,"Próximas reservas")
        self.assertContains(dashboard,'data-live-agenda="painel-hoje"')
        self.assertContains(dashboard,"/static/js/live-agenda")
        other=Tenant.objects.create(name="Salão",slug="salao",category="barbearia",status=Tenant.Status.ACTIVE)
        self.client.force_login(user)
        session=self.client.session
        session["portal_tenant_id"]=other.pk
        session.save()
        page=self.client.get(reverse("portal-resource-list",args=["agenda","agendamentos"]))
        self.assertContains(page,'data-live-agenda="agendamentos"')
        self.assertContains(page,"/static/js/live-agenda")
