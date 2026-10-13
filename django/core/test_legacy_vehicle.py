from contextlib import contextmanager
from datetime import timedelta

from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from auto.models import Vehicle
from core.management.commands.import_legacy_specialized import Command
from scheduling.models import Appointment,Customer,Service
from tenants.models import Tenant


class LegacyAppointmentVehicleTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Oficina",slug="oficina-etl")
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        self.service=Service.objects.create(tenant=self.tenant,name="Lavagem",duration_minutes=30)
        self.vehicle=Vehicle.objects.create(
            tenant=self.tenant,customer=self.customer,plate="ABC1234",model="Carro",
        )
        start=timezone.now()
        self.appointment=Appointment.objects.create(
            tenant=self.tenant,customer=self.customer,service=self.service,
            starts_at=start,ends_at=start+timedelta(minutes=30),
        )
        self.command=Command()
        self.command.tables={"appointments":{"vehicle_id"}}

    def _connection(self,customer_id):
        row={"id":self.appointment.pk,"tenant_id":self.tenant.pk,
             "customer_id":customer_id,"vehicle_id":self.vehicle.pk}

        class Cursor:
            def execute(self,sql):
                assert "vehicle_id IS NOT NULL" in sql
            def fetchall(self):
                return [row]

        class Connection:
            @contextmanager
            def cursor(self):
                yield Cursor()

        return Connection()

    def test_links_vehicle_after_specialized_vehicle_import(self):
        self.assertEqual(self.command._appointment_vehicles(self._connection(self.customer.pk),set()),1)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.vehicle_id,self.vehicle.pk)

    def test_refuses_cross_customer_vehicle_link(self):
        stranger=Customer.objects.create(tenant=self.tenant,name="Outro")
        with self.assertRaises(CommandError):
            self.command._appointment_vehicles(self._connection(stranger.pk),set())

    def test_portal_validation_rejects_vehicle_of_another_customer(self):
        stranger=Customer.objects.create(tenant=self.tenant,name="Outro")
        self.appointment.customer=stranger
        self.appointment.vehicle=self.vehicle
        with self.assertRaises(ValidationError):
            self.appointment.full_clean()
