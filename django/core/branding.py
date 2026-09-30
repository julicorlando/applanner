from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from contenthub.models import BlogPost, PlatformHomepage
from scheduling.models import Professional
from tenants.models import Tenant


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
        fields=["logo","hero_title","hero_description","closing_title"]
        labels={"logo":"Logo personalizada (opcional)","hero_title":"Título principal",
                "hero_description":"Descrição principal","closing_title":"Chamada final"}


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


@login_required
def tenant_branding(request):
    tenant=request.user.tenant
    if tenant is None:
        raise PermissionDenied
    from accounts.permissions import has_capability
    if not has_capability(request.user,"agenda.manage"):
        raise PermissionDenied
    form=TenantBrandingForm(request.POST or None,request.FILES or None,instance=tenant)
    if request.method=="POST" and form.is_valid():
        form.save()
        messages.success(request,"Página pública atualizada.")
        return redirect("tenant-branding")
    return render(request,"portal/branding.html",{"tenant":tenant,"form":form})


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
    return _image_response(getattr(tenant,kind))


def public_professional_image(request,pk):
    professional=get_object_or_404(Professional,pk=pk,active=True,tenant__public_enabled=True,
        tenant__status__in=[Tenant.Status.TRIAL,Tenant.Status.ACTIVE],tenant__deleted_at__isnull=True)
    return _image_response(professional.photo)


def public_blog_image(request,pk):
    return _image_response(get_object_or_404(BlogPost,pk=pk,status=BlogPost.Status.PUBLISHED).cover)


def platform_branding(request):
    return {"platform_branding":PlatformHomepage.objects.filter(pk=1).first()}
