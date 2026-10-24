import base64
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from core.audit import append_audit
from core.crypto import encrypt_text
from .models import PlatformFiscalSettings,TenantFiscalProfile,FiscalDocumentRequest
from .nfse_national import digits,valid_document,certificate_data,FiscalError


def master_guard(request):
    if not request.user.is_superuser:raise PermissionDenied('Acesso fiscal restrito ao Master.')


class FiscalSettingsForm(forms.ModelForm):
    document=forms.CharField(label="CNPJ do MEI",max_length=32)
    certificate=forms.FileField(label='Certificado A1 (.pfx/.p12)',required=False,help_text='Até 1 MB. Criptografado no banco; não fica disponível para download.')
    certificate_password=forms.CharField(label='Senha do certificado A1',required=False,widget=forms.PasswordInput(render_value=False))
    confirm_production=forms.BooleanField(label='Confirmo a ativação em produção após homologar a emissão',required=False)
    class Meta:
        model=PlatformFiscalSettings
        fields=['enabled','environment','document','legal_name','municipality_code','service_code','municipal_service_code','service_description','series','auto_from','tax_confirmed']
        widgets={'auto_from':forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'),'service_description':forms.Textarea(attrs={'rows':3})}
    def clean_document(self):
        value=digits(self.cleaned_data['document'])
        if len(value)!=14 or not valid_document(value):raise ValidationError('Informe um CNPJ válido do MEI.')
        return value
    def clean(self):
        data=super().clean()
        for key,length in [('municipality_code',7),('service_code',6),('municipal_service_code',3)]:
            value=data.get(key,'')
            if (value or key!='municipal_service_code') and (not value.isascii() or not value.isdigit() or len(value)!=length):self.add_error(key,f'Informe {length} dígitos, incluindo zeros à esquerda.')
        file=data.get('certificate');password=data.get('certificate_password','')
        if file:
            if file.size>1024*1024 or not file.name.lower().endswith(('.pfx','.p12')):self.add_error('certificate','Envie um certificado .pfx/.p12 de até 1 MB.')
            elif data.get('document'):
                raw=file.read()
                try:
                    _,cert,_=certificate_data(raw,password,data['document'])
                    self.certificate_values=(encrypt_text(base64.b64encode(raw).decode()),encrypt_text(password),cert.not_valid_after_utc)
                except FiscalError as exc:self.add_error('certificate',str(exc))
        elif password:self.add_error('certificate','Envie novamente o certificado para alterar a senha.')
        if self.instance.pk and self.instance.document!=data.get('document') and not file:
            self.add_error('certificate','Envie o certificado A1 do novo CNPJ emissor.')
        if data.get('enabled'):
            if not data.get('tax_confirmed'):self.add_error('tax_confirmed','Confirme os parâmetros fiscais com sua contabilidade.')
            if not file and not self.instance.certificate_encrypted:self.add_error('certificate','Cadastre um certificado A1 válido para ativar.')
            if not file and self.instance.certificate_expires_at and self.instance.certificate_expires_at<=timezone.now():self.add_error('certificate','O certificado venceu. Envie um novo certificado A1.')
            if data.get('environment')=='production' and not data.get('confirm_production'):self.add_error('confirm_production','Confirme a ativação em produção.')
        return data


class FiscalProfileForm(forms.ModelForm):
    document=forms.CharField(label="CPF/CNPJ",max_length=32)
    postal_code=forms.CharField(label="CEP",max_length=10)
    class Meta:
        model=TenantFiscalProfile
        fields=['document','legal_name','email','municipality_code','postal_code','street','number','district','complement']
    def clean_document(self):
        value=digits(self.cleaned_data['document'])
        if not valid_document(value):raise ValidationError('Informe CPF ou CNPJ válido.')
        return value
    def clean_postal_code(self):
        value=digits(self.cleaned_data['postal_code'])
        if len(value)!=8:raise ValidationError('Informe um CEP com 8 dígitos.')
        return value
    def clean_municipality_code(self):
        value=self.cleaned_data['municipality_code']
        if not value.isascii() or not value.isdigit() or len(value)!=7:raise ValidationError('Informe o código IBGE de 7 dígitos do município.')
        return value


@login_required
def settings_view(request):
    master_guard(request)
    config=PlatformFiscalSettings.objects.filter(pk=1).first() or PlatformFiscalSettings()
    form=FiscalSettingsForm(request.POST or None,request.FILES or None,instance=config)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            row=form.save(commit=False)
            if hasattr(form,'certificate_values'):row.certificate_encrypted,row.certificate_password_encrypted,row.certificate_expires_at=form.certificate_values
            row.save()
            append_audit(user=request.user,request=request,action='FISCAL_SETTINGS_UPDATED',entity_type='billing.PlatformFiscalSettings',entity_id=1,after={'enabled':row.enabled,'environment':row.environment,'certificate_replaced':hasattr(form,'certificate_values')})
        messages.success(request,'Configuração fiscal salva. Homologação não gera documento com validade fiscal.')
        return redirect('master-fiscal-settings')
    # Do not pass a model containing encrypted secrets into the template.
    return render(request,'master/fiscal_settings.html',{'form':form,'expires':config.certificate_expires_at,'has_certificate':bool(config.certificate_encrypted)})


@login_required
def center(request):
    master_guard(request)
    qs=FiscalDocumentRequest.objects.select_related('tenant','payment').order_by('-pk')
    state=request.GET.get('state','')
    if state in dict(FiscalDocumentRequest._meta.get_field('emission_state').choices):qs=qs.filter(emission_state=state)
    return render(request,'master/fiscal_center.html',{'page':Paginator(qs,30).get_page(request.GET.get('page')),'state':state,'states':FiscalDocumentRequest._meta.get_field('emission_state').choices})


@login_required
@require_POST
def retry(request,pk):
    master_guard(request)
    config=PlatformFiscalSettings.objects.filter(pk=1,enabled=True,tax_confirmed=True).first()
    if not config:
        messages.error(request,'Ative e configure a emissão fiscal antes de continuar.');return redirect('master-fiscal-settings')
    with transaction.atomic():
        row=get_object_or_404(FiscalDocumentRequest.objects.select_for_update(),pk=pk)
        if row.processing_until and row.processing_until>timezone.now():
            messages.info(request,'Esta nota já está em processamento.');return redirect('master-nfse-center')
        if row.status=='issued' and row.pdf_file:
            messages.info(request,'A nota já foi emitida.');return redirect('master-nfse-center')
        if row.fiscal_environment=='homologation' and row.emission_state=='authorized' and config.environment=='production':
            # Environment switch is explicit; preserve test history, not test files in customer downloads.
            for field in [row.pdf_file,row.xml_file]:
                if field.name:
                    storage,name=field.storage,field.name
                    transaction.on_commit(lambda storage=storage,name=name:storage.delete(name))
            row.pdf_file='';row.xml_file='';row.access_key='';row.invoice_number='';row.signed_dps_encrypted='';row.dps_id='';row.fiscal_environment='production'
        from .fiscal_automation import record
        record(row,'authorized' if row.access_key else 'queued');row.attempts=0;row.next_attempt_at=timezone.now();row.save()
        append_audit(request=request,user=request.user,tenant=row.tenant,action='NFSE_RETRY_QUEUED',entity_type='billing.FiscalDocumentRequest',entity_id=row.pk,after={'environment':config.environment})
    messages.success(request,'Nota colocada na fila. A mesma DPS será consultada antes de qualquer reenvio.')
    return redirect('master-nfse-center')


@login_required
def profile(request):
    if not request.user.tenant_id or request.user.role not in {'owner','manager','tenant-admin'}:raise PermissionDenied
    tenant=request.user.tenant
    row=TenantFiscalProfile.objects.filter(tenant=tenant).first()
    form=FiscalProfileForm(request.POST or None,instance=row,initial={'document':tenant.document,'legal_name':tenant.name,'email':tenant.email} if not row else None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            row=form.save(commit=False);row.tenant=tenant;row.save()
            # Missing customer data can be repaired without emitting synchronously during a form submission.
            FiscalDocumentRequest.objects.filter(tenant=tenant,emission_state='error',signed_dps_encrypted='').update(emission_state='queued',attempts=0,next_attempt_at=timezone.now())
            append_audit(request=request,user=request.user,tenant=tenant,action='FISCAL_PROFILE_UPDATED',entity_type='billing.TenantFiscalProfile',entity_id=row.pk)
        messages.success(request,'Dados fiscais salvos. As notas pendentes serão processadas pela fila.')
        return redirect('billing-subscription-status')
    return render(request,'billing/fiscal_profile.html',{'form':form})
