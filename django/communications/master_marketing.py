"""Master-only campaign authoring and consent-aware contact imports."""
import csv
import io
import secrets

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import MarketingCampaign, MarketingDelivery, MarketingLead


class CampaignForm(forms.Form):
    subject=forms.CharField(max_length=190,label="Assunto")
    body=forms.CharField(label="Mensagem",widget=forms.Textarea(attrs={"rows":9}),
                         help_text="Texto simples. O link de descadastro será incluído automaticamente.")
    card_link_url=forms.URLField(required=False,label="Link da chamada para ação")
    confirm=forms.BooleanField(label="Confirmo o envio somente para contatos com consentimento registrado")


class ContactImportForm(forms.Form):
    file=forms.FileField(label="Arquivo CSV (nome,email)")
    confirm=forms.BooleanField(label="Confirmo que os contatos deram consentimento para receber campanhas")

    def clean_file(self):
        uploaded=self.cleaned_data["file"]
        if uploaded.size>1024*1024:
            raise forms.ValidationError("O CSV deve ter no máximo 1 MB.")
        try:
            contents=uploaded.read().decode("utf-8-sig")
            reader=csv.DictReader(io.StringIO(contents))
            if not reader.fieldnames or not {"nome","email"}.issubset({name.strip().lower() for name in reader.fieldnames}):
                raise ValueError
            rows=[]
            for row in reader:
                normalized={key.strip().lower():value for key,value in row.items() if key}
                email=forms.EmailField().clean((normalized.get("email") or "").strip().lower())
                name=(normalized.get("nome") or "").strip()
                if not name or len(name)>160:
                    raise ValueError
                rows.append((name,email))
                if len(rows)>5000:
                    raise ValueError
            if not rows:
                raise ValueError
        except (UnicodeError,ValueError,forms.ValidationError,csv.Error):
            raise forms.ValidationError("CSV inválido. Use UTF-8, cabeçalho nome,email e até 5.000 contatos válidos.")
        return rows


def _master(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Acesso restrito ao Master.")


@login_required
def campaigns(request):
    _master(request)
    return render(request,"master/marketing.html",{
        "campaign_form":CampaignForm(),"import_form":ContactImportForm(),
        "campaigns":MarketingCampaign.objects.order_by("-created_at")[:50],
        "eligible_count":MarketingLead.objects.filter(status=MarketingLead.Status.ACTIVE,consent_at__isnull=False).count(),
    })


@login_required
def create_campaign(request):
    _master(request)
    if request.method!="POST":
        return redirect("master-marketing")
    form=CampaignForm(request.POST)
    if not settings.PUBLIC_BASE_URL.startswith("https://"):
        form.add_error(None,"Configure PUBLIC_BASE_URL com HTTPS antes de enviar campanhas e oferecer descadastro.")
    if not form.is_valid():
        return render(request,"master/marketing.html",{"campaign_form":form,"import_form":ContactImportForm(),
            "campaigns":MarketingCampaign.objects.order_by("-created_at")[:50],
            "eligible_count":MarketingLead.objects.filter(status=MarketingLead.Status.ACTIVE,consent_at__isnull=False).count()})
    with transaction.atomic():
        lead_ids=list(MarketingLead.objects.filter(
            status=MarketingLead.Status.ACTIVE,consent_at__isnull=False,
        ).values_list("pk",flat=True))
        if not lead_ids:
            form.add_error(None,"Não há contatos ativos com consentimento registrado.")
            return render(request,"master/marketing.html",{"campaign_form":form,"import_form":ContactImportForm(),
                "campaigns":MarketingCampaign.objects.order_by("-created_at")[:50],"eligible_count":0})
        campaign=MarketingCampaign.objects.create(
            subject=form.cleaned_data["subject"],body=form.cleaned_data["body"],
            card_link_url=form.cleaned_data["card_link_url"],created_by=request.user,
            total_count=len(lead_ids),queued_at=timezone.now(),
        )
        MarketingDelivery.objects.bulk_create([
            MarketingDelivery(campaign=campaign,lead_id=lead_id) for lead_id in lead_ids
        ],batch_size=500)
    messages.success(request,f"Campanha colocada na fila para {len(lead_ids)} contatos com consentimento.")
    return redirect("master-marketing")


@login_required
def cancel_campaign(request,pk):
    _master(request)
    if request.method!="POST":
        return redirect("master-marketing")
    with transaction.atomic():
        campaign=MarketingCampaign.objects.select_for_update().filter(pk=pk).first()
        if campaign and campaign.status in {MarketingCampaign.Status.QUEUED,MarketingCampaign.Status.SENDING}:
            campaign.active=False
            campaign.status=MarketingCampaign.Status.CANCELLED
            campaign.save(update_fields=["active","status","updated_at"])
    messages.success(request,"Envios pendentes interrompidos.")
    return redirect("master-marketing")


@login_required
def import_contacts(request):
    _master(request)
    if request.method!="POST":
        return redirect("master-marketing")
    form=ContactImportForm(request.POST,request.FILES)
    if not form.is_valid():
        return render(request,"master/marketing.html",{"campaign_form":CampaignForm(),"import_form":form,
            "campaigns":MarketingCampaign.objects.order_by("-created_at")[:50],
            "eligible_count":MarketingLead.objects.filter(status=MarketingLead.Status.ACTIVE,consent_at__isnull=False).count()})
    created=0
    with transaction.atomic():
        for email,name in {email:name for name,email in form.cleaned_data["file"]}.items():
            _,added=MarketingLead.objects.get_or_create(email=email,defaults={
                "name":name,"status":MarketingLead.Status.ACTIVE,"source":MarketingLead.Source.CSV,
                "unsubscribe_token":secrets.token_hex(32),"consent_at":timezone.now(),
            })
            created+=int(added)
    messages.success(request,f"{created} novos contatos com consentimento importados. Contatos existentes foram preservados.")
    return redirect("master-marketing")
