from django.core.exceptions import ValidationError
from django.test import TestCase
from tenants.models import Tenant
from .customer_identity import resolve_customer
from .models import Customer


class CustomerIdentityTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Identidade",slug="identity-qa")

    def test_normalized_phone_reuses_identity_and_preserves_history(self):
        original=Customer.objects.create(tenant=self.tenant,name="Nome cadastrado",phone="(81) 98932-8045",email="original@example.test")
        found,reused=resolve_customer(self.tenant,"Outro nome","+55 (81) 98932-8045","")
        self.assertTrue(reused)
        self.assertEqual(found.pk,original.pk)
        original.refresh_from_db()
        self.assertEqual(original.name,"Nome cadastrado")
        self.assertEqual(original.email,"original@example.test")
        self.assertEqual(Customer.objects.count(),1)

    def test_email_is_optional_and_phone_is_required(self):
        created,reused=resolve_customer(self.tenant,"Maria","81989328045")
        self.assertFalse(reused)
        self.assertEqual(created.phone,"5581989328045")
        self.assertEqual(created.email,"")
        with self.assertRaises(ValidationError):
            resolve_customer(self.tenant,"Maria","","maria@example.test")
        with self.assertRaises(ValidationError):
            resolve_customer(self.tenant,"Maria","123")

    def test_email_reuses_customer_without_public_overwrite(self):
        original=Customer.objects.create(tenant=self.tenant,name="Maria",phone="5581999999999",email="Maria@Example.test")
        found,reused=resolve_customer(self.tenant,"Outro nome","81988888888","maria@example.test")
        self.assertTrue(reused)
        self.assertEqual(found.pk,original.pk)
        self.assertEqual(found.phone,original.phone)

    def test_conflicting_identifiers_do_not_merge_customers(self):
        Customer.objects.create(tenant=self.tenant,name="Maria",phone="5581999999999")
        Customer.objects.create(tenant=self.tenant,name="Ana",phone="5581888888888",email="ana@example.test")
        with self.assertRaises(ValidationError):
            resolve_customer(self.tenant,"Maria","81999999999","ana@example.test")
        self.assertEqual(Customer.objects.count(),2)

    def test_legacy_duplicates_require_manager_review_and_tenants_are_isolated(self):
        other=Tenant.objects.create(name="Outra",slug="other-identity")
        Customer.objects.create(tenant=other,name="Outro cliente",phone="81989328045")
        created,reused=resolve_customer(self.tenant,"Maria","81989328045")
        self.assertFalse(reused)
        Customer.objects.create(tenant=self.tenant,name="Duplicado legado",phone="(81) 98932-8045")
        with self.assertRaises(ValidationError):
            resolve_customer(self.tenant,"Maria",created.phone)

    def test_manager_cannot_create_duplicate_contact_and_must_supply_phone(self):
        resolve_customer(self.tenant,"Maria","81989328045")
        duplicate=Customer(tenant=self.tenant,name="Outra pessoa",phone="(81) 98932-8045")
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(ValidationError):
            Customer(tenant=self.tenant,name="Sem telefone",email="email@example.test").full_clean()
