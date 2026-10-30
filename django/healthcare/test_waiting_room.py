from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
import uuid
from PIL import Image
from django.test import TestCase, override_settings, Client
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import User
from billing.models import Module, TenantModule
from tenants.models import Tenant
from scheduling.models import Customer, Professional, Service, Appointment
from core.crypto import decrypt_text
from .operation_models import WaitingRoomDisplay, WaitingRoomCall, WaitingRoomMedia
from .waiting_room import MediaForm


class WaitingRoomTests(TestCase):
    def setUp(self):
        directory=TemporaryDirectory();self.addCleanup(directory.cleanup)
        setting=override_settings(MEDIA_ROOT=directory.name);setting.enable();self.addCleanup(setting.disable)
        self.tenant=Tenant.objects.create(name='Clínica Demonstração',slug='tv-test',category='fisioterapia')
        self.owner=User.objects.create_user(email='tv-owner@test.invalid',tenant=self.tenant,role='owner')
        self.professional=Professional.objects.create(tenant=self.tenant,user=self.owner,name='Pessoa Responsável')
        self.patient=Customer.objects.create(tenant=self.tenant,name='Marina Silva',phone='5581999999999')
        self.service=Service.objects.create(tenant=self.tenant,name='Atendimento',price=100,duration_minutes=30)
        self.appointment=Appointment.objects.create(tenant=self.tenant,customer=self.patient,professional=self.professional,service=self.service,
            starts_at=timezone.now()-timedelta(minutes=10),ends_at=timezone.now()+timedelta(minutes=20))
        module,_=Module.objects.get_or_create(slug='waiting-room-tv',defaults={'name':'TV','active':True})
        self.entitlement=TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        self.display=WaitingRoomDisplay.objects.create(tenant=self.tenant,enabled=True)
        self.client.force_login(self.owner)

    def url(self, kind='screen', **kwargs):
        return reverse('waiting-room-'+kind,args=[self.tenant.slug,self.display.token,*kwargs.values()])

    def call(self, **kwargs):
        return self.client.post(reverse('waiting-room-call'),{'appointment':self.appointment.pk,'room':'Sala 02','request_id':str(uuid.uuid4()),**kwargs})

    def test_module_is_optional_and_cannot_be_bypassed_by_direct_url(self):
        self.entitlement.enabled=False;self.entitlement.save()
        self.assertEqual(self.client.get(reverse('waiting-room-console')).status_code,403)
        self.assertEqual(self.call().status_code,403)
        self.assertEqual(self.client.get(self.url()).status_code,404)
        self.assertEqual(self.client.get(self.url('feed')).status_code,404)
        self.assertFalse(WaitingRoomCall.objects.exists())

    def test_public_feed_uses_abbreviated_names_no_clinical_or_contact_details(self):
        self.assertEqual(self.call().status_code,302)
        row=WaitingRoomCall.objects.get()
        self.assertNotIn('Marina',row.label_encrypted)
        self.assertEqual(decrypt_text(row.label_encrypted),'Marina S.')
        self.client.logout()
        response=self.client.get(self.url('feed'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['calls'][0]['name'],'Marina S.')
        self.assertNotContains(response,self.patient.phone)
        self.assertNotContains(response,'Marina Silva')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(self.client.get(self.url()).status_code,200)
        WaitingRoomCall.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get(self.url('feed')).json()['calls'],[])

    def test_call_replay_is_idempotent_and_conflicting_reuse_rejected(self):
        key=str(uuid.uuid4())
        self.assertEqual(self.call(request_id=key).status_code,302)
        self.assertEqual(self.call(request_id=key).status_code,302)
        self.assertEqual(WaitingRoomCall.objects.count(),1)
        self.assertEqual(self.call(request_id=key,room='Sala 03').status_code,409)
        self.assertEqual(self.call(request_id='invalid').status_code,400)
        self.assertEqual(self.call(appointment='invalid').status_code,400)

    def test_rotation_and_module_revocation_revoke_old_public_links(self):
        old=self.url('feed')
        self.assertEqual(self.client.post(reverse('waiting-room-console'),{'action':'rotate'}).status_code,302)
        self.assertEqual(self.client.get(old).status_code,404)
        self.display.refresh_from_db()
        self.assertEqual(self.client.get(self.url('feed')).status_code,200)
        self.entitlement.enabled=False;self.entitlement.save()
        self.assertEqual(self.client.get(self.url('feed')).status_code,404)

    def test_reception_can_call_but_not_configure(self):
        reception=User.objects.create_user(email='tv-reception@test.invalid',tenant=self.tenant,role='reception')
        self.client.force_login(reception)
        self.assertEqual(self.call().status_code,302)
        self.assertEqual(self.client.post(reverse('waiting-room-console'),{'action':'rotate'}).status_code,403)
        self.assertEqual(self.client.get(reverse('waiting-room-console')).status_code,200)

    def test_clinician_cannot_call_another_professionals_patient(self):
        clinician=User.objects.create_user(email='tv-colleague@test.invalid',tenant=self.tenant,role='professional')
        Professional.objects.create(tenant=self.tenant,user=clinician,name='Outra Pessoa')
        self.client.force_login(clinician)
        self.assertEqual(self.call().status_code,404)
        other=Tenant.objects.create(name='Outra Clínica',slug='tv-other',category='fisioterapia')
        self.owner.tenant=other;self.owner.save()
        self.client.force_login(self.owner)
        module=Module.objects.get(slug='waiting-room-tv');TenantModule.objects.create(tenant=other,module=module,enabled=True)
        WaitingRoomDisplay.objects.create(tenant=other,enabled=True)
        self.assertEqual(self.call().status_code,404)

    def test_media_is_validated_encrypted_and_served_only_via_active_tv_token(self):
        data=BytesIO();Image.new('RGB',(100,50),'blue').save(data,format='PNG')
        raw=data.getvalue()
        file=SimpleUploadedFile('clinic.png',raw,content_type='image/png')
        response=self.client.post(reverse('waiting-room-console'),{'action':'upload','title':'Boas-vindas','file':file})
        self.assertEqual(response.status_code,302)
        row=WaitingRoomMedia.objects.get()
        with row.file.open('rb') as stream:self.assertNotIn(raw,stream.read())
        self.client.logout()
        response=self.client.get(self.url('media',pk=row.pk))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'image/jpeg')
        self.assertEqual(Image.open(BytesIO(b''.join(response.streaming_content))).size,(100,50))
        ranged=self.client.get(self.url('media',pk=row.pk),HTTP_RANGE='bytes=0-9')
        self.assertEqual(ranged.status_code,206);self.assertEqual(len(ranged.content),10)
        self.assertEqual(self.client.get(self.url('media',pk=row.pk),HTTP_RANGE='bytes=99999999-').status_code,416)
        row.active=False;row.save()
        self.assertEqual(self.client.get(self.url('media',pk=row.pk)).status_code,404)
        bad=MediaForm({'title':'Malicioso'},{'file':SimpleUploadedFile('image.png',b'<svg onload=alert(1)>')})
        self.assertFalse(bad.is_valid())
        bad=MediaForm({'title':'Malicioso'},{'file':SimpleUploadedFile('movie.mp4',b'<script>alert(1)</script>')})
        self.assertFalse(bad.is_valid())

    def test_csrf_required_and_retention_bounded(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.owner)
        self.assertEqual(client.post(reverse('waiting-room-call'),{'appointment':self.appointment.pk,'room':'Sala 01'}).status_code,403)
        response=self.client.post(reverse('waiting-room-console'),{'action':'settings','enabled':'on','title':'TV','retention_minutes':1000})
        self.assertEqual(response.status_code,200)
        self.display.refresh_from_db();self.assertEqual(self.display.retention_minutes,30)

    def test_explicit_role_links_preserve_reception_operational_access_only(self):
        from accounts.models import PlatformRole, UserRole
        role=PlatformRole.objects.create(name='Recepção teste TV',slug='reception-tv-test')
        reception=User.objects.create_user(email='tv-linked-reception@test.invalid',tenant=self.tenant,role='reception')
        UserRole.objects.create(user=reception,role=role)
        self.client.force_login(reception)
        response=self.client.get(reverse('waiting-room-console'))
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.call().status_code,302)
        self.assertEqual(self.client.get(reverse('clinical-dashboard')).status_code,403)
        self.assertEqual(self.client.get(reverse('clinical-offline-snapshot')).json()['entries'],[])

    def test_short_link_is_revocable_and_screen_footer_never_discloses_tv_token(self):
        response=self.client.get(reverse('waiting-room-short',args=[self.display.token]))
        self.assertRedirects(response,self.url(),fetch_redirect_response=False)
        response=self.client.get(self.url())
        footer=response.content.decode().split('<footer>')[1].split('</footer>')[0]
        self.assertNotIn(self.display.token,footer)
        old=reverse('waiting-room-short',args=[self.display.token])
        self.client.post(reverse('waiting-room-console'),{'action':'rotate'})
        self.assertEqual(self.client.get(old).status_code,404)
