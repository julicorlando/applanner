from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from finance.models import Product, ProductReservation
from tenants.models import Tenant
from .models import (
    Appointment, Customer, Professional, ProfessionalAvailability, Service,
)


class PublicProductReservationTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(
            name="Barbearia Reserva",slug="barbearia-reserva",public_slug="barbearia-reserva",
            public_enabled=True,public_booking_enabled=True,status=Tenant.Status.ACTIVE,
            category="barbearia",
        )
        self.service=Service.objects.create(
            tenant=self.tenant,name="Corte",duration_minutes=30,price=Decimal("40.00"),
        )
        self.professional=Professional.objects.create(
            tenant=self.tenant,name="João",public_slug="joao",
        )
        self.professional.services.add(self.service)
        self.day=timezone.localdate()+timedelta(days=1)
        ProfessionalAvailability.objects.create(
            tenant=self.tenant,professional=self.professional,
            weekday=self.day.isoweekday(),start_time=time(8,0),end_time=time(18,0),
        )
        self.product=Product.objects.create(
            tenant=self.tenant,name="Pomada",sale_price=Decimal("35.00"),
            cost_price=Decimal("10.00"),stock=Decimal("2.000"),active=True,
        )

    def _slot(self):
        payload=self.client.get(
            f"/api/public/{self.tenant.public_slug}/availability/",
            {"service_id":self.service.pk,"date":self.day.isoformat()},
        ).json()
        self.assertTrue(payload["slots"])
        return payload["slots"][0]["value"]

    def _book(self, *, phone, starts_at=None):
        return self.client.post(
            f"/api/public/{self.tenant.public_slug}/book/",
            {
                "service_id":self.service.pk,
                "professional_id":self.professional.pk,
                "starts_at":starts_at or self._slot(),
                "name":"Cliente Reserva",
                "phone":phone,
                "payment_choice":"on_site",
                "product_ids":[self.product.pk],
            },
            content_type="application/json",
        )

    def test_public_cards_connect_service_professional_and_product_to_booking(self):
        response=self.client.get(f"/p/{self.tenant.public_slug}/")

        self.assertEqual(response.status_code,200)
        self.assertContains(response,f'data-select-service="{self.service.pk}"')
        self.assertContains(
            response,
            f'/p/{self.tenant.public_slug}/profissional/{self.professional.public_slug}/',
        )
        self.assertContains(response,f'data-reserve-product="{self.product.pk}"')
        self.assertContains(response,'id="booking-product-selection"')

    def test_booking_creates_product_reservation_and_returns_it(self):
        response=self._book(phone="81999990001")

        self.assertEqual(response.status_code,201,response.content)
        data=response.json()
        appointment=Appointment.objects.get(pk=data["id"])
        reservation=ProductReservation.objects.get(appointment=appointment,product=self.product)

        self.assertEqual(reservation.quantity,Decimal("1.000"))
        self.assertEqual(reservation.unit_price_snapshot,self.product.sale_price)
        self.assertEqual(data["reserved_products"][0]["name"],self.product.name)

        detail=self.client.get(data["manage_url"])
        self.assertEqual(detail.status_code,200)
        self.assertContains(detail,"Produtos reservados")
        self.assertContains(detail,self.product.name)

    def test_active_reservation_prevents_overselling_public_stock(self):
        self.product.stock=Decimal("1.000")
        self.product.save(update_fields=["stock","updated_at"])

        first=self._book(phone="81999990002")
        self.assertEqual(first.status_code,201,first.content)

        availability=self.client.get(
            f"/api/public/{self.tenant.public_slug}/availability/",
            {"service_id":self.service.pk,"professional_id":self.professional.pk,
             "date":self.day.isoformat()},
        ).json()
        self.assertTrue(availability["slots"])
        second=self._book(phone="81999990003",starts_at=availability["slots"][0]["value"])

        self.assertEqual(second.status_code,409)
        self.assertIn("não possui estoque disponível",second.json()["detail"])

    def test_cancelled_appointment_releases_virtual_product_stock(self):
        first=self._book(phone="81999990004")
        self.assertEqual(first.status_code,201,first.content)
        appointment=Appointment.objects.get(pk=first.json()["id"])
        appointment.status=Appointment.Status.CANCELLED
        appointment.save(update_fields=["status","updated_at"])

        self.product.stock=Decimal("1.000")
        self.product.save(update_fields=["stock","updated_at"])
        availability=self.client.get(
            f"/api/public/{self.tenant.public_slug}/availability/",
            {"service_id":self.service.pk,"professional_id":self.professional.pk,
             "date":self.day.isoformat()},
        ).json()
        self.assertTrue(availability["slots"])

        second=self._book(phone="81999990005",starts_at=availability["slots"][0]["value"])
        self.assertEqual(second.status_code,201,second.content)
