from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from .address_lookup import PostalCodeNotFound, coordinates, geocode_address, lookup_postal_code
from .models import Tenant, Unit
from .tasks import geocode_unit_from_postal_code


class AddressLookupTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("tenants.address_lookup.requests.get")
    def test_cached_cep_address_and_coordinates(self,get):
        get.return_value=Mock(json=lambda:{"street":"Rua A","neighborhood":"Centro","city":"Recife","state":"PE",
            "location":{"coordinates":{"latitude":"-8.05","longitude":"-34.9"}}})
        data=lookup_postal_code("50000-000")
        self.assertEqual(data["address"],"Rua A")
        self.assertEqual(data["latitude"],"-8.0500000")
        self.assertEqual(lookup_postal_code("50000000"),data)
        self.assertEqual(get.call_count,1)

    @patch("tenants.address_lookup.requests.get")
    def test_fallback_and_invalid_cep(self,get):
        get.side_effect=[requests.Timeout(),Mock(json=lambda:{"logradouro":"Rua B","bairro":"Centro","localidade":"Recife","uf":"PE"})]
        self.assertEqual(lookup_postal_code("50000000")["address"],"Rua B")
        get.reset_mock()
        with self.assertRaises(ValueError):lookup_postal_code("abc50000000")
        get.assert_not_called()

    @patch("tenants.address_lookup.requests.get")
    def test_unknown_cep(self,get):
        get.side_effect=[requests.HTTPError(),Mock(json=lambda:{"erro":True})]
        with self.assertRaises(PostalCodeNotFound):lookup_postal_code("99999999")

    def test_invalid_coordinates_are_discarded(self):
        for lat,lon in [("NaN","-34"),("Infinity","0"),("-91","0"),("0","181"),(None,None)]:
            self.assertIsNone(coordinates(lat,lon))

    @patch("tenants.address_lookup.requests.get")
    def test_geocoder_uses_number_and_caches_the_result(self,get):
        unit=Mock(address_number="123",postal_code="50000000")
        get.return_value=Mock(json=lambda:[{"lat":"-8.05","lon":"-34.9"}])
        address={"address":"Rua A","city":"Recife","state":"PE"}
        self.assertEqual(geocode_address(unit,address),(Decimal("-8.05"),Decimal("-34.9")))
        self.assertEqual(get.call_args.kwargs["params"]["street"],"123 Rua A")
        self.assertEqual(get.call_args.kwargs["params"]["countrycodes"],"br")
        geocode_address(unit,address)
        get.assert_called_once()

    @patch("tenants.address_lookup.requests.get")
    def test_geocoder_respects_shared_rate_limit(self,get):
        cache.set("unit-geocode:rate-limit",True,1)
        with self.assertRaises(requests.RequestException):
            geocode_address(Mock(address_number="123",postal_code="50000000"),{"address":"Rua A","city":"Recife"})
        get.assert_not_called()

    @patch("core.postal_code.lookup_postal_code")
    def test_endpoint_requires_login_and_returns_normalized_address(self,lookup):
        url=reverse("accounts:postal-code-lookup")
        self.assertEqual(self.client.get(url,{"cep":"50000000"}).status_code,302)
        user=User.objects.create_user(email="cep@example.test",password="test-pass")
        self.client.force_login(user)
        from .models import TenantOnboarding
        tenant=Tenant.objects.create(name="Cadastro inicial",slug="cep-inicial")
        TenantOnboarding.objects.create(tenant=tenant,required=True)
        user.tenant=tenant
        user.save(update_fields=["tenant"])
        lookup.return_value={"address":"Rua A","city":"Recife","state":"PE"}
        self.assertEqual(self.client.get(url,{"cep":"50000000"}).json()["address"],"Rua A")
        lookup.side_effect=PostalCodeNotFound("CEP não encontrado.")
        self.assertEqual(self.client.get(url,{"cep":"99999999"}).status_code,404)
        lookup.side_effect=requests.Timeout()
        self.assertEqual(self.client.get(url,{"cep":"50000000"}).status_code,503)


class UnitGeocodingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant=Tenant.objects.create(name="Empresa CEP",slug="empresa-cep")
        self.unit=Unit.objects.create(tenant=self.tenant,name="Centro",postal_code="50000000",address="Rua A",
            address_number="123",city="Recife",state="PE",latitude=Decimal("-8.05"),longitude=Decimal("-34.9"))

    @patch("tenants.tasks.queue_unit_geocoding")
    def test_editing_address_clears_old_coordinates_and_queues_after_commit(self,queue):
        self.unit.address_number="456"
        with self.captureOnCommitCallbacks(execute=True):self.unit.save()
        self.unit.refresh_from_db()
        self.assertIsNone(self.unit.latitude)
        self.assertIsNone(self.unit.longitude)
        queue.assert_called_once_with(self.unit.pk)

    @patch("tenants.tasks.queue_unit_geocoding")
    def test_new_unit_is_geocoded_and_manual_coordinates_are_kept(self,queue):
        with self.captureOnCommitCallbacks(execute=True):
            other=Unit.objects.create(tenant=self.tenant,name="Nova",postal_code="50000000")
        queue.assert_called_once_with(other.pk)
        queue.reset_mock()
        self.unit.address_number="456"
        self.unit.latitude=Decimal("-8.06")
        self.unit.longitude=Decimal("-34.91")
        with self.captureOnCommitCallbacks(execute=True):self.unit.save()
        queue.assert_not_called()
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.latitude,Decimal("-8.06"))

    @patch("tenants.tasks.geocode_address")
    @patch("tenants.tasks.lookup_postal_code")
    def test_full_address_is_geocoded_and_used_by_directory(self,lookup,geocode):
        lookup.return_value={"address":"Rua A","district":"Centro","city":"Recife","state":"PE","latitude":"-8.05","longitude":"-34.9"}
        geocode.return_value=(Decimal("-8.0600000"),Decimal("-34.9100000"))
        self.assertEqual(geocode_unit_from_postal_code.run(self.unit.pk),"updated")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.latitude,Decimal("-8.06"))
        self.assertIsNotNone(self.unit.geocoded_at)
        self.tenant.public_enabled=True
        self.tenant.save(update_fields=["public_enabled"])
        response=self.client.get("/directory/",{"lat":"-8.06","lon":"-34.91"})
        self.assertEqual(response.context["cards"][0]["unit"].pk,self.unit.pk)
        self.assertLess(response.context["cards"][0]["distance_km"],0.01)
        self.assertEqual(geocode.call_args.args[0].address_number,"123")

    @patch("tenants.tasks.geocode_address")
    @patch("tenants.tasks.lookup_postal_code")
    def test_old_worker_cannot_overwrite_a_new_address(self,lookup,geocode):
        lookup.return_value={"address":"Rua A","city":"Recife","state":"PE","latitude":"-8.05","longitude":"-34.9"}
        def concurrent_edit(*args):
            Unit.objects.filter(pk=self.unit.pk).update(address="Rua Nova",latitude=None,longitude=None)
            return Decimal("-8.06"),Decimal("-34.91")
        geocode.side_effect=concurrent_edit
        self.assertEqual(geocode_unit_from_postal_code.run(self.unit.pk),"stale")
        self.unit.refresh_from_db()
        self.assertIsNone(self.unit.latitude)
        self.assertEqual(self.unit.address,"Rua Nova")
