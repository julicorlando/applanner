from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from contenthub.models import BlogPost, PlatformHomepage
from scheduling.models import Professional
from tenants.models import Tenant,Unit


class ImageSizeForm(forms.ModelForm):
    def clean(self):
        data=super().clean()
        for field in ("logo","cover"):
            uploaded=data.get(field)
            if uploaded and getattr(uploaded,"size",0)>5*1024*1024:
                self.add_error(field,"Imagem deve ter no máximo 5 MB.")
        return data


class PlatformHomepageForm(ImageSizeForm):
    class Meta:
        model=PlatformHomepage
        fields=["logo","hero_title","hero_description","closing_title","medical_segment_visible"]
        labels={"logo":"Logo personalizada (opcional)","hero_title":"Título principal",
                "hero_description":"Descrição principal","closing_title":"Chamada final",
                "medical_segment_visible":"Exibir Médico / Clínica e Clínicas publicamente"}


class TenantBrandingForm(ImageSizeForm):
    class Meta:
        model=Tenant
        fields=["logo","cover","description","public_headline","public_subheadline",
                "public_enabled","public_booking_enabled"]
        labels={"logo":"Logo da empresa","cover":"Foto de capa da página pública",
                "description":"Descrição da empresa","public_headline":"Título da página pública",
                "public_subheadline":"Descrição da página pública",
                "public_enabled":"Mostrar empresa no diretório e abrir página pública",
                "public_booking_enabled":"Permitir agendamento na página pública"}


@login_required
def platform_homepage(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    row,_=PlatformHomepage.objects.get_or_create(pk=1)
    form=PlatformHomepageForm(request.POST or None,request.FILES or None,instance=row)
    if request.method=="POST" and form.is_valid():
        form.save()
        messages.success(request,"Página inicial atualizada.")
        return redirect("master-homepage")
    return render(request,"master/homepage.html",{"form":form,"branding":row})


class PublicTextListField(forms.CharField):
    def prepare_value(self,value):
        return "\n".join(value) if isinstance(value,list) else value

    def to_python(self,value):
        text=super().to_python(value).strip()
        if not text:
            return []
        if text.startswith("["):
            import json
            try:
                rows=json.loads(text)
            except ValueError:
                raise forms.ValidationError("Informe os itens separados por linha ou vírgula.")
            if not isinstance(rows,list) or any(not isinstance(item,str) for item in rows):
                raise forms.ValidationError("Informe somente nomes de itens.")
        else:
            rows=text.replace(",","\n").splitlines()
        return list(dict.fromkeys(item.strip() for item in rows if item.strip()))


class UnitBrandingForm(ImageSizeForm):
    amenities=PublicTextListField(label="Comodidades",required=False,widget=forms.Textarea(attrs={"rows":3}))
    payment_methods=PublicTextListField(label="Formas de pagamento",required=False,widget=forms.Textarea(attrs={"rows":3}))
    description=forms.CharField(label="Descrição da unidade",required=False,widget=forms.Textarea)
    public_headline=forms.CharField(label="Título da página",max_length=120,required=False)
    public_subheadline=forms.CharField(label="Apresentação da unidade",max_length=300,required=False)
    public_cta_label=forms.CharField(label="Texto do botão de agendamento",max_length=60,required=False)
    public_announcement=forms.CharField(label="Aviso na capa",max_length=160,required=False)
    primary_color=forms.RegexField(r"^#[0-9a-fA-F]{6}$",label="Cor dos botões",widget=forms.TextInput(attrs={"type":"color"}))
    background_color=forms.RegexField(r"^#[0-9a-fA-F]{6}$",label="Cor de fundo",widget=forms.TextInput(attrs={"type":"color"}))
    text_color=forms.RegexField(r"^#[0-9a-fA-F]{6}$",label="Cor do texto",widget=forms.TextInput(attrs={"type":"color"}))

    class Meta:
        model=Unit
        fields=["logo","cover","public_notes","phone","whatsapp","email","instagram","facebook","tiktok","website","amenities","payment_methods"]
        labels={"logo":"Logo da unidade","cover":"Capa da unidade","public_notes":"Informações da unidade",
                "phone":"Telefone","whatsapp":"WhatsApp","email":"E-mail","instagram":"Instagram",
                "facebook":"Facebook","tiktok":"TikTok","website":"Site","amenities":"Comodidades",
                "payment_methods":"Formas de pagamento"}

    setting_fields=("description","public_headline","public_subheadline","public_cta_label",
                    "public_announcement","primary_color","background_color","text_color")

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for key in self.setting_fields:
            self.fields[key].initial=(self.instance.public_settings or {}).get(key,getattr(self.instance.tenant,key,""))
        for key in ("amenities","payment_methods"):
            self.fields[key].help_text='Informe um item por linha ou separe por vírgulas.'

    def clean(self):
        data=super().clean()
        for key in ("amenities","payment_methods"):
            value=data.get(key)
            if value is not None and (not isinstance(value,list) or any(not isinstance(item,str) for item in value)):
                self.add_error(key,"Informe uma lista de textos.")
        return data

    def save(self,commit=True):
        self.instance.public_settings={key:self.cleaned_data[key] for key in self.setting_fields}
        return super().save(commit=commit)


@login_required
def tenant_branding(request):
    tenant=request.user.tenant
    if tenant is None:
        raise PermissionDenied
    from accounts.permissions import has_capability
    if not has_capability(request.user,"agenda.manage"):
        raise PermissionDenied
    units=list(tenant.units.filter(active=True).order_by("-is_primary","name"))
    raw=request.GET.get("unit") or request.POST.get("unit")
    selected_unit=get_object_or_404(Unit,pk=raw,tenant=tenant,active=True) if raw and str(raw).isdigit() else (units[0] if units else None)
    if selected_unit:
        request.session[f"operation_unit_{tenant.pk}"]=selected_unit.pk
    if request.GET.get("company")=="1":
        selected_unit=None
    Form=UnitBrandingForm if selected_unit else TenantBrandingForm
    form=Form(request.POST or None,request.FILES or None,instance=selected_unit or tenant)
    if request.method=="POST" and form.is_valid():
        form.save()
        messages.success(request,"Página da unidade atualizada." if selected_unit else "Página pública atualizada.")
        from django.urls import reverse
        return redirect(reverse("tenant-branding")+(f"?unit={selected_unit.pk}" if selected_unit else "?company=1"))
    from .public_identity import short_url, verification_status
    return render(request,"portal/branding.html",{"tenant":tenant,"form":form,"unit_choices":units,"selected_unit":selected_unit,
        "short_link":short_url(tenant,selected_unit), "verification":verification_status(tenant)})


def _image_response(image):
    if not image:
        raise Http404
    try:
        stream=image.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404 from None
    # Field-level ImageField validation occurs on upload. Never expose arbitrary media paths.
    from pathlib import Path
    suffix=Path(image.name).suffix.lower()
    content_type={".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",
                  ".webp":"image/webp",".gif":"image/gif"}.get(suffix,"application/octet-stream")
    response=FileResponse(stream,content_type=content_type)
    response["X-Content-Type-Options"]="nosniff"
    response["Cache-Control"]="public, max-age=300"
    return response


def public_platform_logo(request):
    return _image_response(get_object_or_404(PlatformHomepage,pk=1).logo)


def public_tenant_image(request,pk,kind):
    if kind not in {"logo","cover"}:
        raise Http404
    tenant=get_object_or_404(Tenant,pk=pk,public_enabled=True,
                             status__in=[Tenant.Status.TRIAL,Tenant.Status.ACTIVE],deleted_at__isnull=True)
    raw=request.GET.get("unit","")
    unit=get_object_or_404(Unit,pk=int(raw),tenant=tenant,active=True) if raw.isdigit() else None
    return _image_response((getattr(unit,kind) if unit else None) or getattr(tenant,kind))


def public_professional_image(request,pk):
    professional=get_object_or_404(Professional,pk=pk,active=True,tenant__public_enabled=True,
        tenant__status__in=[Tenant.Status.TRIAL,Tenant.Status.ACTIVE],tenant__deleted_at__isnull=True)
    return _image_response(professional.photo)


def public_blog_image(request,pk):
    return _image_response(get_object_or_404(BlogPost,pk=pk,status=BlogPost.Status.PUBLISHED).cover)


def platform_branding(request):
    return {"platform_branding":PlatformHomepage.objects.filter(pk=1).first()}
