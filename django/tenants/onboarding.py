import re

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify

from scheduling.models import Professional, ProfessionalAvailability, ProfessionalService, Service
from .models import Tenant, TenantOnboarding, Unit


STEPS=(
    ("company_done","Empresa e contato"),
    ("unit_done","Endereço da unidade"),
    ("service_done","Primeiro serviço"),
    ("professional_done","Primeiro profissional"),
    ("schedule_done","Horários de atendimento"),
    ("branding_done","Página e pagamentos"),
)


def validate_document(value):
    digits=re.sub(r"\D","",value)
    if len(digits)==11 and len(set(digits))>1:
        first=(sum(int(digits[i])*(10-i) for i in range(9))*10)%11%10
        second=(sum(int(digits[i])*(11-i) for i in range(10))*10)%11%10
        if digits[-2:]==f"{first}{second}":
            return digits
    if len(digits)==14 and len(set(digits))>1:
        weights_a=(5,4,3,2,9,8,7,6,5,4,3,2)
        weights_b=(6,5,4,3,2,9,8,7,6,5,4,3,2)
        a=(sum(int(n)*w for n,w in zip(digits[:12],weights_a))%11)
        a=0 if a<2 else 11-a
        b=(sum(int(n)*w for n,w in zip(digits[:13],weights_b))%11)
        b=0 if b<2 else 11-b
        if digits[-2:]==f"{a}{b}":
            return digits
    raise forms.ValidationError("Informe um CPF ou CNPJ válido.")


def validate_phone(value):
    digits=re.sub(r"\D","",value or "")
    if not 10<=len(digits)<=13:
        raise forms.ValidationError("Informe telefone com DDD (10 ou 11 dígitos; código do país opcional).")
    return digits


class CompanyForm(forms.ModelForm):
    class Meta:
        model=Tenant
        fields=["name","document","category","email","phone","description"]
        labels={"name":"Nome da empresa","document":"CPF ou CNPJ","category":"Segmento",
                "email":"E-mail comercial","phone":"Telefone com DDD","description":"Apresentação (opcional)"}
        widgets={"category":forms.Select(choices=[("","Selecione"),("barbearia","Barbearia"),
            ("salao","Salão"),("estetica","Estética"),("auto","Automotivo"),
            ("arena","Arena / quadras"),("saude","Saúde"),("outro","Outro")])}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for key in ("document","category","email","phone"):
            self.fields[key].required=True

    def clean_document(self):
        document=validate_document(self.cleaned_data["document"])
        if Tenant.objects.filter(document=document,deleted_at__isnull=True).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Este documento já está vinculado a outra empresa.")
        return document

    def clean_phone(self):
        return validate_phone(self.cleaned_data["phone"])


class UnitForm(forms.ModelForm):
    class Meta:
        model=Unit
        fields=["name","postal_code","address","address_number","address_complement",
                "district","city","state","phone","whatsapp"]
        labels={"name":"Nome da unidade","postal_code":"CEP","address":"Rua / avenida",
                "address_number":"Número","address_complement":"Complemento (opcional)",
                "district":"Bairro","city":"Cidade","state":"UF",
                "phone":"Telefone da unidade","whatsapp":"WhatsApp (opcional)"}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for key in ("postal_code","address","address_number","district","city","state","phone"):
            self.fields[key].required=True

    def clean_postal_code(self):
        digits=re.sub(r"\D","",self.cleaned_data["postal_code"])
        if len(digits)!=8:
            raise forms.ValidationError("Informe um CEP com 8 dígitos.")
        return digits

    def clean_state(self):
        state=self.cleaned_data["state"].strip().upper()
        if state not in set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()):
            raise forms.ValidationError("Informe uma UF brasileira válida.")
        return state

    def clean_phone(self):
        return validate_phone(self.cleaned_data["phone"])

    def clean_whatsapp(self):
        value=self.cleaned_data.get("whatsapp")
        return validate_phone(value) if value else ""


class ServiceForm(forms.ModelForm):
    class Meta:
        model=Service
        fields=["name","description","duration_minutes","price"]
        labels={"name":"Nome do serviço","description":"Descrição (opcional)",
                "duration_minutes":"Duração em minutos","price":"Preço em R$"}

    def clean_duration_minutes(self):
        value=self.cleaned_data["duration_minutes"]
        if value<5 or value>720:
            raise forms.ValidationError("Informe uma duração entre 5 e 720 minutos.")
        return value


class ProfessionalForm(forms.ModelForm):
    class Meta:
        model=Professional
        fields=["name","specialty","phone","email","photo"]
        labels={"name":"Nome do profissional","specialty":"Especialidade (opcional)",
                "phone":"Telefone (opcional)","email":"E-mail (opcional)","photo":"Foto (opcional)"}

    def clean_phone(self):
        value=self.cleaned_data.get("phone")
        return validate_phone(value) if value else ""

    def clean_photo(self):
        photo=self.cleaned_data.get("photo")
        if photo and getattr(photo,"size",0)>5*1024*1024:
            raise forms.ValidationError("A foto deve ter até 5 MB.")
        return photo


class HoursForm(forms.Form):
    days=forms.MultipleChoiceField(
        choices=[(str(day),label) for day,label in enumerate(
            ("Segunda","Terça","Quarta","Quinta","Sexta","Sábado","Domingo"),start=1)],
        widget=forms.CheckboxSelectMultiple,label="Dias de atendimento",
    )
    start_time=forms.TimeField(widget=forms.TimeInput(attrs={"type":"time"}),label="Abre às")
    end_time=forms.TimeField(widget=forms.TimeInput(attrs={"type":"time"}),label="Fecha às")

    def clean(self):
        values=super().clean()
        if values.get("start_time") and values.get("end_time") and values["start_time"]>=values["end_time"]:
            self.add_error("end_time","O encerramento deve ser depois da abertura.")
        return values


class PublicForm(forms.ModelForm):
    methods=forms.MultipleChoiceField(
        choices=[("pix","Pix"),("card","Cartão"),("cash","Dinheiro")],
        widget=forms.CheckboxSelectMultiple,label="Formas de pagamento aceitas",
    )

    class Meta:
        model=Tenant
        fields=["logo","cover","primary_color","public_headline","public_subheadline","public_booking_enabled"]
        labels={"logo":"Logo (opcional)","cover":"Foto de capa (opcional)",
                "primary_color":"Cor principal (#RRGGBB)","public_headline":"Título da página pública",
                "public_subheadline":"Texto de apresentação (opcional)",
                "public_booking_enabled":"Permitir agendamentos pela página"}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["methods"].initial=self.instance.accepted_payment_methods or ["pix"]
        self.fields["public_headline"].required=True

    def clean_primary_color(self):
        value=self.cleaned_data["primary_color"]
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}",value):
            raise forms.ValidationError("Use uma cor no formato #RRGGBB.")
        return value

    def clean(self):
        values=super().clean()
        for key in ("logo","cover"):
            image=values.get(key)
            if image and getattr(image,"size",0)>5*1024*1024:
                self.add_error(key,"A imagem deve ter até 5 MB.")
        return values


def _first_step(row):
    for field,label in STEPS:
        if not getattr(row,field):
            return field,label
    return "verification","Verificação e publicação"


@login_required
def onboarding(request):
    if not request.user.tenant_id or request.user.is_superuser:
        raise PermissionDenied
    tenant=request.user.tenant
    row=TenantOnboarding.objects.filter(tenant=tenant,required=True).first()
    if not row or row.completed_at:
        return redirect("home")
    if request.user.role!="owner":
        return render(request,"tenants/onboarding_wait.html",{"tenant":tenant},status=403)

    step,label=_first_step(row)
    unit=Unit.objects.filter(tenant=tenant,is_primary=True).first()
    service=Service.objects.filter(tenant=tenant,active=True).order_by("pk").first()
    professional=Professional.objects.filter(tenant=tenant,active=True).order_by("pk").first()
    if step=="company_done":
        form=CompanyForm(request.POST or None,instance=tenant)
    elif step=="unit_done":
        form=UnitForm(request.POST or None,instance=unit)
    elif step=="service_done":
        form=ServiceForm(request.POST or None,instance=service)
    elif step=="professional_done":
        form=ProfessionalForm(request.POST or None,request.FILES or None,instance=professional)
    elif step=="schedule_done":
        form=HoursForm(request.POST or None,initial={"days":["1","2","3","4","5"],"start_time":"09:00","end_time":"18:00"})
    elif step=="branding_done":
        form=PublicForm(request.POST or None,request.FILES or None,instance=tenant)
    else:
        form=None

    if request.method=="POST" and step=="verification":
        if not request.user.email_verified_at:
            messages.error(request,"Confirme seu e-mail para concluir o cadastro.")
        elif not (unit and service and professional and ProfessionalAvailability.objects.filter(tenant=tenant,professional=professional,active=True).exists()):
            messages.error(request,"Faltam dados de unidade, serviço, profissional ou horários. Contate o suporte.")
        else:
            with transaction.atomic():
                row=TenantOnboarding.objects.select_for_update().get(tenant=tenant)
                if all(getattr(row,flag) for flag,_ in STEPS):
                    tenant.public_enabled=request.POST.get("publish")=="on"
                    tenant.save(update_fields=["public_enabled","updated_at"])
                    row.public_page_done=True
                    row.completed_at=timezone.now()
                    row.save(update_fields=["public_page_done","completed_at","updated_at"])
                    messages.success(request,"Cadastro concluído. Sua operação está pronta.")
                    return redirect("home")
    elif request.method=="POST" and form and form.is_valid():
        with transaction.atomic():
            if step in {"company_done","branding_done"}:
                obj=form.save(commit=False)
                if step=="branding_done":
                    obj.accepted_payment_methods=form.cleaned_data["methods"]
                    obj.public_enabled=False  # Só o responsável verificado publica a página.
                obj.save()
                if step=="branding_done":
                    row.payment_done=True
                    row.save(update_fields=["payment_done","updated_at"])
            elif step=="unit_done":
                obj=form.save(commit=False)
                obj.tenant=tenant
                obj.is_primary=True
                obj.save()
            elif step=="service_done":
                obj=form.save(commit=False)
                obj.tenant=tenant
                obj.save()
            elif step=="professional_done":
                obj=form.save(commit=False)
                obj.tenant=tenant
                obj.unit=unit
                obj.public_slug=slugify(obj.name)[:100] or "profissional"
                if Professional.objects.filter(tenant=tenant,public_slug=obj.public_slug).exclude(pk=obj.pk).exists():
                    obj.public_slug=f"{obj.public_slug[:90]}-{tenant.pk}"
                obj.save()
                ProfessionalService.objects.get_or_create(professional=obj,service=service)
            elif step=="schedule_done":
                days={int(value) for value in form.cleaned_data["days"]}
                ProfessionalAvailability.objects.filter(tenant=tenant,professional=professional).exclude(weekday__in=days).update(active=False)
                for day in days:
                    ProfessionalAvailability.objects.update_or_create(
                        professional=professional,weekday=day,
                        defaults={"tenant":tenant,"start_time":form.cleaned_data["start_time"],
                                  "end_time":form.cleaned_data["end_time"],"active":True},
                    )
            setattr(row,step,True)
            row.save(update_fields=[step,"updated_at"])
            tenant.onboarding_step=1+sum(bool(getattr(row,flag)) for flag,_ in STEPS)
            tenant.save(update_fields=["onboarding_step","updated_at"])
        return redirect("tenant-onboarding")

    return render(request,"tenants/onboarding.html",{
        "tenant":tenant,"step":step,"label":label,"form":form,
        "progress":sum(bool(getattr(row,flag)) for flag,_ in STEPS),
        "total":len(STEPS)+1,"verified":bool(request.user.email_verified_at),
    })
