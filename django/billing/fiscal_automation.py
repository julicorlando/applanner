"""Durable fiscal outbox; one document per payment and stable DPS across retries."""
import base64
from datetime import timedelta
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from core.audit import append_audit
from core.crypto import encrypt_text,decrypt_text
from .models import Payment,FiscalDocumentRequest,PlatformFiscalSettings,TenantFiscalProfile
from .nfse_national import NationalClient,FiscalError,build_dps,invoice_xml


def record(row,state,error=''):
    row.emission_state=state;row.last_error=error[:500]
    row.emission_history=(row.emission_history+[{'at':timezone.now().isoformat(),'state':state,'attempt':row.attempts,'error':error[:500]}])[-30:]


def eligible(payment):
    return (payment.status=='paid' and payment.environment=='production' and payment.purpose=='subscription' and payment.subscription_id
        and payment.subscription.tenant_id==payment.tenant_id and payment.amount>0 and payment.paid_at
        and not payment.tenant.is_demo and not payment.tenant.deleted_at and not payment.tenant.archived_at)


def prepare(payment_id,*,manual=False):
    config=PlatformFiscalSettings.objects.filter(pk=1,enabled=True,tax_confirmed=True).first()
    if not config:return None
    with transaction.atomic():
        payment=Payment.objects.select_for_update().select_related('subscription','tenant').get(pk=payment_id)
        if not eligible(payment) or (not manual and payment.paid_at<config.auto_from):return None
        if payment.amount<=0:return None
        user=payment.tenant.users.filter(role__in=['owner','manager','tenant-admin'],is_active=True).order_by('pk').first()
        if not user:return None
        from .breakdown import subscription_charge_breakdown
        row,created=FiscalDocumentRequest.objects.get_or_create(payment=payment,defaults={
            'tenant':payment.tenant,'subscription':payment.subscription,'requested_by':user,'requested_at':timezone.now(),
            'reference_month':timezone.localtime(payment.paid_at).date().replace(day=1),'amount':payment.amount,
            'charge_breakdown':(payment.metadata or {}).get('breakdown') or subscription_charge_breakdown(payment.subscription)})
        if row.status=='issued' or row.emission_state!='manual':return row
        record(row,'queued');row.next_attempt_at=timezone.now();row.save()
        append_audit(tenant=row.tenant,action='FISCAL_QUEUED',entity_type='billing.FiscalDocumentRequest',entity_id=row.pk,after={'payment_id':payment.pk,'environment':config.environment})
        return row


def dispatch(payment_id):
    """Broker outage must never roll back an approved payment; beat recovers the outbox."""
    try:
        row=prepare(payment_id)
        if row:
            from .tasks import process_fiscal_document
            process_fiscal_document.delay(row.pk)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Fiscal outbox pending reconciliation for payment %s',payment_id)


def process(document_id):
    now=timezone.now();lease=now+timedelta(minutes=15)
    config=PlatformFiscalSettings.objects.filter(pk=1,enabled=True,tax_confirmed=True).first()
    if not config:return False
    with transaction.atomic():
        row=FiscalDocumentRequest.objects.select_for_update().select_related('payment__subscription','payment__tenant','tenant').get(pk=document_id)
        if row.emission_state=='manual' or (row.status=='issued' and row.emission_state!='authorized'):return False
        if row.emission_state=='authorized' and row.pdf_file:return False
        if row.processing_until and row.processing_until>now:return False
        if row.next_attempt_at and row.next_attempt_at>now:return False
        if row.attempts>=6:return False
        if not eligible(row.payment) and row.emission_state!='authorized' and not row.signed_dps_encrypted:
            record(row,'error','Pagamento não elegível para emissão automática. Confira pagamento, empresa e eventual estorno.');row.next_attempt_at=None;row.save();return False
        if row.issuer_document and row.issuer_document!=config.document:
            record(row,'error','O CNPJ emissor mudou. Restaure o emissor original para consultar esta DPS.');row.save();return False
        row.processing_until=lease;row.attempts+=1
        if row.emission_state!='authorized':record(row,'processing')
        row.save()
    client=NationalClient(config,row.fiscal_environment or config.environment)
    try:
        if row.emission_state=='authorized':
            key=row.access_key;number=row.invoice_number;xml=None
        else:
            if not row.signed_dps_encrypted:
                profile=TenantFiscalProfile.objects.filter(tenant=row.tenant).first()
                if not profile:raise FiscalError('Complete os dados fiscais da empresa na tela de pagamentos.')
                ident,xml=build_dps(row,config,profile)
                row.dps_id=ident;row.fiscal_environment=config.environment;row.issuer_document=config.document
                row.signed_dps_encrypted=encrypt_text(base64.b64encode(xml).decode())
                FiscalDocumentRequest.objects.filter(pk=row.pk,processing_until=lease).update(dps_id=ident,fiscal_environment=row.fiscal_environment,issuer_document=row.issuer_document,signed_dps_encrypted=row.signed_dps_encrypted)
            else:xml=base64.b64decode(decrypt_text(row.signed_dps_encrypted))
            # Always reconcile the same DPS before submitting. A timeout never allocates a new number.
            found=client.lookup(row.dps_id)
            if found:
                key=found.get('chaveAcesso','')
                import re
                if not re.fullmatch(r'\d{50}',key):raise FiscalError('Consulta da DPS retornou chave inválida.',uncertain=True)
                result=client.invoice(key)
            else:
                if not eligible(row.payment):raise FiscalError('Pagamento não elegível. A consulta não encontrou nota autorizada; nenhuma DPS será transmitida.')
                if row.status=='rejected':
                    profile=TenantFiscalProfile.objects.filter(tenant=row.tenant).first()
                    if not profile:raise FiscalError('Complete os dados fiscais da empresa.')
                    ident,xml=build_dps(row,config,profile)
                    if ident!=row.dps_id:raise FiscalError('Restaure CNPJ, município e série originais desta DPS para corrigir a rejeição.')
                    row.signed_dps_encrypted=encrypt_text(base64.b64encode(xml).decode())
                    row.status='requested'
                    FiscalDocumentRequest.objects.filter(pk=row.pk,processing_until=lease).update(signed_dps_encrypted=row.signed_dps_encrypted,status='requested')
                result=client.submit(xml)
            key,number,xml=invoice_xml(result,row)
        pdf=None;pdf_error=''
        try:
            from .danfse import render_danfse
            if xml is None:
                row.xml_file.open('rb')
                try:xml_for_pdf=row.xml_file.read()
                finally:row.xml_file.close()
            else:xml_for_pdf=xml
            pdf=render_danfse(xml_for_pdf)
        except FiscalError:pdf_error='NFS-e autorizada. O PDF ainda não está disponível; o XML foi preservado.'
        with transaction.atomic():
            current=FiscalDocumentRequest.objects.select_for_update().get(pk=row.pk)
            if current.processing_until!=lease:return False
            current.access_key=key;current.invoice_number=number
            if xml and not current.xml_file:current.xml_file.save(f'NFSe-{current.pk}.xml',ContentFile(xml),save=False)
            if pdf and not current.pdf_file:current.pdf_file.save(f'NFSe-{current.pk}.pdf',ContentFile(pdf),save=False)
            record(current,'authorized',pdf_error)
            # Homologation documents never masquerade as a customer's valid tax invoice.
            if current.fiscal_environment=='production':
                current.status='issued';current.uploaded_at=timezone.now()
                if not current.notice_queued_at:
                    from communications.models import Notification
                    from django.conf import settings
                    from django.urls import reverse
                    profile=TenantFiscalProfile.objects.filter(tenant=current.tenant).first()
                    if profile:
                        url=settings.PUBLIC_BASE_URL.rstrip('/')+reverse('billing-subscription-status')
                        Notification.objects.create(tenant=current.tenant,channel='email',template_key='fiscal_invoice',destination=profile.email,
                            payload={'subject':'Sua nota fiscal do ApPlanner está disponível','text':f'Sua NFS-e nº {number} foi autorizada. Acesse Pagamentos para baixar o documento: {url}','fiscal_document_id':current.pk},status='queued')
                        current.notice_queued_at=timezone.now()
            current.processing_until=None;current.next_attempt_at=timezone.now()+timedelta(minutes=30) if pdf_error else None;current.save()
            append_audit(tenant=current.tenant,action='NFSE_AUTHORIZED',entity_type='billing.FiscalDocumentRequest',entity_id=current.pk,after={'payment_id':current.payment_id,'environment':current.fiscal_environment,'pdf':bool(current.pdf_file)})
        return True
    except Exception as exc:
        error=str(exc) if isinstance(exc,FiscalError) else 'Falha interna na emissão. Consulte o monitoramento técnico e tente novamente.'
        uncertain=not isinstance(exc,FiscalError) or exc.uncertain
        with transaction.atomic():
            current=FiscalDocumentRequest.objects.select_for_update().get(pk=row.pk)
            if current.processing_until!=lease:return False
            record(current,'waiting' if uncertain else 'error',error)
            if isinstance(exc,FiscalError) and exc.rejected:current.status='rejected'
            current.processing_until=None;current.next_attempt_at=timezone.now()+timedelta(minutes=min(60,5*2**min(current.attempts,4))) if uncertain else None
            current.save()
            append_audit(tenant=current.tenant,action='NFSE_PENDING',entity_type='billing.FiscalDocumentRequest',entity_id=current.pk,after={'state':current.emission_state,'attempt':current.attempts})
        return False


def reconcile():
    config=PlatformFiscalSettings.objects.filter(pk=1,enabled=True,tax_confirmed=True).first()
    if not config:return 0
    ids=Payment.objects.filter(status='paid',environment='production',purpose='subscription',paid_at__gte=config.auto_from).filter(Q(fiscal_document_request__isnull=True)|Q(fiscal_document_request__emission_state='manual',fiscal_document_request__status='requested')).order_by('pk').values_list('pk',flat=True)[:100]
    for pk in ids:prepare(pk)
    rows=FiscalDocumentRequest.objects.filter(emission_state__in=['queued','waiting','processing','authorized'],attempts__lt=6,next_attempt_at__lte=timezone.now()).filter(Q(processing_until__isnull=True)|Q(processing_until__lt=timezone.now())).values_list('pk',flat=True)[:25]
    from .tasks import process_fiscal_document
    for pk in rows:process_fiscal_document.delay(pk)
    return len(rows)
