import json
from io import BytesIO
from xml.sax.saxutils import escape
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError,SuspiciousOperation
from django.db.models import Sum
from django.http import FileResponse,JsonResponse
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from billing.entitlements import require_module,module_enabled
from core.audit import append_audit
from core.crypto import decrypt_text
from scheduling.models import Customer,Professional
from .models import (MedicalRecordAccessLog,ClinicalRegistration,
                     ClinicalAttachment,ClinicalCareGrant,ClinicalFollowUp)
from .services import assert_clinical_access,clinical_records_for,read_record,create_record
from .clinical import (save_structured_record,grant_care,revoke_care,attach_document,read_document,
                       change_treatment_status,schedule_followup,consume_clinical_session)
from .clinic_forms import (RegistrationForm,StructuredClinicalForm,RectificationForm,AttachmentForm,
                           CareGrantForm,FollowUpForm,TreatmentStatusForm)


def numeric_id(value):
    if not str(value or "").isdigit():raise SuspiciousOperation("Identificador inválido.")
    return int(value)


def clinic(request):
    assert_clinical_access(request.user)
    tenant=request.user.tenant
    require_module(tenant,"medical_records")
    return tenant


def unpack(entry,user):
    text=read_record(entry=entry,user=user)
    try:data=json.loads(text)
    except (ValueError,TypeError):data={"content":text}
    return data if isinstance(data,dict) else {"content":text}


@login_required
@never_cache
def dashboard(request):
    user=request.user
    if not user.tenant_id or user.role not in {"owner","manager","tenant-admin","professional","healthcare"}:
        raise PermissionDenied
    tenant=user.tenant
    if not module_enabled(tenant,"medical_records"):
        # Keep the subscription gate: do not silently grant clinical modules.
        return render(request,"healthcare/clinical_setup.html",{
            "reason":"module","tenant":tenant,"clinical_access":False,
        })
    try:
        assert_clinical_access(user)
    except PermissionDenied:
        # The owner may configure the clinic but cannot read clinical records
        # until linked to an active, authorized clinical professional.
        if user.role not in {"owner","tenant-admin","manager"}:
            raise
        return render(request,"healthcare/clinical_setup.html",{
            "reason":"professional","tenant":tenant,"clinical_access":False,
        })
    records=clinical_records_for(user=user,tenant=tenant)
    return render(request,"healthcare/clinic_dashboard.html",{
        "patients":Customer.objects.filter(tenant=tenant,active=True).order_by("name"),
        "entries":records.select_related("customer","professional").order_by("-created_at")[:100],
        "followups":ClinicalFollowUp.objects.filter(entry__in=records,completed_at__isnull=True).select_related("entry__customer").order_by("due_at")[:100],
        "dentistry":module_enabled(tenant,"dentistry"),"physiotherapy":module_enabled(tenant,"physiotherapy"),
    })


@login_required
@never_cache
def registration(request):
    user=request.user
    if not user.tenant_id or user.role not in {"owner","tenant-admin","healthcare","professional"}:raise PermissionDenied
    pk=request.GET.get("professional") or request.POST.get("professional")
    qs=Professional.objects.filter(tenant_id=user.tenant_id,active=True)
    if user.role not in {"owner","tenant-admin"}:qs=qs.filter(user=user)
    professional=get_object_or_404(qs,pk=numeric_id(pk)) if pk else qs.filter(user=user).first()
    instance=ClinicalRegistration.objects.filter(professional=professional).first() if professional else None
    form=RegistrationForm(request.POST or None,user=user,instance=instance,initial={"professional":professional})
    if request.method=="POST" and form.is_valid():
        row=form.save()
        append_audit(tenant=user.tenant,user=user,request=request,action="clinical.registration.saved",entity_type="ClinicalRegistration",entity_id=row.pk)
        messages.success(request,"Identificação profissional salva. Verifique o registro no conselho competente.")
        return redirect("clinical-registration")
    return render(request,"healthcare/clinic_form.html",{"form":form,"title":"Identificação profissional"})


@login_required
@never_cache
def structured_record(request,kind):
    tenant=clinic(request);require_module(tenant,"dentistry")
    if kind not in {"periodontal","treatment_plan"}:raise PermissionDenied
    title="Periodontograma" if kind=="periodontal" else "Plano de tratamento e orçamento"
    form=StructuredClinicalForm(request.POST or None,user=request.user,kind=kind)
    if request.method=="POST" and form.is_valid():
        data=form.cleaned_data
        if not hasattr(data["professional"],"clinical_registration") or data["professional"].clinical_registration.council!="CRO":
            form.add_error("professional","Cadastre CRO/UF antes de registrar o atendimento.")
        else:
            try:
                entry=save_structured_record(tenant=tenant,customer=data["customer"],professional=data["professional"],
                    user=request.user,kind=kind,data={**data["payload"],"notes":data["notes"]},title=title)
                return redirect("clinical-record",pk=entry.pk)
            except (PermissionDenied,ValidationError) as exc:form.add_error(None,str(exc))
    return render(request,"healthcare/structured_form.html",{"form":form,"title":title,"kind":kind})


@login_required
@never_cache
def record_detail(request,pk):
    tenant=clinic(request)
    entry=get_object_or_404(clinical_records_for(user=request.user,tenant=tenant),pk=pk)
    payload=unpack(entry,request.user)
    owner=entry.professional.user_id==request.user.pk
    forms={"correct":RectificationForm(),"attach":AttachmentForm(),"grant":CareGrantForm(user=request.user),
           "followup":FollowUpForm(),"status":TreatmentStatusForm()}
    plan=getattr(entry,"treatment_budget",None)
    if request.method=="POST":
        if not owner:raise PermissionDenied
        action=request.POST.get("action")
        classes={"correct":RectificationForm,"attach":AttachmentForm,"grant":CareGrantForm,"followup":FollowUpForm,"status":TreatmentStatusForm}
        if action=="package":
            from engagement.models import CustomerPackage
            package=get_object_or_404(CustomerPackage,pk=numeric_id(request.POST.get("package")),tenant=tenant,customer=entry.customer)
            try:consume_clinical_session(entry=entry,customer_package=package,user=request.user)
            except (ValidationError,PermissionDenied) as exc:messages.error(request,str(exc))
            return redirect("clinical-record",pk=entry.pk)
        if action=="revoke":
            grant=get_object_or_404(ClinicalCareGrant,pk=numeric_id(request.POST.get("grant")),tenant=tenant,customer=entry.customer,source_professional=entry.professional)
            revoke_care(grant=grant,user=request.user)
            return redirect("clinical-record",pk=entry.pk)
        if action=="complete-followup":
            row=get_object_or_404(ClinicalFollowUp,pk=numeric_id(request.POST.get("followup")),entry=entry)
            row.completed_at=timezone.now();row.completed_by=request.user;row.save(update_fields=["completed_at","completed_by"])
            append_audit(tenant=tenant,user=request.user,action="clinical.followup.completed",entity_type="ClinicalFollowUp",entity_id=row.pk)
            return redirect("clinical-record",pk=entry.pk)
        if action not in classes:raise PermissionDenied
        form=classes[action](request.POST,request.FILES,**({"user":request.user} if action=="grant" else {})) if action=="attach" else classes[action](request.POST,**({"user":request.user} if action=="grant" else {}))
        forms[action]=form
        if form.is_valid():
            d=form.cleaned_data
            try:
                if action=="correct":
                    new=create_record(tenant=tenant,customer=entry.customer,professional=entry.professional,user=request.user,
                        appointment=entry.appointment,record_type=entry.record_type,title="Retificação — "+entry.title[:160],
                        content=json.dumps({"kind":"clinical_correction","original_entry":entry.pk,"correction":d["correction"]},ensure_ascii=False),
                        supersedes=entry,correction_reason=d["reason"])
                    return redirect("clinical-record",pk=new.pk)
                if action=="attach":attach_document(entry=entry,user=request.user,**d)
                if action=="grant":grant_care(entry=entry,user=request.user,**d)
                if action=="followup":schedule_followup(entry=entry,user=request.user,**d)
                if action=="status":
                    if not plan:raise ValidationError("Este registro não é um plano de tratamento.")
                    change_treatment_status(plan=plan,user=request.user,**d)
                return redirect("clinical-record",pk=entry.pk)
            except (ValidationError,PermissionDenied) as exc:form.add_error(None,str(exc))
    fields=[]
    labels={"anamnesis":"Anamnese","findings":"Achados","procedures":"Procedimentos e evolução","treatment_plan":"Plano terapêutico","notes":"Observações","content":"Conteúdo","correction":"Retificação","status":"Situação do tratamento","before":"Situação anterior","plan_id":"Plano de tratamento","patient_approval":"Aprovação do paciente"}
    for key,label in labels.items():
        if payload.get(key):fields.append({"label":label,"value":payload[key]})
    from .forms import DENTAL_DETAILS
    fields.extend({"label":DENTAL_DETAILS[key],"value":value} for key,value in payload.get("clinical_details",{}).items() if key in DENTAL_DETAILS and value)
    sections=payload.get("sections",{})
    if isinstance(sections,dict):
        from core.portal import PhysiotherapyRecordForm
        f=PhysiotherapyRecordForm()
        fields.extend({"label":f.fields[key].label,"value":value} for key,value in sections.items() if key in f.fields and isinstance(value,(str,int,float)) and value!="")
    return render(request,"healthcare/clinical_record.html",{"entry":entry,"correction_reason":decrypt_text(entry.correction_reason_encrypted) if entry.correction_reason_encrypted else "","payload":payload,"fields":fields,"forms":forms,"owner":owner,"plan":plan,
        "attachments":entry.attachments.all(),"grants":ClinicalCareGrant.objects.filter(tenant=tenant,customer=entry.customer,source_professional=entry.professional,revoked_at__isnull=True).select_related("grantee") if owner else [],
        "chart_json":json.dumps(payload.get("odontogram",{})),"followups":entry.followups.all(),
        "packages":entry.customer.packages.filter(status="active") if owner else []})


@login_required
@never_cache
def attachment_download(request,pk):
    clinic(request)
    document=get_object_or_404(ClinicalAttachment.objects.select_related("entry"),pk=pk,entry__tenant_id=request.user.tenant_id)
    raw,filename=read_document(document=document,user=request.user)
    response=FileResponse(BytesIO(raw),as_attachment=True,filename=filename,content_type=document.mime_type)
    response["X-Content-Type-Options"]="nosniff";response["Content-Security-Policy"]="default-src 'none'; sandbox"
    return response


@login_required
@never_cache
def patient(request,pk):
    tenant=clinic(request);customer=get_object_or_404(Customer,pk=pk,tenant=tenant)
    entries=clinical_records_for(user=request.user,tenant=tenant).filter(customer=customer).order_by("created_at","pk")
    history=[];physio=[]
    for entry in entries:
        data=unpack(entry,request.user)
        history.append({"entry":entry,"kind":data.get("kind",""),"pain":data.get("sections",{}).get("pain_level")})
        if data.get("schema")=="applanner.physiotherapy.v1":physio.append({"id":entry.pk,"date":entry.created_at.isoformat(),"regions":data.get("sections",{}).get("body_findings",{}),"pain":data.get("sections",{}).get("pain_level")})
    from engagement.models import CustomerPackage
    packages=[]
    for pack in CustomerPackage.objects.filter(tenant=tenant,customer=customer).select_related("package"):
        purchased=pack.package.items.aggregate(n=Sum("credits"))["n"] or 0
        used=pack.usages.aggregate(n=Sum("credits_used"))["n"] or 0
        packages.append({"name":pack.package.name,"purchased":purchased,"used":used,"remaining":max(0,purchased-used),"status":pack.get_status_display()})
    from core.portal import PHYSIO_BODY_AREAS
    return render(request,"healthcare/clinical_patient.html",{"patient":customer,"history":history,"physio":physio,"packages":packages,"body_labels":dict(PHYSIO_BODY_AREAS)})


@login_required
@never_cache
def export_patient(request,pk,kind):
    tenant=clinic(request);customer=get_object_or_404(Customer,pk=pk,tenant=tenant)
    entries=clinical_records_for(user=request.user,tenant=tenant).filter(customer=customer).order_by("created_at","pk")
    rows=[]
    for entry in entries:
        rows.append({"id":entry.pk,"date":entry.created_at.isoformat(),"professional":entry.professional_snapshot,
            "title":entry.title,"supersedes":entry.supersedes_id,"correction_reason":decrypt_text(entry.correction_reason_encrypted) if entry.correction_reason_encrypted else "","data":unpack(entry,request.user),
            "documents":[{"id":x.pk,"kind":x.kind,"sha256":x.sha256,"size":x.size} for x in entry.attachments.all()]})
        MedicalRecordAccessLog.objects.create(tenant=tenant,entry=entry,user=request.user,action="export")
    data={"patient":{"id":customer.pk,"name":customer.name,"birth_date":str(customer.birth_date or "")},"exported_at":timezone.now().isoformat(),"records":rows}
    append_audit(tenant=tenant,user=request.user,action="clinical.patient.exported",entity_type="Customer",entity_id=customer.pk,after={"format":kind,"records":len(rows)})
    if kind=="json":
        response=JsonResponse(data,json_dumps_params={"ensure_ascii":False});response["Content-Disposition"]=f'attachment; filename="prontuario-{customer.pk}.json"';return response
    if kind!="pdf":raise PermissionDenied
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    output=BytesIO();styles=getSampleStyleSheet();story=[]
    story.append(Paragraph("Prontuário clínico — "+escape(customer.name),styles["Title"]))
    story.append(Paragraph("Exportação restrita aos registros autorizados. Documentos assinados originais são fornecidos separadamente.",styles["Normal"]))
    def walk(value,prefix=""):
        if isinstance(value,dict):
            for key,item in value.items():walk(item,prefix+str(key).replace("_"," ")+": ")
        elif isinstance(value,list):
            for item in value:walk(item,prefix)
        else:story.append(Paragraph(escape(prefix+str(value or "—")),styles["Normal"]))
    for row in rows:
        story.append(Spacer(1,14));story.append(Paragraph(escape(row["title"]+" · "+row["date"]),styles["Heading2"]))
        walk(row["professional"]);walk(row["data"])
        if row["documents"]:
            table=Table([["Documento","SHA-256"]]+[[str(doc["id"]),doc["sha256"][:32]+"…"] for doc in row["documents"]],colWidths=[100,350])
            table.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.5,colors.lightgrey)]));story.append(table)
    SimpleDocTemplate(output).build(story)
    return FileResponse(BytesIO(output.getvalue()),as_attachment=True,filename=f"prontuario-{customer.pk}.pdf",content_type="application/pdf")
