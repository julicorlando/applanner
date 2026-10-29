"""Clinical workflows: encrypted records are the sole source of clinical facts."""
import hashlib
import json
from decimal import Decimal,InvalidOperation
from io import BytesIO
from pathlib import Path
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from PIL import Image,UnidentifiedImageError
from core.audit import append_audit
from core.crypto import encrypt_text,decrypt_text
from .dentistry import ALL_TEETH
from .models import (ClinicalAttachment,ClinicalCareGrant,ClinicalTreatmentPlan,
                     ClinicalFollowUp,MedicalRecordAccessLog)
from .services import create_record,read_record,assert_clinical_access

SITES=("MV","V","DV","ML","L","DL")


def periodontal_chart(value):
    if not isinstance(value,dict) or not value or any(key not in ALL_TEETH for key in value):
        raise ValidationError("Dentes FDI inválidos no periodontograma.")
    result={}
    for tooth,item in value.items():
        if not isinstance(item,dict) or isinstance(item.get("mobility",0),bool) or item.get("mobility",0) not in range(4):
            raise ValidationError("Mobilidade deve estar entre 0 e 3.")
        sites=item.get("sites",{})
        if not isinstance(sites,dict) or any(key not in SITES for key in sites):
            raise ValidationError("Sítios periodontais inválidos.")
        cleaned={}
        for site,data in sites.items():
            if not isinstance(data,dict):raise ValidationError("Sondagem inválida.")
            for field,low,high in (("probing",0,20),("recession",-10,20)):
                number=data.get(field,0)
                if isinstance(number,bool) or not isinstance(number,(int,float)) or not low<=number<=high:
                    raise ValidationError("Medidas periodontais fora dos limites do formulário.")
            if not isinstance(data.get("bleeding",False),bool):raise ValidationError("Sangramento inválido.")
            cleaned[site]={key:data.get(key,False if key=="bleeding" else 0) for key in ("probing","recession","bleeding")}
        result[tooth]={"mobility":item.get("mobility",0),"sites":cleaned}
    return result


def treatment_lines(lines):
    if not isinstance(lines,list) or not 1<=len(lines)<=100:
        raise ValidationError("Informe entre 1 e 100 itens no plano.")
    clean=[];total=Decimal("0.00")
    for item in lines:
        if not isinstance(item,dict):raise ValidationError("Item inválido.")
        tooth=item.get("tooth","");label=item.get("procedure","")
        if (tooth and tooth not in ALL_TEETH) or not isinstance(label,str) or not 1<=len(label.strip())<=200:
            raise ValidationError("Informe dente FDI válido e procedimento por item.")
        try:price=Decimal(str(item.get("price"))).quantize(Decimal("0.01"))
        except (InvalidOperation,ValueError,TypeError):raise ValidationError("Valor de procedimento inválido.")
        quantity=item.get("quantity",1)
        if not price.is_finite() or not 0<=price<=Decimal("999999.99") or isinstance(quantity,bool) or not isinstance(quantity,int) or not 1<=quantity<=99:
            raise ValidationError("Valor ou quantidade de procedimento inválido.")
        total+=price*quantity
        clean.append({"tooth":tooth,"procedure":label.strip(),"quantity":quantity,"price":str(price)})
    if total>Decimal("9999999999.99"):raise ValidationError("Orçamento excede o limite permitido.")
    return clean,total


@transaction.atomic
def save_structured_record(*,tenant,customer,professional,user,kind,data,title,ip=""):
    if kind=="periodontal":data={"chart":periodontal_chart(data.get("chart")),"notes":str(data.get("notes",""))[:10000]}
    elif kind=="treatment_plan":
        lines,total=treatment_lines(data.get("lines"))
        data={"lines":lines,"total":str(total),"notes":str(data.get("notes",""))[:10000]}
    else:raise ValidationError("Tipo de documento inválido.")
    entry=create_record(tenant=tenant,customer=customer,professional=professional,user=user,
        title=title,record_type="procedure",content=json.dumps({"kind":kind,"schema":1,**data},ensure_ascii=False),ip=ip)
    if kind=="treatment_plan":ClinicalTreatmentPlan.objects.create(entry=entry,total=total)
    return entry


@transaction.atomic
def grant_care(*,entry,grantee,user,reason,ip=""):
    read_record(entry=entry,user=user,ip=ip)
    if entry.professional.user_id!=user.pk or grantee.tenant_id!=entry.tenant_id or not grantee.active or not grantee.user_id:
        raise PermissionDenied("Somente o responsável pelo registro pode autorizar outro profissional da clínica.")
    if not reason.strip() or len(reason)>2000:raise ValidationError("Informe justificativa de até 2000 caracteres.")
    grant=ClinicalCareGrant.objects.create(tenant=entry.tenant,customer=entry.customer,
        source_professional=entry.professional,grantee=grantee,granted_by=user,justification_encrypted=encrypt_text(reason))
    append_audit(tenant=entry.tenant,user=user,action="clinical.care.granted",entity_type="ClinicalCareGrant",entity_id=grant.pk,
        after={"entry_id":entry.pk,"grantee_id":grantee.pk})
    return grant


@transaction.atomic
def revoke_care(*,grant,user):
    assert_clinical_access(user)
    grant=ClinicalCareGrant.objects.select_for_update().get(pk=grant.pk)
    if grant.tenant_id!=user.tenant_id or grant.source_professional.user_id!=user.pk:
        raise PermissionDenied("A autorização pertence a outro profissional.")
    if not grant.revoked_at:
        grant.revoked_at=timezone.now();grant.revoked_by=user
        grant.save(update_fields=["revoked_at","revoked_by"])
        append_audit(tenant=grant.tenant,user=user,action="clinical.care.revoked",entity_type="ClinicalCareGrant",entity_id=grant.pk)
    return grant


def _pdf_content(raw):
    from pypdf import PdfReader
    try:
        reader=PdfReader(BytesIO(raw),strict=True)
        if reader.is_encrypted or not 1<=len(reader.pages)<=300:raise ValueError()
        from pypdf.generic import DictionaryObject,ArrayObject,IndirectObject
        visited=set();stack=[reader.trailer["/Root"]];count=0
        while stack:
            item=stack.pop();count+=1
            if count>100000:raise ValueError()
            if isinstance(item,IndirectObject):
                key=(item.idnum,item.generation)
                if key in visited:continue
                visited.add(key);item=item.get_object()
            if isinstance(item,DictionaryObject):
                if any(k in item for k in ("/JS","/JavaScript","/Launch","/EmbeddedFiles","/AA","/OpenAction","/RichMedia","/XFA","/URI")):
                    raise ValueError()
                if item.get("/S") in ("/JavaScript","/Launch","/URI","/GoToR","/SubmitForm","/ImportData"):raise ValueError()
                if "/AcroForm" in item:
                    acro=item["/AcroForm"]
                    for field in acro.get("/Fields",[]):
                        if field.get_object().get("/FT")!="/Sig":raise ValueError()
                stack.extend(item.values())
            elif isinstance(item,ArrayObject):stack.extend(item)
    except Exception as exc:raise ValidationError("PDF inválido, criptografado ou com conteúdo ativo. Envie PDF estático.") from exc
    return raw


@transaction.atomic
def attach_document(*,entry,user,upload,kind,attestation=False,ip=""):
    read_record(entry=entry,user=user,ip=ip)
    if entry.professional.user_id!=user.pk:raise PermissionDenied("Somente o responsável pode anexar documentos.")
    if kind not in ClinicalAttachment.Kind.values or upload.size>10*1024*1024:
        raise ValidationError("Documento deve ter até 10 MB e tipo válido.")
    if kind==ClinicalAttachment.Kind.CONSENT and not attestation:
        raise ValidationError("Confirme a ciência/autorização e a autenticidade do documento anexado.")
    raw=upload.read(10*1024*1024+1)
    if len(raw)>10*1024*1024:raise ValidationError("Arquivo muito grande.")
    if raw.startswith(b"%PDF-"):
        raw=_pdf_content(raw);mime="application/pdf";suffix=".pdf"
    else:
        try:
            with Image.open(BytesIO(raw)) as picture:
                if picture.width*picture.height>20000000 or picture.format not in {"PNG","JPEG","TIFF"}:raise ValueError()
                image_format=picture.format;picture.load()
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError) as exc:
            raise ValidationError("Envie PNG, JPEG, TIFF ou PDF estático válido.") from exc
        mime,suffix={"PNG":("image/png",".png"),"JPEG":("image/jpeg",".jpg"),"TIFF":("image/tiff",".tiff")}[image_format]
        # Preserve diagnostic/source evidence without lossy resizing or metadata rewriting.
    filename=Path(upload.name).stem[:100]+suffix
    cipher=Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).encrypt(raw)
    document=ClinicalAttachment.objects.create(entry=entry,kind=kind,filename_encrypted=encrypt_text(filename),
        content_encrypted=cipher,mime_type=mime,sha256=hashlib.sha256(raw).hexdigest(),size=len(raw),
        attestation=attestation,uploaded_by=user)
    append_audit(tenant=entry.tenant,user=user,action="clinical.document.attached",entity_type="ClinicalAttachment",entity_id=document.pk,
        after={"entry_id":entry.pk,"sha256":document.sha256,"kind":kind})
    return document


def read_document(*,document,user,ip=""):
    read_record(entry=document.entry,user=user,ip=ip)
    MedicalRecordAccessLog.objects.create(tenant=document.entry.tenant,entry=document.entry,user=user,action="export")
    return (Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(bytes(document.content_encrypted)),decrypt_text(document.filename_encrypted))


@transaction.atomic
def change_treatment_status(*,plan,user,status,attestation=False):
    plan=ClinicalTreatmentPlan.objects.select_for_update().select_related("entry").get(pk=plan.pk)
    read_record(entry=plan.entry,user=user)
    if plan.entry.professional.user_id!=user.pk:raise PermissionDenied("Somente o profissional responsável pode atualizar o tratamento.")
    transitions={"proposed":{"accepted","declined"},"accepted":{"in_progress","completed"},"in_progress":{"completed"}}
    if status==plan.status:return plan
    if status not in transitions.get(plan.status,set()):raise ValidationError("Transição de tratamento inválida.")
    if status=="accepted" and not attestation:raise ValidationError("Confirme a aprovação do paciente.")
    before=plan.status;plan.status=status;plan.save(update_fields=["status","updated_at"])
    # Preserve each status/consent as an encrypted, chronological clinical event.
    create_record(tenant=plan.entry.tenant,customer=plan.entry.customer,professional=plan.entry.professional,
        user=user,title="Andamento do plano de tratamento",record_type="follow_up",
        content=json.dumps({"kind":"treatment_status","plan_id":plan.pk,"before":before,"status":status,"patient_approval":attestation}))
    append_audit(tenant=plan.entry.tenant,user=user,action="clinical.treatment.status",entity_type="ClinicalTreatmentPlan",entity_id=plan.pk,
                 before={"status":before},after={"status":status})
    if status=="accepted":
        from finance.models import FinancialTransaction
        FinancialTransaction.objects.get_or_create(tenant=plan.entry.tenant,idempotency_key=f"clinical-plan-{plan.pk}",
            defaults={"type":"income","description":f"Plano de tratamento #{plan.pk}","amount":plan.total,
                      "source_type":"clinical-plan","source_id":plan.pk,"status":"pending"})
    return plan


def schedule_followup(*,entry,user,due_at,note):
    read_record(entry=entry,user=user)
    if entry.professional.user_id!=user.pk:raise PermissionDenied("Retorno pertence a outro profissional.")
    if due_at<timezone.localdate():raise ValidationError("Data de retorno deve ser hoje ou futura.")
    return ClinicalFollowUp.objects.create(entry=entry,due_at=due_at,note_encrypted=encrypt_text(note[:2000]))


@transaction.atomic
def consume_clinical_session(*,entry,customer_package,user):
    from engagement.models import CustomerPackage
    from engagement.services import consume_package_credit
    from .models import ClinicalSessionUsage
    read_record(entry=entry,user=user)
    if entry.professional.user_id!=user.pk or entry.record_type!="physio_evolution" or not entry.appointment_id or entry.appointment.status!="completed":
        raise ValidationError("Consumo exige evolução fisioterapêutica vinculada ao agendamento do profissional.")
    package=CustomerPackage.objects.select_for_update().get(pk=customer_package.pk)
    if package.tenant_id!=entry.tenant_id or package.customer_id!=entry.customer_id:
        raise PermissionDenied("Pacote de outro paciente ou clínica.")
    existing=ClinicalSessionUsage.objects.filter(entry=entry).first()
    if existing:return existing
    if package.usages.filter(appointment_id=entry.appointment_id).exists():
        raise ValidationError("Este agendamento já consumiu uma sessão do pacote.")
    usage=consume_package_credit(customer_package=package,service=entry.appointment.service,
        appointment=entry.appointment,user=user,credits=1)
    return ClinicalSessionUsage.objects.create(entry=entry,usage=usage)
