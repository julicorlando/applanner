"""Formulários operacionais com vínculos limitados à própria empresa."""
from django import forms
from django.db import transaction

from scheduling.models import Professional, Service

WEEKDAYS=((1,"Segunda-feira"),(2,"Terça-feira"),(3,"Quarta-feira"),
          (4,"Quinta-feira"),(5,"Sexta-feira"),(6,"Sábado"),(7,"Domingo"))


class OperationModelForm(forms.ModelForm):
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.tenant=tenant
        label=self._meta.model._meta.label_lower
        if "weekday" in self.fields:
            required=self.fields["weekday"].required
            choices=WEEKDAYS if required else (("","Todos os dias"),)+WEEKDAYS
            self.fields["weekday"]=forms.TypedChoiceField(
                label="Dia da semana",choices=choices,coerce=int,empty_value=None,required=required)
        if label=="scheduling.professional":
            restricted=bool(self.instance.pk and (self.instance.services_restricted or self.instance.services.exists()))
            self.fields["service_selection"]=forms.BooleanField(required=False,initial=True,widget=forms.HiddenInput)
            self.fields["all_services"]=forms.BooleanField(required=False,initial=not restricted,
                label="Atende todos os serviços",help_text="Desmarque para selecionar os serviços deste profissional.")
            self.fields["offered_services"]=forms.ModelMultipleChoiceField(
                queryset=Service.objects.filter(tenant=tenant).order_by("name"),required=False,
                initial=self.instance.services.all() if self.instance.pk else [],
                widget=forms.CheckboxSelectMultiple,label="Serviços atendidos")
        elif label=="scheduling.service":
            professionals=Professional.objects.filter(tenant=tenant).order_by("name")
            initial=[p.pk for p in professionals if not (p.services_restricted or p.services.exists())
                     or (self.instance.pk and p.services.filter(pk=self.instance.pk).exists())]
            self.fields["service_selection"]=forms.BooleanField(required=False,initial=True,widget=forms.HiddenInput)
            self.fields["offering_professionals"]=forms.ModelMultipleChoiceField(
                queryset=professionals,required=False,initial=initial,widget=forms.CheckboxSelectMultiple,
                label="Profissionais que atendem este serviço",
                help_text="Selecione a equipe responsável. Os vínculos dos demais serviços serão preservados.")

    def clean(self):
        data=super().clean()
        if data.get("start_time") and data.get("end_time") and data["end_time"]<=data["start_time"]:
            self.add_error("end_time","A hora final deve ser posterior à hora inicial.")
        if data.get("duration_minutes") is not None and data["duration_minutes"]<=0:
            self.add_error("duration_minutes","Informe uma duração maior que zero.")
        if data.get("price") is not None and data["price"]<0:
            self.add_error("price","O preço não pode ser negativo.")
        if self.cleaned_data.get("service_selection") and self._meta.model==Professional:
            if not data.get("all_services") and not data.get("offered_services"):
                self.add_error("offered_services","Selecione pelo menos um serviço ou marque que atende todos.")
        return data

    @transaction.atomic
    def _save_m2m(self):
        super()._save_m2m()
        if not self.cleaned_data.get("service_selection"):
            return
        if self._meta.model==Professional:
            self.instance.services_restricted=not self.cleaned_data["all_services"]
            self.instance.save(update_fields=["services_restricted"])
            self.instance.services.set(self.cleaned_data["offered_services"] if self.instance.services_restricted else [])
        elif self._meta.model==Service:
            selected={p.pk for p in self.cleaned_data["offering_professionals"]}
            for professional in Professional.objects.select_for_update().filter(tenant=self.tenant,pk__in=self.fields["offering_professionals"].queryset.values("pk")).order_by("pk"):
                if not professional.services_restricted and not professional.services.exists():
                    # Explicit selection freezes the previous all-services access;
                    # an empty result must mean no services, not unrestricted access.
                    professional.services.set(Service.objects.filter(tenant=self.tenant).exclude(pk=self.instance.pk))
                professional.services_restricted=True
                professional.save(update_fields=["services_restricted"])
                if professional.pk in selected:
                    professional.services.add(self.instance)
                else:
                    professional.services.remove(self.instance)
