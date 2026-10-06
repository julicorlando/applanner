import base64,gzip
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch,MagicMock
from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from cryptography import x509
from cryptography.x509.oid import NameOID,ObjectIdentifier
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree
from signxml import XMLVerifier
from accounts.models import User
from tenants.models import Tenant
from communications.models import Notification
from core.crypto import encrypt_text,decrypt_text
from .models import Plan,Subscription,Payment,PlatformFiscalSettings,TenantFiscalProfile,FiscalDocumentRequest
from .nfse_national import build_dps,certificate_data,FiscalError,NationalClient,invoice_xml,valid_document,NS
from .fiscal_automation import prepare,process,reconcile,dispatch
from .fiscal_views import FiscalSettingsForm

CNPJ='11222333000181'

def certificate(document=CNPJ,expired=False):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=timezone.now()
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic fiscal tests')])
    der=b'\x0c\x0e'+document.encode()
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(days=10)).not_valid_after(now+timedelta(days=-1 if expired else 90))
        .add_extension(x509.SubjectAlternativeName([x509.OtherName(ObjectIdentifier('2.16.76.1.3.3'),der)]),critical=False).sign(key,hashes.SHA256()))
    raw=pkcs12.serialize_key_and_certificates(b'test',key,cert,None,serialization.BestAvailableEncryption(b'synthetic-password'))
    return raw,cert


@override_settings(SUBSCRIPTION_ACCESS_ENFORCED=False)
class NfseAutomationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.raw,cls.cert=certificate()
        cls.tenant=Tenant.objects.create(name='Fiscal QA',slug='fiscal-qa',document=CNPJ,email='fiscal@example.test')
        cls.owner=User.objects.create_user(email='owner-fiscal@example.test',tenant=cls.tenant,role='owner')
        cls.master=User.objects.create_superuser(email='master-fiscal@example.test',password='Synthetic-Password123!')
        plan=Plan.objects.create(name='Plano',slug='fiscal',monthly_price=100)
        cls.sub=Subscription.objects.create(tenant=cls.tenant,plan=plan,status='active',started_at=timezone.now())
        cls.config=PlatformFiscalSettings.objects.create(enabled=True,tax_confirmed=True,environment='production',auto_from=timezone.now()-timedelta(days=1),document=CNPJ,legal_name='Emissor QA',municipality_code='2611101',service_code='010501',service_description='Serviço de homologação',certificate_encrypted=encrypt_text(base64.b64encode(cls.raw).decode()),certificate_password_encrypted=encrypt_text('synthetic-password'))
        cls.profile=TenantFiscalProfile.objects.create(tenant=cls.tenant,document=CNPJ,legal_name='Fiscal QA',email='fiscal@example.test',municipality_code='2611101',postal_code='55815000',street='Rua Teste',number='1',district='Centro')
    def setUp(self):
        self.client.force_login(self.owner)
        self.payment=Payment.objects.create(tenant=self.tenant,subscription=self.sub,status='paid',environment='production',amount=100,paid_at=timezone.now())
        self.row=prepare(self.payment.pk)

    def response(self,row=None):
        row=row or FiscalDocumentRequest.objects.get(pk=self.row.pk)
        ident,xml=build_dps(row,self.config,self.profile)
        # Fake only authority's envelope; signed DPS is real and XSD validated.
        key='1'*50
        root=etree.Element('{%s}NFSe'%NS,nsmap={None:NS},versao='1.01')
        inf=etree.SubElement(root,'{%s}infNFSe'%NS,Id='NFS'+key)
        etree.SubElement(inf,'{%s}nNFSe'%NS).text='123'
        inf.append(etree.fromstring(xml))
        return {'chaveAcesso':key,'nfseXmlGZipB64':base64.b64encode(gzip.compress(etree.tostring(root))).decode()}

    def test_signed_dps_matches_official_xsd_and_signature(self):
        ident,xml=build_dps(self.row,self.config,self.profile)
        signed=XMLVerifier().verify(xml,x509_cert=self.cert.public_bytes(serialization.Encoding.PEM)).signed_xml
        self.assertEqual(signed.get('Id'),ident)
        self.assertEqual(signed.findtext('{%s}tpAmb'%NS),'1')
        self.assertEqual(signed.findtext('.//{%s}vServ'%NS),'100.00')
        self.assertEqual(signed.findtext('.//{%s}opSimpNac'%NS),'2')
        from .danfse import render_danfse
        data=self.response();pdf=render_danfse(gzip.decompress(base64.b64decode(data['nfseXmlGZipB64'])))
        self.assertTrue(pdf.startswith(b'%PDF-'));self.assertIn(b'/Count 1',pdf)

    def test_automatic_authorization_and_email_only_once(self):
        with patch('billing.fiscal_automation.NationalClient') as provider:
            api=provider.return_value;api.lookup.return_value=None;api.submit.return_value=self.response();api.pdf.return_value=b'%PDF-synthetic'
            self.assertTrue(process(self.row.pk));self.assertFalse(process(self.row.pk))
            self.assertEqual(api.submit.call_count,1)
        self.row.refresh_from_db();self.assertEqual(self.row.status,'issued');self.assertTrue(self.row.pdf_file);self.assertTrue(self.row.xml_file)
        self.assertEqual(Notification.objects.filter(template_key='fiscal_invoice').count(),1)
        self.assertEqual(prepare(self.payment.pk).pk,self.row.pk)

    def test_timeout_reconciles_same_dps_without_second_submit(self):
        with patch('billing.fiscal_automation.NationalClient') as provider:
            api=provider.return_value;api.lookup.return_value=None;api.submit.side_effect=FiscalError('Resultado incerto',uncertain=True)
            self.assertFalse(process(self.row.pk))
        self.row.refresh_from_db();snapshot=self.row.signed_dps_encrypted;ident=self.row.dps_id
        FiscalDocumentRequest.objects.filter(pk=self.row.pk).update(next_attempt_at=timezone.now())
        with patch('billing.fiscal_automation.NationalClient') as provider:
            api=provider.return_value;api.lookup.return_value={'chaveAcesso':'1'*50};api.invoice.return_value=self.response();api.pdf.return_value=b'%PDF-synthetic'
            self.assertTrue(process(self.row.pk));api.submit.assert_not_called();api.lookup.assert_called_once_with(ident)
        self.row.refresh_from_db();self.assertEqual(self.row.signed_dps_encrypted,snapshot)

    def test_payment_filters_and_no_historical_auto_emission(self):
        for environment,status,purpose in [('sandbox','paid','subscription'),('production','pending','subscription'),('production','paid','appointment')]:
            row=Payment.objects.create(tenant=self.tenant,subscription=self.sub,amount=100,environment=environment,status=status,purpose=purpose,paid_at=timezone.now())
            self.assertIsNone(prepare(row.pk))
        row=Payment.objects.create(tenant=self.tenant,subscription=self.sub,amount=100,status='paid',environment='production',paid_at=timezone.now()-timedelta(days=3))
        self.assertIsNone(prepare(row.pk));self.assertIsNotNone(prepare(row.pk,manual=True))

    def test_missing_profile_blocks_invoice_not_payment_and_profile_repairs(self):
        self.profile.delete()
        with patch('billing.fiscal_automation.NationalClient') as provider:
            self.assertFalse(process(self.row.pk));provider.return_value.submit.assert_not_called()
        self.row.refresh_from_db();self.payment.refresh_from_db();self.assertEqual(self.row.emission_state,'error');self.assertEqual(self.payment.status,'paid')
        self.assertEqual(self.client.post(reverse('billing-fiscal-profile'),{'document':CNPJ,'legal_name':'Empresa','email':'fiscal@example.test','municipality_code':'2611101','postal_code':'55815-000','street':'Rua QA','number':'1','district':'Centro'}).status_code,302)
        self.row.refresh_from_db();self.assertEqual(self.row.emission_state,'queued')

    def test_live_processing_lease_prevents_duplicate_worker(self):
        FiscalDocumentRequest.objects.filter(pk=self.row.pk).update(processing_until=timezone.now()+timedelta(minutes=10))
        with patch('billing.fiscal_automation.NationalClient') as provider:
            self.assertFalse(process(self.row.pk));provider.assert_not_called()

    def test_wrong_invoice_response_is_not_published(self):
        result=self.response();result['chaveAcesso']='2'*50
        with patch('billing.fiscal_automation.NationalClient') as provider:
            api=provider.return_value;api.lookup.return_value=None;api.submit.return_value=result
            self.assertFalse(process(self.row.pk))
        self.row.refresh_from_db();self.assertNotEqual(self.row.status,'issued');self.assertFalse(self.row.xml_file)

    def test_pdf_outage_does_not_repeat_emission(self):
        with patch('billing.fiscal_automation.NationalClient') as provider, patch('billing.danfse.render_danfse',side_effect=FiscalError('PDF indisponível',uncertain=True)):
            api=provider.return_value;api.lookup.return_value=None;api.submit.return_value=self.response()
            self.assertTrue(process(self.row.pk))
        self.row.refresh_from_db();self.assertEqual(self.row.status,'issued');self.assertTrue(self.row.xml_file)
        FiscalDocumentRequest.objects.filter(pk=self.row.pk).update(next_attempt_at=timezone.now())
        with patch('billing.fiscal_automation.NationalClient') as provider:
            api=provider.return_value;api.pdf.return_value=b'%PDF-synthetic'
            self.assertTrue(process(self.row.pk));api.submit.assert_not_called();api.lookup.assert_not_called()
        self.assertEqual(Notification.objects.filter(template_key='fiscal_invoice').count(),1)

    def test_homologation_hidden_and_explicit_production_transition(self):
        PlatformFiscalSettings.objects.filter(pk=1).update(environment='homologation');self.config.environment='homologation'
        with patch('billing.fiscal_automation.NationalClient') as provider:
            api=provider.return_value;api.lookup.return_value=None;api.submit.return_value=self.response();api.pdf.return_value=b'%PDF-synthetic'
            self.assertTrue(process(self.row.pk))
        self.row.refresh_from_db();self.assertEqual(self.row.status,'requested');self.assertFalse(Notification.objects.filter(template_key='fiscal_invoice').exists())
        url=reverse('billing-nfe-download',args=[self.row.pk,'xml']);self.assertEqual(self.client.get(url).status_code,404)
        self.client.force_login(self.master);self.assertEqual(self.client.get(url).status_code,200)
        PlatformFiscalSettings.objects.filter(pk=1).update(environment='production')
        self.assertEqual(self.client.post(reverse('master-nfse-retry',args=[self.row.pk])).status_code,302)
        self.row.refresh_from_db();self.assertEqual(self.row.fiscal_environment,'production');self.assertFalse(self.row.signed_dps_encrypted);self.assertFalse(self.row.xml_file)

    def test_master_only_and_tenant_isolation(self):
        for name in ['master-nfse-center','master-fiscal-settings']:
            self.assertEqual(self.client.get(reverse(name)).status_code,403)
        self.assertEqual(self.client.post(reverse('master-nfse-retry',args=[self.row.pk])).status_code,403)
        other=Tenant.objects.create(name='Outra',slug='fiscal-other');user=User.objects.create_user(email='other-fiscal@example.test',tenant=other,role='owner')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('billing-nfe-download',args=[self.row.pk,'xml'])).status_code,403)
        staff=User.objects.create_user(email='staff-fiscal@example.test',tenant=self.tenant,role='professional')
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('billing-nfe-download',args=[self.row.pk,'xml'])).status_code,403)
        self.client.force_login(self.master)
        self.assertContains(self.client.get(reverse('master-nfse-center')),'Fiscal QA')
        self.assertContains(self.client.get(reverse('master-fiscal-settings')),'Configuração fiscal')

    def test_certificate_validation_and_form_encryption(self):
        for raw,password,doc in [(self.raw,'wrong',CNPJ),(self.raw,'synthetic-password','11444777000161'),(certificate(expired=True)[0],'synthetic-password',CNPJ)]:
            with self.assertRaises(FiscalError):certificate_data(raw,password,doc)
        data={'enabled':'on','environment':'production','document':CNPJ,'legal_name':'Emissor QA','municipality_code':'2611101','service_code':'010501','service_description':'Serviço','series':1,'auto_from':timezone.now().strftime('%Y-%m-%dT%H:%M'),'tax_confirmed':'on','certificate_password':'synthetic-password'}
        form=FiscalSettingsForm(data,{'certificate':SimpleUploadedFile('a1.pfx',self.raw)},instance=PlatformFiscalSettings.objects.get(pk=1))
        self.assertFalse(form.is_valid());self.assertIn('confirm_production',form.errors)
        data['confirm_production']='on';form=FiscalSettingsForm(data,{'certificate':SimpleUploadedFile('a1.pfx',self.raw)},instance=PlatformFiscalSettings.objects.get(pk=1))
        self.assertTrue(form.is_valid(),form.errors);self.assertNotIn('synthetic-password',form.certificate_values[1]);self.assertEqual(decrypt_text(form.certificate_values[1]),'synthetic-password')
        self.assertFalse(valid_document('11111111111111'))

    def test_refund_and_attempt_ceiling_stop_new_issuance(self):
        Payment.objects.filter(pk=self.payment.pk).update(status='refunded')
        with patch('billing.fiscal_automation.NationalClient') as provider:
            self.assertFalse(process(self.row.pk));provider.assert_not_called()
        Payment.objects.filter(pk=self.payment.pk).update(status='paid')
        FiscalDocumentRequest.objects.filter(pk=self.row.pk).update(attempts=6)
        self.assertFalse(process(self.row.pk))

    def test_broker_failure_does_not_undo_payment_and_reconciliation_recovers(self):
        with patch('billing.tasks.process_fiscal_document.delay',side_effect=RuntimeError('broker down')):dispatch(self.payment.pk)
        self.payment.refresh_from_db();self.assertEqual(self.payment.status,'paid')
        with patch('billing.tasks.process_fiscal_document.delay') as queue:
            self.assertEqual(reconcile(),1);queue.assert_called_once_with(self.row.pk)

    @override_settings(SUBSCRIPTION_ACCESS_ENFORCED=True)
    def test_expired_company_can_manage_fiscal_data_in_payment_area(self):
        Subscription.objects.filter(pk=self.sub.pk).update(status='suspended')
        self.assertEqual(self.client.get(reverse('billing-fiscal-profile')).status_code,200)

    def test_rejected_dps_can_be_corrected_without_changing_identifier(self):
        with patch('billing.fiscal_automation.NationalClient') as provider:
            api=provider.return_value;api.lookup.return_value=None;api.submit.side_effect=FiscalError('Rejeição RNG',rejected=True)
            self.assertFalse(process(self.row.pk))
        self.row.refresh_from_db();self.assertEqual(self.row.status,'rejected');ident=self.row.dps_id
        PlatformFiscalSettings.objects.filter(pk=1).update(service_description='Descrição corrigida')
        self.config.service_description='Descrição corrigida'
        self.client.force_login(self.master);self.client.post(reverse('master-nfse-retry',args=[self.row.pk]))
        with patch('billing.fiscal_automation.NationalClient') as provider:
            api=provider.return_value;api.lookup.return_value=None;api.submit.return_value=self.response();api.pdf.return_value=b'%PDF-test'
            self.assertTrue(process(self.row.pk))
            xml=api.submit.call_args.args[0];self.assertIn('Descrição corrigida'.encode(),xml)
        self.row.refresh_from_db();self.assertEqual(self.row.dps_id,ident)

    def test_transport_fixed_hosts_certificate_cleanup_and_safe_errors(self):
        import json,os
        paths=[]
        with patch('billing.nfse_national.requests.Session') as mocked:
            session=mocked.return_value.__enter__.return_value
            response=session.request.return_value.__enter__.return_value
            response.status_code=200;response.iter_content.return_value=[b'{}']
            def capture(*args,**kwargs):
                for path in session.cert:
                    self.assertEqual(os.stat(path).st_mode & 0o777,0o600);paths.append(path)
                return session.request.return_value
            session.request.side_effect=capture
            self.assertEqual(NationalClient(self.config,'production').lookup('DPS-test'),{})
            self.assertFalse(session.request.call_args.kwargs['allow_redirects'])
            self.assertEqual(session.request.call_args.args[1],'https://sefin.nfse.gov.br/SefinNacional/dps/DPS-test')
        for path in paths:self.assertFalse(os.path.exists(path))
        with patch('billing.nfse_national.NationalClient.connection') as connection:
            session=connection.return_value.__enter__.return_value;response=session.request.return_value.__enter__.return_value
            response.status_code=403;response.iter_content.return_value=[json.dumps({'erros':[{'Codigo':'AUTH','Descricao':'secret-private-body'}]}).encode()]
            with self.assertRaises(FiscalError) as error:NationalClient(self.config,'production').lookup('DPS-test')
            self.assertTrue(error.exception.uncertain);self.assertNotIn('secret-private-body',str(error.exception))

    def test_wrong_customer_in_authorized_xml_is_rejected(self):
        self.row.dps_id,xml=build_dps(self.row,self.config,self.profile)
        self.row.issuer_document=CNPJ;self.row.fiscal_environment='production';self.row.signed_dps_encrypted=encrypt_text(base64.b64encode(xml).decode())
        result=self.response();raw=gzip.decompress(base64.b64decode(result['nfseXmlGZipB64']));root=etree.fromstring(raw)
        root.find('.//{%s}toma/{%s}CNPJ'%(NS,NS)).text='11444777000161'
        result['nfseXmlGZipB64']=base64.b64encode(gzip.compress(etree.tostring(root))).decode()
        with self.assertRaises(FiscalError):invoice_xml(result,self.row)


from django.test import TransactionTestCase,skipUnlessDBFeature
class NfseConcurrentWorkersTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_two_workers_claim_only_one_emission(self):
        import threading
        from django.db import close_old_connections
        NfseAutomationTests.setUpTestData.__func__(type(self))
        payment=Payment.objects.create(tenant=self.tenant,subscription=self.sub,status='paid',environment='production',amount=100,paid_at=timezone.now())
        row=prepare(payment.pk);entered=threading.Event();release=threading.Event();errors=[];results=[]
        def lookup(_):
            entered.set()
            if not release.wait(10):raise RuntimeError('Test timed out')
            return None
        def worker():
            close_old_connections()
            try:results.append(process(row.pk))
            except Exception as exc:errors.append(exc)
            finally:close_old_connections()
        with patch('billing.fiscal_automation.NationalClient') as provider:
            api=provider.return_value;api.lookup.side_effect=lookup;api.submit.side_effect=FiscalError('synthetic timeout',uncertain=True)
            thread=threading.Thread(target=worker);thread.start()
            try:
                self.assertTrue(entered.wait(10));self.assertFalse(process(row.pk))
            finally:release.set();thread.join(15)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[]);self.assertEqual(api.submit.call_count,1)
        self.assertEqual(results,[False])
