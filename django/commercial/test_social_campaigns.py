import io
import shutil
import tempfile

from PIL import Image
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from growth.models import AcquisitionEvent
from tenants.models import Tenant
from .models import CommercialProfile, Lead, SocialCampaign, SocialCampaignContact, SocialCampaignMedia


class SocialCampaignTests(TestCase):
    def setUp(self):
        cache.clear()
        self.directory=tempfile.mkdtemp()
        self.settings_override=override_settings(MEDIA_ROOT=self.directory)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree,self.directory,True)
        self.master=User.objects.create_superuser(email='social-master@example.test',password='ReviewPassword123!')
        self.sales=User.objects.create_user(email='social-sales@example.test',password='ReviewPassword123!')
        CommercialProfile.objects.create(user=self.sales)
        self.other=User.objects.create_user(email='social-other@example.test',password='ReviewPassword123!')
        CommercialProfile.objects.create(user=self.other)
        tenant=Tenant.objects.create(name='Tenant',slug='social-tenant')
        self.tenant_user=User.objects.create_user(email='social-tenant@example.test',password='ReviewPassword123!',tenant=tenant)
        CommercialProfile.objects.create(user=self.tenant_user)
        self.campaign=SocialCampaign.objects.create(owner=self.sales,name='Teste social',headline='Organize a sua agenda',caption='Conheça o ApPlanner')
        self.detail=reverse('commercial-social-detail',args=[self.campaign.pk])
        self.public=reverse('commercial-social-public',args=[self.campaign.code])
        self.data={'name':'Contato de teste','business':'Barbearia Teste','email':'interessado@example.test',
                   'phone':'81999999999','consent':'on'}

    def image(self):
        data=io.BytesIO()
        Image.new('RGB',(1080,1350),'blue').save(data,'PNG')
        return SimpleUploadedFile('campanha.png',data.getvalue(),content_type='image/png')

    def upload(self,client=None,file=None,**extra):
        return (client or self.client).post(self.detail,{'action':'upload','title':'Agenda organizada','placement':'feed',
            'rights':'on','file':file or self.image(),**extra})

    def activate(self):
        self.campaign.status=SocialCampaign.Status.ACTIVE
        self.campaign.save()

    def test_access_is_limited_to_platform_commercial_and_owned_campaigns(self):
        url=reverse('commercial-social-list')
        self.assertEqual(self.client.get(url).status_code,302)
        self.client.force_login(self.tenant_user)
        self.assertEqual(self.client.get(url).status_code,403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.detail).status_code,404)
        self.assertEqual(self.client.post(self.detail,{'action':'activate'}).status_code,404)
        self.client.force_login(self.sales)
        self.assertContains(self.client.get(url),'Teste social')
        self.client.force_login(self.master)
        self.assertEqual(self.client.get(self.detail).status_code,200)

    def test_create_defaults_to_draft_and_cannot_inject_owner_or_status(self):
        self.client.force_login(self.sales)
        response=self.client.post(reverse('commercial-social-create'),{'name':'Nova','headline':'Uma campanha',
            'channel':'facebook','objective':'lead','owner':self.other.pk,'status':'active'})
        self.assertEqual(response.status_code,302)
        row=SocialCampaign.objects.get(name='Nova')
        self.assertEqual(row.owner,self.sales)
        self.assertEqual(row.status,'draft')

    def test_drafts_and_paused_pages_are_not_public(self):
        self.assertEqual(self.client.get(self.public).status_code,404)
        self.activate()
        self.assertContains(self.client.get(self.public),'Organize a sua agenda')
        self.campaign.status='paused';self.campaign.save()
        self.assertEqual(self.client.get(self.public).status_code,404)
        self.assertEqual(self.client.post(self.public,self.data).status_code,404)

    def test_upload_normalizes_images_and_protects_unpublished_media(self):
        self.client.force_login(self.sales)
        self.assertEqual(self.upload().status_code,302)
        asset=SocialCampaignMedia.objects.get()
        self.assertEqual(asset.content_type,'image/jpeg')
        self.assertEqual((asset.width,asset.height),(1080,1350))
        self.assertTrue(asset.file.name.startswith('private/social/'))
        download=reverse('commercial-social-media',args=[asset.pk])
        public=reverse('commercial-social-public-media',args=[self.campaign.code,asset.pk])
        response=self.client.get(download+'?download=1')
        self.assertIn('attachment',response['Content-Disposition'])
        b"".join(response.streaming_content)
        self.client.logout()
        self.assertEqual(self.client.get(download).status_code,302)
        self.assertEqual(self.client.get(public).status_code,404)
        self.activate()
        response=self.client.get(public)
        self.assertEqual(response['Content-Type'],'image/jpeg')
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        b"".join(response.streaming_content)
        self.assertEqual(self.client.get('/media/'+asset.file.name).status_code,404)

    def test_upload_rejects_fake_images_svg_and_fake_mp4(self):
        self.client.force_login(self.sales)
        for filename in ('bad.jpg','script.svg','bad.mp4'):
            with self.subTest(filename=filename):
                response=self.upload(file=SimpleUploadedFile(filename,b'<script>bad()</script>'))
                self.assertEqual(response.status_code,200)
                self.assertTrue(response.context['media_form'].errors)
        self.assertFalse(SocialCampaignMedia.objects.exists())

    def test_upload_requires_media_rights_and_enforces_count_limit(self):
        self.client.force_login(self.sales)
        self.upload(rights='')
        self.assertFalse(SocialCampaignMedia.objects.exists())
        for i in range(10):
            SocialCampaignMedia.objects.create(campaign=self.campaign,title=str(i),file='private/social/test.jpg',content_type='image/jpeg')
        response=self.upload()
        self.assertContains(response,'até 10 mídias')
        self.assertEqual(self.campaign.media.count(),10)

    def test_activate_and_pause_are_explicit_post_actions(self):
        self.client.force_login(self.sales)
        self.assertEqual(self.client.get(self.detail+'?action=activate').status_code,200)
        self.campaign.refresh_from_db();self.assertEqual(self.campaign.status,'draft')
        self.client.post(self.detail,{'action':'activate'})
        self.campaign.refresh_from_db();self.assertEqual(self.campaign.status,'active')
        self.client.post(self.detail,{'action':'pause'})
        self.campaign.refresh_from_db();self.assertEqual(self.campaign.status,'paused')

    def test_public_form_creates_one_attributed_lead_and_keeps_registration_link(self):
        self.activate()
        response=self.client.get(self.public+'?utm_source=facebook')
        self.assertEqual(response.context['signup_link'].split('utm_campaign=')[-1],self.campaign.tracking_code)
        self.assertEqual(self.client.post(self.public+'?utm_source=facebook',self.data).status_code,302)
        lead=Lead.objects.get()
        self.assertEqual(lead.source,'facebook')
        self.assertEqual(lead.source_campaign,self.campaign.tracking_code)
        self.assertEqual(lead.phone,'5581999999999')
        self.assertTrue(lead.consent_granted)
        self.assertEqual(lead.consent_version,'social_contact_v1')
        self.assertFalse(AcquisitionEvent.objects.get(event_name='Lead').marketing_consent)
        self.client.post(self.public,self.data)
        self.assertEqual(Lead.objects.count(),1)
        self.assertEqual(SocialCampaignContact.objects.count(),1)
        self.assertEqual(AcquisitionEvent.objects.filter(event_name='Lead').count(),1)
        response=self.client.get(self.public+'?recebido=1')
        self.assertContains(response,'Seu contato foi recebido')
        self.assertIn('utm_source=facebook',response.context['signup_link'])

    def test_consent_is_required_and_meta_consent_is_separate(self):
        self.activate()
        response=self.client.post(self.public,{**self.data,'consent':''})
        self.assertEqual(response.status_code,200)
        self.assertFalse(Lead.objects.exists())
        self.client.post(self.public,{**self.data,'marketing':'on'})
        self.assertTrue(AcquisitionEvent.objects.get(event_name='Lead').marketing_consent)

    def test_honeypot_and_rate_limit_do_not_create_contacts(self):
        self.activate()
        self.client.post(self.public,{**self.data,'website':'spam'})
        self.assertFalse(Lead.objects.exists())
        for _ in range(9):
            response=self.client.post(self.public,{})
        self.assertContains(response,'Muitas tentativas')
        self.assertFalse(Lead.objects.exists())

    def test_existing_contact_preferences_are_never_reset(self):
        self.activate()
        lead=Lead.objects.create(name='Contato existente',phone=self.data['phone'],email=self.data['email'],business_type='Salão',
            do_not_contact=True,consent_granted=False,assigned_to=self.other)
        self.client.post(self.public,self.data)
        lead.refresh_from_db()
        self.assertTrue(lead.do_not_contact)
        self.assertFalse(lead.consent_granted)
        self.assertEqual(Lead.objects.count(),1)
        self.client.force_login(self.sales)
        self.assertNotContains(self.client.get(self.detail),'Contato existente')

    def test_visits_and_registration_metrics_are_real_and_scoped(self):
        self.activate()
        self.client.get(self.public)
        self.client.get(self.public)
        self.assertEqual(AcquisitionEvent.objects.filter(event_name='PageView').count(),1)
        self.client.force_login(self.sales)
        response=self.client.get(self.detail)
        self.assertEqual(response.context['stats'],{'visits':1,'contacts':0,'registrations':0})

    def test_public_capture_requires_csrf(self):
        self.activate()
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.public,self.data).status_code,403)
        self.assertFalse(Lead.objects.exists())

    def test_anonymization_removes_campaign_contact_fingerprints(self):
        from .services import anonymize_lead
        self.activate()
        self.client.post(self.public,self.data)
        self.assertTrue(SocialCampaignContact.objects.exists())
        anonymize_lead(lead=Lead.objects.get(),actor=self.master)
        self.assertFalse(SocialCampaignContact.objects.exists())

    def test_registration_metrics_deduplicate_companies_and_ignore_other_campaigns(self):
        import uuid
        tenant=self.tenant_user.tenant
        for campaign in [self.campaign.tracking_code,self.campaign.tracking_code,'other-campaign']:
            AcquisitionEvent.objects.create(session_key='social-review',event_id=uuid.uuid4(),event_name='CompleteRegistration',tenant=tenant,campaign=campaign)
        self.client.force_login(self.sales)
        self.assertEqual(self.client.get(self.detail).context['stats']['registrations'],1)

    def test_another_sales_user_cannot_download_private_creative(self):
        self.client.force_login(self.sales)
        self.upload()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('commercial-social-media',args=[SocialCampaignMedia.objects.get().pk])).status_code,404)
