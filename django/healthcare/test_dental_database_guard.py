from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.core.exceptions import ValidationError
from django.db import connection,connections,transaction,IntegrityError
from django.test import TestCase,TransactionTestCase
from scheduling.models import Professional
from tenants.models import Tenant


@skipUnless(connection.vendor=="postgresql","PostgreSQL trigger coverage")
class DentalDatabaseGuardTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Odonto SQL",slug="dental-sql",category="odontologia")
        Professional.objects.create(tenant=self.tenant,name="Incluído")

    def test_base_manager_bulk_insert_cannot_bypass_database_limit(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            Professional._base_manager.bulk_create([Professional(tenant=self.tenant,name="Sem vaga")])
        self.assertEqual(Professional.objects.filter(tenant=self.tenant,active=True).count(),1)

    def test_base_manager_update_cannot_bypass_database_limit(self):
        inactive=Professional.objects.create(tenant=self.tenant,name="Inativo",active=False)
        with self.assertRaises(IntegrityError),transaction.atomic():
            Professional._base_manager.filter(pk=inactive.pk).update(active=True)
        inactive.refresh_from_db()
        self.assertFalse(inactive.active)


@skipUnless(connection.vendor=="postgresql","PostgreSQL row lock coverage")
class DentalCapacityConcurrencyTests(TransactionTestCase):
    def test_only_one_first_dentist_can_be_created_concurrently(self):
        tenant=Tenant.objects.create(name="Odonto concorrente",slug="dental-race",category="odontologia")
        barrier=Barrier(2)
        def add(index):
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '30s'")
                clinic=Tenant.objects.get(pk=tenant.pk)
                barrier.wait(timeout=10)
                Professional.objects.create(tenant=clinic,name=f"Dentista {index}")
                return "created"
            except (ValidationError,IntegrityError):
                return "denied"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(add,[1,2]))
        self.assertCountEqual(outcomes,["created","denied"])
        self.assertEqual(Professional.objects.filter(tenant=tenant,active=True).count(),1)
