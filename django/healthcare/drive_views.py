import base64
import hashlib
import secrets
from urllib.parse import urlencode
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404,render,redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from core.crypto import encrypt_text,decrypt_text
from core.audit import append_audit
from tenants.models import Tenant
from .drive_models import ClinicalDriveConfiguration
from .drive_backup import google,create_folder,file_id,DriveBackupError,GOOGLE_TOKEN


class DriveForm(forms.Form):
    client_id=forms.CharField(label='Google OAuth Client ID',max_length=300)
    client_secret=forms.CharField(label='Client Secret (preencha para substituir)',max_length=600,required=False,widget=forms.PasswordInput(render_value=False))
    folder_id=forms.RegexField(label='ID da pasta (opcional; deixe vazio para criar uma pasta da empresa ao conectar)',regex=r'^[A-Za-z0-9_-]{5,200}$',required=False)
    enabled=forms.BooleanField(label='Ativar backup diário em PDF',required=False)
    hour=forms.IntegerField(label='Hora inicial do backup no fuso da clínica',min_value=0,max_value=23,initial=3)
    authorized=forms.BooleanField(label='Confirmo a autorização da empresa para enviar a cópia integral dos prontuários à conta Google selecionada',required=False)


def master(user):
    if not user.is_authenticated or not user.is_active or not user.is_superuser or not user.is_staff:
        raise PermissionDenied('Configuração restrita ao Master autorizado.')


@login_required
@never_cache
def configuration(request,pk):
    master(request.user);tenant=get_object_or_404(Tenant,pk=pk,archived_at__isnull=True,deleted_at__isnull=True)
    from billing.entitlements import is_healthcare_tenant
    if not is_healthcare_tenant(tenant):raise PermissionDenied('Backup clínico disponível apenas para empresas de saúde.')
    config,_=ClinicalDriveConfiguration.objects.get_or_create(tenant=tenant)
    form=DriveForm(request.POST or None,initial={'client_id':config.client_id,'folder_id':config.folder_id,'enabled':config.enabled,'hour':config.hour,'authorized':bool(config.authorized_at)})
    callback=request.build_absolute_uri(reverse('master-clinical-drive-callback'))
    if request.method=='POST':
        action=request.POST.get('action','save')
        try:
            if action=='run':
                if not config.enabled or not config.refresh_token_encrypted:raise ValidationError('Salve, conecte a conta e ative o backup antes de executar.')
                from .drive_tasks import enqueue_company
                count=enqueue_company(config.pk,True)
                messages.success(request,f'Verificação de {count} prontuários encaminhada à fila.')
                return redirect('master-clinical-drive',pk=pk)
            if action=='connect':
                if not config.client_id or not config.client_secret_encrypted:raise ValidationError('Salve primeiro o Client ID e o Client Secret do aplicativo Google.')
                state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
                request.session['clinical_drive_oauth']={'configuration':config.pk,'tenant':tenant.pk,'actor':request.user.pk,
                    'state':hashlib.sha256(state.encode()).hexdigest(),'verifier':verifier,'expires':(timezone.now()+timezone.timedelta(minutes=10)).timestamp()}
                params={'client_id':config.client_id,'redirect_uri':callback,'response_type':'code','scope':'openid email https://www.googleapis.com/auth/drive.file',
                    'access_type':'offline','prompt':'consent','state':state,'code_challenge_method':'S256',
                    'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
                return redirect('https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params))
            if action=='disconnect':
                config.enabled=False;config.refresh_token_encrypted='';config.account_email='';config.generation+=1;config.save()
                append_audit(tenant=tenant,user=request.user,request=request,action='clinical.drive.disconnected',entity_type='ClinicalDriveConfiguration',entity_id=config.pk)
                return redirect('master-clinical-drive',pk=pk)
            if form.is_valid():
                data=form.cleaned_data
                changed=config.client_id!=data['client_id'] or config.folder_id!=data['folder_id'] or bool(data['client_secret'])
                if data['enabled'] and (not data['authorized'] or not config.refresh_token_encrypted or changed):
                    raise ValidationError('Salve a configuração desativada, conecte a conta Google e confirme a autorização antes de ativar.')
                if not config.client_secret_encrypted and not data['client_secret']:raise ValidationError('Informe o Client Secret do aplicativo Google.')
                with transaction.atomic():
                    config=ClinicalDriveConfiguration.objects.select_for_update().get(pk=config.pk)
                    if changed:
                        config.enabled=False;config.generation+=1;config.refresh_token_encrypted='';config.account_email='';config.last_queued_day=None
                    config.client_id=data['client_id'];config.folder_id=data['folder_id'];config.hour=data['hour'];config.enabled=data['enabled']
                    if data['client_secret']:config.client_secret_encrypted=encrypt_text(data['client_secret'])
                    config.authorized_by=request.user if data['authorized'] else None
                    config.authorized_at=timezone.now() if data['authorized'] else None
                    config.save()
                    append_audit(tenant=tenant,user=request.user,request=request,action='clinical.drive.configured',entity_type='ClinicalDriveConfiguration',entity_id=config.pk,
                        after={'enabled':config.enabled,'generation':config.generation,'export_authorized':bool(config.authorized_at)})
                return redirect('master-clinical-drive',pk=pk)
        except (ValidationError,DriveBackupError) as exc:
            messages.error(request,' '.join(exc.messages) if isinstance(exc,ValidationError) else 'O Google não confirmou a operação. Confira a conexão.')
    return render(request,'master/clinical_drive.html',{'tenant':tenant,'config':config,'form':form,'callback':callback,
        'jobs':config.backups.filter(generation=config.generation).order_by('-updated_at')[:100]})


@login_required
@never_cache
def callback(request):
    master(request.user)
    pending=request.session.pop('clinical_drive_oauth',None)
    state=request.GET.get('state','')
    if (not pending or pending.get('actor')!=request.user.pk or pending.get('expires',0)<timezone.now().timestamp()
        or not constant_time_compare(pending.get('state',''),hashlib.sha256(state.encode()).hexdigest())):
        return HttpResponseBadRequest('Autorização expirada ou inválida. Inicie novamente pelo cadastro da empresa.')
    config=get_object_or_404(ClinicalDriveConfiguration,pk=pending['configuration'],tenant_id=pending['tenant'])
    if request.GET.get('error') or not request.GET.get('code'):
        messages.error(request,'A conta Google não foi autorizada. Nenhum prontuário foi enviado.')
        return redirect('master-clinical-drive',pk=config.tenant_id)
    try:
        response=google('POST',GOOGLE_TOKEN,data={'client_id':config.client_id,'client_secret':decrypt_text(config.client_secret_encrypted),
            'code':request.GET['code'],'redirect_uri':request.build_absolute_uri(reverse('master-clinical-drive-callback')),
            'grant_type':'authorization_code','code_verifier':pending['verifier']})
        tokens=response.json();access=tokens.get('access_token');refresh=tokens.get('refresh_token')
        if not access or not refresh:raise DriveBackupError('google_refresh_token_missing')
        info=google('GET','https://openidconnect.googleapis.com/v1/userinfo',headers={'Authorization':'Bearer '+access}).json()
        email=info.get('email','')
        if not email or not info.get('email_verified'):raise DriveBackupError('google_account_not_verified')
        folder=config.folder_id or create_folder(access,'ApPlanner - '+config.tenant.slug)
        response=google('GET','https://www.googleapis.com/drive/v3/files/'+file_id(folder),params={'fields':'id,mimeType,trashed,capabilities(canAddChildren)','supportsAllDrives':'true'},headers={'Authorization':'Bearer '+access})
        meta=response.json()
        if response.status_code!=200 or meta.get('mimeType')!='application/vnd.google-apps.folder' or meta.get('trashed') or not meta.get('capabilities',{}).get('canAddChildren'):
            raise DriveBackupError('google_folder_not_writable')
        with transaction.atomic():
            config=ClinicalDriveConfiguration.objects.select_for_update().get(pk=config.pk)
            if config.account_email and config.account_email!=email:config.generation+=1;config.enabled=False;config.authorized_at=None
            config.refresh_token_encrypted=encrypt_text(refresh);config.account_email=email;config.folder_id=folder;config.last_error_code='';config.save()
            append_audit(tenant=config.tenant,user=request.user,request=request,action='clinical.drive.connected',entity_type='ClinicalDriveConfiguration',entity_id=config.pk)
        messages.success(request,'Conta Google conectada. Confira a pasta e ative o backup diário com autorização da empresa.')
    except (DriveBackupError,ValueError,KeyError):
        messages.error(request,'Não foi possível concluir a conexão. Confira as credenciais, o endereço de retorno e a permissão da pasta.')
    return redirect('master-clinical-drive',pk=config.tenant_id)
