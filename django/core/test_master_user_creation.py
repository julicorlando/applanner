from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from tenants.models import Tenant


class MasterUserCreationTests(TestCase):
    def setUp(self):
        self.master=User.objects.create_superuser(email="master@example.test",password="SenhaMaster123!")
        self.tenant=Tenant.objects.create(name="Arena Beach",slug="arena-beach",category="Arena")
        self.client.force_login(self.master)
        self.url=reverse("master-resource-create",args=["usuarios"])

    def test_creates_owner_with_hashed_temporary_password(self):
        response=self.client.post(self.url,{"tenant":self.tenant.pk,"email":"owner@example.test",
            "role":"owner","is_active":"on","new_password":"SenhaInicialForte123!",
            "confirm_password":"SenhaInicialForte123!"})
        self.assertEqual(response.status_code,302)
        owner=User.objects.get(email="owner@example.test")
        self.assertEqual(owner.tenant,self.tenant)
        self.assertTrue(owner.check_password("SenhaInicialForte123!"))
        self.assertTrue(owner.must_change_password)

    def test_missing_or_mismatched_password_shows_field_error(self):
        data={"tenant":self.tenant.pk,"email":"owner@example.test","role":"owner","is_active":"on"}
        self.assertContains(self.client.post(self.url,data),"Senha inicial")
        self.assertFalse(User.objects.filter(email="owner@example.test").exists())
        data.update(new_password="SenhaInicialForte123!",confirm_password="outra")
        self.assertContains(self.client.post(self.url,data),"As senhas não conferem")
        self.assertFalse(User.objects.filter(email="owner@example.test").exists())

    def test_edit_without_password_preserves_hash(self):
        owner=User.objects.create_user(email="owner@example.test",password="SenhaExistente123!",
            tenant=self.tenant,role="owner")
        old_hash=owner.password
        url=reverse("master-resource-edit",args=["usuarios",owner.pk])
        response=self.client.post(url,{"tenant":self.tenant.pk,"email":owner.email,
            "role":"owner","is_active":"on"})
        self.assertEqual(response.status_code,302)
        owner.refresh_from_db()
        self.assertEqual(owner.password,old_hash)
