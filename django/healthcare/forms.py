from django import forms
from scheduling.models import Customer, Professional, Appointment
from .dentistry import validate_odontogram
import json


class DentalEncounterForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), label="Paciente")
    professional = forms.ModelChoiceField(queryset=Professional.objects.none(), label="Cirurgião-dentista responsável")
    appointment = forms.ModelChoiceField(queryset=Appointment.objects.none(), required=False, label="Agendamento")
    anamnesis = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="Anamnese: queixa, histórico, alergias, medicamentos e condições sistêmicas")
    findings = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="Exame clínico, sinais, diagnóstico e achados")
    procedures = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="Evolução: procedimentos, materiais, anestesia, intercorrências e orientações")
    plan = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), label="Plano terapêutico, prognóstico e retorno")
    odontogram_json = forms.CharField(widget=forms.HiddenInput(), initial="{}")

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(tenant=tenant)
        self.fields["professional"].queryset = Professional.objects.filter(tenant=tenant, active=True)
        self.fields["appointment"].queryset = Appointment.objects.filter(tenant=tenant)

    def clean_odontogram_json(self):
        try:
            return validate_odontogram(json.loads(self.cleaned_data["odontogram_json"]))
        except (TypeError, ValueError) as exc:
            raise forms.ValidationError("Odontograma inválido.") from exc
