from datetime import timedelta
from decimal import Decimal
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from tenants.models import Tenant, TenantOnboarding, Unit
from scheduling.models import Professional
from billing.models import Module, TenantModule, Plan, Subscription
from billing.module_services import request_module
from accounts.models import User
from core.public_identity import verification_status, short_url, REGISTRATION_FLAGS


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_BASE_URL='https://applanner.com.br',
    STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
              'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}},
    CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache'}})
class PublicIdentityTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name='Barbearia',slug='barbearia',public_enabled=True,status='active')
        Tenant.objects.filter(pk=self.tenant.pk).update(created_at=timezone.now()-timedelta(days=8))
        self.tenant.refresh_from_db()
        self.unit=Unit.objects.create(tenant=self.tenant,name='Centro',active=True)
        self.staff=Professional.objects.create(tenant=self.tenant,unit=self.unit,name='João',public_slug='joao')
        self.module=Module.objects.get(slug='verified-business')
        self.module.addon_monthly_price=Decimal('9.90');self.module.save()
        self.row=TenantOnboarding.objects.create(tenant=self.tenant,completed_at=timezone.now(),
            **{flag:True for flag in REGISTRATION_FLAGS})
        self.release=TenantModule.objects.create(tenant=self.tenant,module=self.module,enabled=True)

    def test_badge_requires_seven_days_complete_registration_and_enabled_module(self):
        self.assertTrue(verification_status(self.tenant)['verified'])
        self.tenant.created_at=timezone.now()-timedelta(days=7)+timedelta(seconds=1)
        self.assertFalse(verification_status(self.tenant)['verified'])
        self.tenant.created_at=timezone.now()-timedelta(days=7,seconds=1)
        self.assertTrue(verification_status(self.tenant)['verified'])
        for flag in REGISTRATION_FLAGS:
            setattr(self.row,flag,False);self.row.save()
            self.assertFalse(verification_status(self.tenant)['verified'],flag)
            setattr(self.row,flag,True);self.row.save()
        self.release.enabled=False;self.release.save()
        self.assertFalse(verification_status(self.tenant)['verified'])
        self.release.enabled=True;self.release.save()
        self.tenant.status='suspended'
        self.assertFalse(verification_status(self.tenant)['verified'])

    def test_short_link_tracks_slug_changes_and_keeps_unit(self):
        path=reverse('tenant-short-link',args=[self.tenant.public_short_code])
        self.assertRedirects(self.client.get(path,{'unit':self.unit.pk}),f'/p/barbearia/?unit={self.unit.pk}',fetch_redirect_response=False)
        code=self.tenant.public_short_code
        self.tenant.public_slug='novo-nome';self.tenant.save()
        self.assertEqual(self.tenant.public_short_code,code)
        self.assertRedirects(self.client.get(path),'/p/novo-nome/',fetch_redirect_response=False)
        self.assertEqual(short_url(self.tenant,self.unit),f'https://applanner.com.br{path}?unit={self.unit.pk}')
        other=Tenant.objects.create(name='Outra',slug='outra')
        other_unit=Unit.objects.create(tenant=other,name='Outra unidade')
        self.assertEqual(self.client.get(path,{'unit':other_unit.pk}).status_code,404)
        self.assertEqual(self.client.get(path,{'unit':'abc'}).status_code,404)

    def test_professional_short_link_keeps_professional_and_its_unit(self):
        path=reverse('professional-short-link',args=[self.staff.public_short_code])
        self.assertRedirects(self.client.get(path),f'/p/barbearia/profissional/joao/?unit={self.unit.pk}',fetch_redirect_response=False)
        self.staff.public_slug='joao-novo';self.staff.save()
        self.assertRedirects(self.client.get(path),f'/p/barbearia/profissional/joao-novo/?unit={self.unit.pk}',fetch_redirect_response=False)
        self.staff.active=False;self.staff.save()
        self.assertEqual(self.client.get(path).status_code,404)

    def test_hidden_or_archived_company_does_not_redirect(self):
        path=reverse('tenant-short-link',args=[self.tenant.public_short_code])
        self.tenant.public_enabled=False;self.tenant.save()
        self.assertEqual(self.client.get(path).status_code,404)
        self.tenant.public_enabled=True;self.tenant.archived_at=timezone.now();self.tenant.save()
        self.assertEqual(self.client.get(path).status_code,404)

    def test_directory_uses_unit_logo_and_only_displays_eligible_badge(self):
        self.unit.logo='unit/logo/example.png';self.unit.save()
        response=self.client.get(reverse('public-directory'))
        self.assertContains(response,f'/imagens/empresa/{self.tenant.pk}/logo/?unit={self.unit.pk}')
        self.assertContains(response,'Empresa verificada')
        data=self.client.get(reverse('public-directory-api')).json()['results'][0]
        self.assertTrue(data['verified']);self.assertIn(f'unit={self.unit.pk}',data['logo_url'])
        self.release.enabled=False;self.release.save()
        self.assertNotContains(self.client.get(reverse('public-directory')),'Empresa verificada')

    def test_ineligible_request_rejected_on_server(self):
        self.release.enabled=False;self.release.save()
        self.row.schedule_done=False;self.row.save()
        owner=User.objects.create_user(email='owner-short@example.com',password='strong-local-test',tenant=self.tenant,role='owner')
        with self.assertRaisesMessage(ValidationError,'Concluir todas as etapas'):
            request_module(tenant=self.tenant,module=self.module,user=owner)

    def test_public_cover_contains_badge_and_unchanged_booking(self):
        self.tenant.logo='tenant/logo/example.png';self.tenant.save()
        response=self.client.get(reverse('tenant-public',args=[self.tenant.slug]))
        self.assertContains(response,'public-business-identity')
        self.assertContains(response,'Empresa verificada')
        self.assertContains(response,'public-booking')

    @override_settings(SUBSCRIPTION_ACCESS_ENFORCED=True)
    def test_short_links_do_not_bypass_subscription_lock(self):
        plan=Plan.objects.create(name='Inicial',slug='short-inicial',monthly_price=Decimal('59.90'))
        Subscription.objects.create(tenant=self.tenant,plan=plan,status='past_due',started_at=timezone.now())
        for name,code in [('tenant-short-link',self.tenant.public_short_code),('professional-short-link',self.staff.public_short_code)]:
            self.assertEqual(self.client.get(reverse(name,args=[code])).status_code,403)

    def test_catalog_seed_preserves_master_defined_badge_price(self):
        from django.core.management import call_command
        call_command('seed_modules',verbosity=0)
        self.module.refresh_from_db()
        self.assertEqual(self.module.addon_monthly_price,Decimal('9.90'))
