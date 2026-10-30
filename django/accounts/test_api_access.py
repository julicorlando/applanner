import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory,TestCase,override_settings
from django.utils import timezone

from accounts.api_access import allowed_scopes,api_resource
from accounts.models import PersonalAPIToken,UserBlock
from scheduling.models import Appointment,Customer,Professional,Service
from tenants.models import Tenant


@override_settings(SECURE_SSL_REDIRECT=False,CACHES={"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache"}})
class PersonalAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant=Tenant.objects.create(name="Empresa A",slug="empresa-a",status="active")
        self.other=Tenant.objects.create(name="Empresa B",slug="empresa-b",status="active")
        self.user=get_user_model().objects.create_user(email="owner@example.com",password="TestPassword!123",tenant=self.tenant,role="owner")
        self.client.force_login(self.user)

    def issue(self,scopes=("agenda.read",)):
        before=PersonalAPIToken.objects.count()
        response=self.client.post("/account/documentacao-api/",{
            "name":"Integração de teste","scopes":list(scopes),"expires_in":"7",
        })
        self.assertEqual(response.status_code,200)
        self.assertEqual(PersonalAPIToken.objects.count(),before+1)
        return re.search(r"ap_[A-Za-z0-9_-]+",response.content.decode()).group()

    def get_api(self,raw,path):
        return self.client.get(path,HTTP_AUTHORIZATION=f"Bearer {raw}")

    def test_hash_only_and_tenant_isolation(self):
        mine=Customer.objects.create(tenant=self.tenant,name="Cliente A")
        Customer.objects.create(tenant=self.other,name="Cliente B")
        raw=self.issue()
        token=PersonalAPIToken.objects.get(user=self.user)
        self.assertNotIn(raw,token.secret_hash)
        self.assertEqual(token.tenant_id,self.tenant.pk)
        response=self.get_api(raw,"/api/v1/clientes/?empresa="+str(self.other.pk))
        self.assertEqual(response.status_code,200)
        self.assertEqual([row["id"] for row in response.json()["dados"]],[mine.pk])
        self.assertEqual(self.get_api(raw,f"/api/v1/clientes/{mine.pk}/").status_code,200)
        self.assertEqual(self.get_api(raw,"/api/v1/clientes/999999/").status_code,404)
        self.assertEqual(self.get_api(raw,"/api/v1/produtos/").status_code,403)
        self.assertEqual(self.client.post("/api/v1/clientes/",HTTP_AUTHORIZATION=f"Bearer {raw}").status_code,405)

    def test_revocation_and_permission_change(self):
        raw=self.issue()
        token=PersonalAPIToken.objects.get(user=self.user)
        self.user.role="finance"
        self.user.save(update_fields=["role"])
        self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,401)
        self.user.role="owner"
        self.user.save(update_fields=["role"])
        self.client.post(f"/account/documentacao-api/tokens/{token.pk}/revogar/")
        self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,401)

    def test_other_user_cannot_revoke_token(self):
        self.issue()
        pk=PersonalAPIToken.objects.get(user=self.user).pk
        other_user=get_user_model().objects.create_user(email="other@example.com",password="TestPassword!123",tenant=self.other,role="owner")
        self.client.force_login(other_user)
        self.assertEqual(self.client.post(f"/account/documentacao-api/tokens/{pk}/revogar/").status_code,404)

    def test_expiry_and_session_version(self):
        raw=self.issue()
        token=PersonalAPIToken.objects.get(user=self.user)
        token.expires_at=timezone.now()-timedelta(seconds=1)
        token.save(update_fields=["expires_at"])
        self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,401)
        token.expires_at=timezone.now()+timedelta(days=1)
        token.save(update_fields=["expires_at"])
        self.user.session_version+=1
        self.user.save(update_fields=["session_version"])
        self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,401)

    def test_rate_limit(self):
        raw=self.issue()
        now=timezone.now()
        with patch("accounts.api_access.timezone.now",return_value=now):
            for _ in range(60):
                self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,200)
            self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,429)
        with patch("accounts.api_access.timezone.now",return_value=now+timedelta(minutes=1)):
            self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,200)

    def test_rate_limit_counter_remains_consistent_across_minute_boundary(self):
        self.issue()
        token=PersonalAPIToken.objects.get(user=self.user)
        before=timezone.now().replace(second=59,microsecond=999999)
        after=before+timedelta(microseconds=1)
        cache.set(f"api:limit:{token.pk}:{before.strftime('%Y%m%d%H%M')}",60,timeout=75)
        request=RequestFactory().get("/api/v1/clientes/")
        with patch("accounts.api_access._authenticate",return_value=token), \
             patch("accounts.api_access.timezone.now",side_effect=[before,after]):
            response=api_resource(request,"clientes")
        self.assertEqual(response.status_code,429)

    def test_blocked_user_loses_token_access(self):
        raw=self.issue()
        UserBlock.objects.create(user=self.user,tenant=self.tenant,reason_code="security",blocked_at=timezone.now())
        self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,401)

    def test_professional_only_own_appointments_and_docs(self):
        person=get_user_model().objects.create_user(email="pro@example.com",password="TestPassword!123",tenant=self.tenant,role="professional")
        own_professional=Professional.objects.create(tenant=self.tenant,name="Pro",user=person)
        other_professional=Professional.objects.create(tenant=self.tenant,name="Outra")
        customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        service=Service.objects.create(tenant=self.tenant,name="Serviço",duration_minutes=30)
        start=timezone.now()+timedelta(days=1)
        mine=Appointment.objects.create(tenant=self.tenant,customer=customer,service=service,
            professional=own_professional,starts_at=start,ends_at=start+timedelta(minutes=30))
        Appointment.objects.create(tenant=self.tenant,customer=customer,service=service,
            professional=other_professional,starts_at=start,ends_at=start+timedelta(minutes=30))
        self.assertEqual(allowed_scopes(person),{"professional.read"})
        self.client.force_login(person)
        response=self.client.get("/account/documentacao-api/")
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Minha agenda e ganhos")
        self.assertNotContains(response,"/api/v1/clientes/")
        raw=self.issue(scopes=("professional.read",))
        self.assertEqual([row["id"] for row in self.get_api(raw,"/api/v1/meus-agendamentos/").json()["dados"]],[mine.pk])
        self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,403)

    def test_master_must_select_company_and_cannot_read_tenant_secrets(self):
        master=get_user_model().objects.create_superuser(email="master@example.com",password="TestPassword!123")
        self.client.force_login(master)
        raw=self.issue(scopes=("agenda.read",))
        self.assertEqual(self.get_api(raw,"/api/v1/clientes/").status_code,400)
        self.assertEqual(self.get_api(raw,f"/api/v1/clientes/?empresa={self.tenant.pk}").status_code,200)
        self.assertEqual(self.get_api(raw,"/api/v1/visao-master/").status_code,403)
