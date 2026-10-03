from pathlib import Path

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.http import FileResponse,Http404
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import append_audit
from .breakdown import subscription_charge_breakdown
from .models import FiscalDocumentRequest,Payment


MAX_PDF_BYTES=10*1024*1024
MAX_XML_BYTES=5*1024*1024


def _validate_upload(upload,kind):
    if not upload:
        return
    ext=Path(upload.name or "").suffix.lower()
    allowed={".pdf"} if kind=="pdf" else {".xml"}
    if ext not in allowed:
        raise ValidationError(f"Envie um arquivo {next(iter(allowed)).upper()}.")
    maximum=MAX_PDF_BYTES if kind=="pdf" else MAX_XML_BYTES
    if upload.size>maximum:
        raise ValidationError(
            "O PDF deve ter no máximo 10 MB." if kind=="pdf" else "O XML deve ter no máximo 5 MB."
        )
    head=upload.read(512)
    upload.seek(0)
    if kind=="pdf" and not head.startswith(b"%PDF-"):
        raise ValidationError("O arquivo enviado não parece ser um PDF válido.")
    if kind=="xml":
        stripped=head.lstrip(b"\xef\xbb\xbf \t\r\n")
        if not stripped.startswith(b"<"):
            raise ValidationError("O arquivo enviado não parece ser um XML válido.")


class FiscalDocumentUploadForm(forms.Form):
    invoice_number=forms.CharField(max_length=80,label="Número da nota fiscal")
    pdf_file=forms.FileField(label="PDF da NFe / DANFE")
    xml_file=forms.FileField(required=False,label="XML da nota fiscal (opcional)")
    master_note=forms.CharField(
        required=False,max_length=500,label="Observação interna",
        widget=forms.Textarea(attrs={"rows":3}),
    )

    def clean_pdf_file(self):
        value=self.cleaned_data["pdf_file"]
        _validate_upload(value,"pdf")
        return value

    def clean_xml_file(self):
        value=self.cleaned_data.get("xml_file")
        _validate_upload(value,"xml")
        return value


@login_required
@require_POST
def request_fiscal_document(request,payment_id):
    if not request.user.tenant_id or request.user.role not in {
        "owner","manager","tenant-admin"
    }:
        raise PermissionDenied("Somente a gestão da empresa pode solicitar a nota fiscal.")
    payment=get_object_or_404(
        Payment.objects.select_related("subscription","subscription__plan"),
        pk=payment_id,tenant_id=request.user.tenant_id,
        purpose="subscription",status=Payment.Status.PAID,
    )
    paid_at=payment.paid_at or payment.updated_at
    local=timezone.localtime(paid_at)
    reference_month=local.date().replace(day=1)
    breakdown=(payment.metadata or {}).get("breakdown") or subscription_charge_breakdown(
        payment.subscription
    )
    row,created=FiscalDocumentRequest.objects.get_or_create(
        payment=payment,
        defaults={
            "tenant":payment.tenant,
            "subscription":payment.subscription,
            "reference_month":reference_month,
            "amount":payment.amount,
            "charge_breakdown":breakdown,
            "requested_by":request.user,
            "requested_at":timezone.now(),
        },
    )
    if created:
        append_audit(
            tenant=payment.tenant,user=request.user,request=request,
            action="FISCAL_DOCUMENT_REQUESTED",
            entity_type="billing.FiscalDocumentRequest",entity_id=row.pk,
            after={
                "payment_id":payment.pk,
                "reference_month":reference_month.isoformat(),
                "amount":str(payment.amount),
            },
        )
        messages.success(
            request,
            f"NFe de {reference_month:%m/%Y} solicitada. Ela aparecerá aqui após o upload do Master.",
        )
    else:
        messages.info(request,"A NFe deste pagamento já foi solicitada.")
    return redirect("billing-subscription-status")


@login_required
def download_fiscal_document(request,pk,kind):
    row=get_object_or_404(
        FiscalDocumentRequest.objects.select_related("tenant"),pk=pk,
        status=FiscalDocumentRequest.Status.ISSUED,
    )
    if not request.user.is_superuser and request.user.tenant_id!=row.tenant_id:
        raise PermissionDenied("Este documento pertence a outra empresa.")
    field=row.pdf_file if kind=="pdf" else row.xml_file if kind=="xml" else None
    if not field or not field.name:
        raise Http404
    extension=".pdf" if kind=="pdf" else ".xml"
    safe_number="".join(ch for ch in (row.invoice_number or str(row.pk)) if ch.isalnum() or ch in "-_")
    filename=f"NFe-{row.reference_month:%Y-%m}-{safe_number}{extension}"
    append_audit(
        tenant=row.tenant,user=request.user,request=request,
        action="FISCAL_DOCUMENT_DOWNLOADED",
        entity_type="billing.FiscalDocumentRequest",entity_id=row.pk,
        after={"kind":kind,"reference_month":row.reference_month.isoformat()},
    )
    field.open("rb")
    return FileResponse(field,as_attachment=True,filename=filename)


@login_required
def master_fiscal_document(request,pk):
    if not request.user.is_superuser:
        raise PermissionDenied("Acesso restrito ao Master.")
    row=get_object_or_404(
        FiscalDocumentRequest.objects.select_related(
            "tenant","subscription","payment","requested_by"
        ),pk=pk,
    )
    form=FiscalDocumentUploadForm(request.POST or None,request.FILES or None)
    if request.method=="POST" and form.is_valid():
        before={
            "status":row.status,"invoice_number":row.invoice_number,
            "pdf":bool(row.pdf_file),"xml":bool(row.xml_file),
        }
        old_pdf=row.pdf_file.name if row.pdf_file else ""
        old_xml=row.xml_file.name if row.xml_file else ""
        row.invoice_number=form.cleaned_data["invoice_number"].strip()
        row.pdf_file=form.cleaned_data["pdf_file"]
        if form.cleaned_data.get("xml_file"):
            row.xml_file=form.cleaned_data["xml_file"]
        row.master_note=form.cleaned_data.get("master_note","").strip()
        row.status=FiscalDocumentRequest.Status.ISSUED
        row.uploaded_by=request.user
        row.uploaded_at=timezone.now()
        row.save()
        if old_pdf and old_pdf!=row.pdf_file.name:
            row.pdf_file.storage.delete(old_pdf)
        if old_xml and form.cleaned_data.get("xml_file") and old_xml!=row.xml_file.name:
            row.xml_file.storage.delete(old_xml)
        append_audit(
            tenant=row.tenant,user=request.user,request=request,
            action="FISCAL_DOCUMENT_UPLOADED",
            entity_type="billing.FiscalDocumentRequest",entity_id=row.pk,
            before=before,
            after={
                "status":row.status,"invoice_number":row.invoice_number,
                "pdf":bool(row.pdf_file),"xml":bool(row.xml_file),
                "reference_month":row.reference_month.isoformat(),
            },
        )
        messages.success(request,"Nota fiscal enviada. O botão de download já está disponível para a empresa.")
        return redirect("master-resource-list",slug="notas-fiscais")
    return render(request,"master/fiscal_document.html",{"row":row,"form":form})
