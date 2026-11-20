import csv
import hashlib
from datetime import timedelta
from io import StringIO

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from core.crypto import decrypt_json, encrypt_json
from scheduling.models import CustomerImportBatch
from tenants.models import Tenant
from .customer_import_service import FIELDS, MAX_BYTES, apply_batch, counts, preview_rows, read_source, suggested_mapping


def require_master(request):
    if not request.user.is_superuser or not request.user.is_active or request.user.deleted_at or getattr(request, "support_actor", None):
        raise PermissionDenied


class UploadForm(forms.Form):
    tenant = forms.ModelChoiceField(queryset=Tenant.objects.none(), label="Empresa de destino")
    source = forms.FileField(label="Base exportada (CSV ou XLSX)",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,.xlsx"}))
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tenant"].queryset = Tenant.objects.filter(
            deleted_at__isnull=True, archived_at__isnull=True).order_by("name")
    def clean_source(self):
        source = self.cleaned_data["source"]
        if not source.size or source.size > MAX_BYTES:
            raise ValidationError("Envie um CSV ou XLSX de até 5 MB.")
        return source


class MappingForm(forms.Form):
    def __init__(self, *args, headers, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "Não importar")] + [(str(index), f"{index+1}. {name or 'Coluna sem título'}")
                                           for index, name in enumerate(headers)]
        for name, label in FIELDS.items():
            self.fields[name] = forms.ChoiceField(label=label, choices=choices, required=name in {"name", "phone"})
    def clean(self):
        data = super().clean()
        indexes = [index for index in data.values() if index != ""]
        if len(indexes) != len(set(indexes)):
            raise ValidationError("Use uma coluna diferente para cada campo.")
        return data


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def upload(request):
    require_master(request)
    form = UploadForm(request.POST if request.method == "POST" else None,
                      request.FILES if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        source, tenant = form.cleaned_data["source"], form.cleaned_data["tenant"]
        content = source.read(MAX_BYTES + 1)
        try:
            headers, rows = read_source(content, source.name)
            encrypted = encrypt_json({"headers": headers, "rows": rows})
            batch, _ = CustomerImportBatch.objects.get_or_create(
                tenant=tenant, file_hash=hashlib.sha256(content).hexdigest(),
                defaults={"created_by": request.user, "source_name": source.name[:160],
                          "payload_encrypted": encrypted, "mapping": suggested_mapping(headers),
                          "expires_at": timezone.now() + timedelta(hours=24)})
        except ValidationError as exc:
            form.add_error("source", exc)
        except (RuntimeError, ValueError):
            form.add_error(None, "Não foi possível proteger a prévia. Confira a configuração de criptografia do servidor.")
        else:
            if batch.state == "preview" and batch.expires_at <= timezone.now():
                batch.payload_encrypted = encrypted
                batch.expires_at = timezone.now() + timedelta(hours=24)
                batch.save(update_fields=["payload_encrypted", "expires_at", "updated_at"])
            return redirect("master-customer-import-detail", pk=batch.pk)
    return render(request, "master/customer_import_upload.html", {
        "form": form, "batches": CustomerImportBatch.objects.select_related("tenant").order_by("-created_at")[:30]})


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def detail(request, pk):
    require_master(request)
    batch = get_object_or_404(CustomerImportBatch.objects.select_related("tenant"), pk=pk)
    if batch.state == "applied":
        return render(request, "master/customer_import_detail.html", {"batch": batch})
    if batch.expires_at <= timezone.now():
        messages.error(request, "A prévia expirou. Envie o arquivo novamente.")
        return redirect("master-customer-import")
    payload = decrypt_json(batch.payload_encrypted)
    form = MappingForm(request.POST if request.method == "POST" and request.POST.get("action") == "preview" else None,
                       headers=payload["headers"], initial=batch.mapping)
    preview, summary, token = [], None, ""
    if request.method == "POST" and request.POST.get("action") == "apply":
        try:
            signed = signing.loads(request.POST.get("preview_token", ""), salt="customer-import-preview", max_age=3600)
            if signed.get("batch") != batch.pk or signed.get("tenant") != batch.tenant_id or signed.get("file") != batch.file_hash:
                raise ValidationError("A confirmação não corresponde a esta base.")
            batch = apply_batch(batch.pk, request.user, allow_errors=request.POST.get("allow_errors") == "yes",
                                expected_mapping=signed.get("mapping"))
        except (signing.BadSignature, ValidationError) as exc:
            messages.error(request, " ".join(exc.messages) if isinstance(exc, ValidationError) else "Gere a prévia novamente.")
        else:
            messages.success(request, "Importação concluída. Cadastros anteriores e respectivos históricos foram preservados.")
            return redirect("master-customer-import-detail", pk=batch.pk)
    elif request.method == "POST" and form.is_valid():
        batch.mapping = form.cleaned_data
        batch.save(update_fields=["mapping", "updated_at"])
        preview = preview_rows(batch.tenant, payload["headers"], payload["rows"], batch.mapping)
        summary = counts(preview)
        token = signing.dumps({"batch": batch.pk, "tenant": batch.tenant_id, "file": batch.file_hash,
                               "mapping": batch.mapping}, salt="customer-import-preview")
    return render(request, "master/customer_import_detail.html", {
        "batch": batch, "form": form, "preview": preview[:30], "summary": summary,
        "preview_token": token, "total_rows": len(payload["rows"])})


@login_required
@never_cache
def report(request, pk):
    require_master(request)
    batch = get_object_or_404(CustomerImportBatch, pk=pk, state="applied")
    output = StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Linha no arquivo", "Resultado", "Motivo"])
    labels = {"create": "Importado", "skip": "Mantido sem alterações", "error": "Não importado"}
    for row in batch.report.get("rows", []):
        writer.writerow([row["row"], labels.get(row["state"], row["state"]), row["reason"]])
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="importacao-clientes-{batch.pk}.csv"'
    return response


@login_required
def example(request):
    require_master(request)
    response = HttpResponse("\ufeffNome;Telefone;Email;Nascimento;Observacoes\r\n",
                            content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="modelo-importacao-clientes.csv"'
    return response
