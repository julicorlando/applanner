import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404,render,redirect
from django.views.decorators.cache import never_cache
from cryptography.fernet import Fernet
from django.conf import settings
from billing.entitlements import require_module
from core.audit import append_audit
from core.crypto import encrypt_text,decrypt_text
from scheduling.models import Professional,Customer
from .document_models import ClinicalDocumentTemplate,ClinicalIssuedDocument,ProfessionalSignature,KINDS
from .document_services import own_professional,save_signature,finalize_document,text_from_template,default_body,DEFAULT_TITLES
from .patient_scope import patients_for


def staff(request):
    user=request.user
    if not user.is_active or user.is_superuser or not user.tenant_id or user.role not in {'owner','tenant-admin','manager','professional','healthcare','reception'}:
        raise PermissionDenied
    from billing.entitlements import is_healthcare_tenant
    if not is_healthcare_tenant(user.tenant) or user.tenant.archived_at or user.tenant.deleted_at:raise PermissionDenied
    require_module(user.tenant,'medical_records')
    return user.tenant


class SignatureForm(forms.Form):
    upload=forms.FileField(label='Assinatura em PNG/JPG (até 2 MB)',required=False)
    authorization=forms.BooleanField(label='Sou o profissional responsável e autorizo cadastrar minha assinatura',required=True)


@login_required
@never_cache
def signature(request):
    profile=own_professional(request.user)
    form=SignatureForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        try:
            remove=request.POST.get('action')=='remove'
            if not remove and not form.cleaned_data['upload']:raise ValidationError('Selecione uma imagem.')
            save_signature(request.user,form.cleaned_data['upload'],remove)
            messages.success(request,'Assinatura removida.' if remove else 'Assinatura cadastrada para revisão em cada emissão.')
            return redirect('clinical-signature')
        except ValidationError as exc:form.add_error(None,exc)
    return render(request,'healthcare/signature.html',{'form':form,'profile':profile,
        'has_signature':ProfessionalSignature.objects.filter(professional=profile).exclude(sha256='').exists()})


@login_required
@never_cache
def signature_image(request):
    profile=own_professional(request.user)
    row=get_object_or_404(ProfessionalSignature,professional=profile)
    if not row.image_encrypted:return HttpResponse(status=404)
    append_audit(tenant=request.user.tenant,user=request.user,request=request,action='clinical.signature.preview',entity_type='ProfessionalSignature',entity_id=row.pk)
    return HttpResponse(Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(bytes(row.image_encrypted)),content_type='image/png',headers={'X-Content-Type-Options':'nosniff'})


class TemplateForm(forms.Form):
    name=forms.CharField(label='Nome do modelo',max_length=100)
    kind=forms.ChoiceField(label='Tipo',choices=KINDS)
    text=forms.CharField(label='Texto padrão',max_length=20000,widget=forms.Textarea(attrs={'rows':8}))
    shared=forms.BooleanField(label='Disponível para toda a clínica',required=False)


def available_templates(user):
    return ClinicalDocumentTemplate.objects.filter(tenant_id=user.tenant_id,active=True).filter(Q(professional__isnull=True)|Q(professional__user=user))


@login_required
@never_cache
def templates(request):
    tenant=staff(request)
    if request.user.role=='reception':raise PermissionDenied
    admin=request.user.role in {'owner','manager','tenant-admin'}
    form=TemplateForm(request.POST or None)
    if request.method=='POST':
        if request.POST.get('action')=='disable':
            row=get_object_or_404(available_templates(request.user),pk=request.POST.get('template'))
            if row.professional_id and row.professional.user_id!=request.user.pk:raise PermissionDenied
            if not row.professional_id and not admin:raise PermissionDenied
            row.active=False;row.save(update_fields=['active','updated_at'])
            append_audit(tenant=tenant,user=request.user,request=request,action='clinical.document_template.disabled',entity_type='ClinicalDocumentTemplate',entity_id=row.pk)
            return redirect('clinical-document-templates')
        if form.is_valid():
            shared=form.cleaned_data['shared']
            if shared and not admin:raise PermissionDenied
            profile=None if shared else own_professional(request.user)
            row=ClinicalDocumentTemplate.objects.create(tenant=tenant,professional=profile,name=form.cleaned_data['name'],kind=form.cleaned_data['kind'],
                text_encrypted=encrypt_text(form.cleaned_data['text']),created_by=request.user)
            append_audit(tenant=tenant,user=request.user,request=request,action='clinical.document_template.created',entity_type='ClinicalDocumentTemplate',entity_id=row.pk)
            return redirect('clinical-document-templates')
    return render(request,'healthcare/document_templates.html',{'form':form,'templates':available_templates(request.user),'admin':admin})


class PrepareForm(forms.Form):
    customer=forms.ModelChoiceField(label='Paciente',queryset=Customer.objects.none())
    professional=forms.ModelChoiceField(label='Profissional que revisará e emitirá',queryset=Professional.objects.none())
    template=forms.ModelChoiceField(label='Modelo (opcional)',queryset=ClinicalDocumentTemplate.objects.none(),required=False)
    kind=forms.ChoiceField(label='Tipo',choices=KINDS)
    title=forms.CharField(label='Título',max_length=150)
    body=forms.CharField(label='Texto do documento',required=False,max_length=20000,widget=forms.Textarea(attrs={'rows':12}),
        help_text='Linhas no formato "Rótulo: valor" saem com o rótulo em negrito; inicie a linha com ## para um subtítulo.')
    request_id=forms.UUIDField(widget=forms.HiddenInput)
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        reception=user.role=='reception'
        self.fields['customer'].queryset=patients_for(user,administrative=reception).filter(active=True)
        self.fields['professional'].queryset=Professional.objects.filter(tenant_id=user.tenant_id,active=True,user__isnull=False)
        if not reception:self.fields['professional'].queryset=self.fields['professional'].queryset.filter(user=user)
        self.fields['template'].queryset=available_templates(user)


@login_required
@never_cache
def documents(request):
    tenant=staff(request);reception=request.user.role=='reception'
    initial={'request_id':uuid.uuid4(),'customer':request.GET.get('customer')}
    kind=request.GET.get('kind')
    patient=None
    if str(request.GET.get('customer') or '').isdigit():
        patient=patients_for(request.user,administrative=reception).filter(pk=int(request.GET['customer']),active=True).first()
    if kind in DEFAULT_TITLES and request.method=='GET':
        initial.update(kind=kind,title=DEFAULT_TITLES[kind])
        if patient and not reception:
            try:
                profile=own_professional(request.user)
            except PermissionDenied:
                profile=None
            if profile:
                initial.update(professional=profile.pk,body=default_body(kind=kind,user=request.user,patient=patient,professional=profile))
    form=PrepareForm(request.POST or None,user=request.user,initial=initial)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data;profile=data['professional'];patient=data['customer'];template=data['template']
        if template and template.professional_id and template.professional_id!=profile.pk:raise PermissionDenied
        body=data['body'] or (text_from_template(template,patient,profile,tenant) if template else '')
        if not body.strip():form.add_error('body','Digite o texto ou selecione um modelo.')
        else:
            with transaction.atomic():
                existing=ClinicalIssuedDocument.objects.filter(request_id=data['request_id']).first()
                if existing:
                    if (existing.tenant_id!=tenant.pk or existing.created_by_id!=request.user.pk or existing.customer_id!=patient.pk or existing.professional_id!=profile.pk
                        or existing.title!=data['title'] or decrypt_text(existing.body_encrypted)!=body or existing.kind!=(template.kind if template else data['kind'])):
                        raise PermissionDenied
                    row=existing
                else:
                    row=ClinicalIssuedDocument.objects.create(tenant=tenant,customer=patient,professional=profile,template=template,
                        kind=template.kind if template else data['kind'],title=data['title'],body_encrypted=encrypt_text(body),created_by=request.user,request_id=data['request_id'])
                    append_audit(tenant=tenant,user=request.user,request=request,action='clinical.document.prepared',entity_type='ClinicalIssuedDocument',entity_id=row.pk)
            return redirect('clinical-document-detail',pk=row.pk)
    rows=ClinicalIssuedDocument.objects.filter(tenant=tenant)
    rows=rows.filter(created_by=request.user) if reception else rows.filter(professional__user=request.user,professional__active=True)
    if patient:rows=rows.filter(customer=patient)
    return render(request,'healthcare/documents.html',{'form':form,'rows':rows.order_by('-created_at')[:100],'reception':reception,
        'patient':patient,'kinds':KINDS,'selected_kind':kind if kind in DEFAULT_TITLES else '','back_url':_record_url(tenant,patient) if patient else ''})


def _record_url(tenant,patient):
    from django.urls import reverse
    from billing.entitlements import module_enabled
    from .navigation import dental_workspace
    if dental_workspace(tenant) and module_enabled(tenant,'dentistry'):
        return reverse('dental-assessments')+f'?customer={patient.pk}'
    return reverse('clinical-patient',args=[patient.pk])


class ReviewForm(forms.Form):
    title=forms.CharField(label='Título',max_length=150)
    body=forms.CharField(label='Texto revisado',max_length=20000,widget=forms.Textarea(attrs={'rows':12}))
    version=forms.IntegerField(widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='Revisei o conteúdo e confirmo a emissão com minha identificação e assinatura cadastrada',required=False)


@login_required
@never_cache
def detail(request,pk):
    tenant=staff(request);reception=request.user.role=='reception'
    rows=ClinicalIssuedDocument.objects.filter(tenant=tenant)
    rows=rows.filter(created_by=request.user,status='draft') if reception else rows.filter(professional__user=request.user,professional__active=True)
    row=get_object_or_404(rows,pk=pk)
    if request.method=='POST' and row.status!='draft':return HttpResponse('O documento emitido foi preservado. Emita outro para corrigir.',status=409)
    form=ReviewForm(request.POST or None,initial={'title':row.title,'body':decrypt_text(row.body_encrypted),'version':row.version})
    if request.method=='POST' and form.is_valid():
        try:
            data=form.cleaned_data
            if request.POST.get('action')=='finalize':
                if reception:raise PermissionDenied
                finalize_document(user=request.user,document=row,base_url=request.build_absolute_uri('/'),**data)
            elif request.POST.get('action')=='draft':
                with transaction.atomic():
                    current=ClinicalIssuedDocument.objects.select_for_update().get(pk=row.pk,status='draft')
                    if data['version']!=current.version:raise ValidationError('O rascunho mudou; atualize a página.')
                    current.body_encrypted=encrypt_text(data['body']);current.title=data['title'];current.version+=1;current.save()
            else:raise PermissionDenied
            return redirect('clinical-document-detail',pk=row.pk)
        except ValidationError as exc:form.add_error(None,exc)
    append_audit(tenant=tenant,user=request.user,request=request,action='clinical.document.viewed',entity_type='ClinicalIssuedDocument',entity_id=row.pk)
    from .document_services import verification_url
    return render(request,'healthcare/document_detail.html',{'row':row,'form':form,'reception':reception,
        'validation_url':verification_url(row.verification_code,request.build_absolute_uri('/')) if row.verification_code else '',
        'validations':row.validations.all()[:50] if not reception else []})


@login_required
@never_cache
def pdf(request,pk):
    profile=own_professional(request.user)
    row=get_object_or_404(ClinicalIssuedDocument,pk=pk,tenant_id=request.user.tenant_id,professional=profile,status='finalized')
    raw=Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(bytes(row.pdf_encrypted))
    append_audit(tenant=request.user.tenant,user=request.user,request=request,action='clinical.document.pdf.exported',entity_type='ClinicalIssuedDocument',entity_id=row.pk)
    return HttpResponse(raw,content_type='application/pdf',headers={'Content-Disposition':f'inline; filename="documento-{row.pk}.pdf"','X-Content-Type-Options':'nosniff'})
