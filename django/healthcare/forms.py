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
    odontogram_json = forms.CharField(widget=forms.HiddenInput(attrs={"data-chart-input": ""}), initial="{}")

    def __init__(self, *args, tenant, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(tenant=tenant)
        self.fields["professional"].queryset = Professional.objects.filter(tenant=tenant, user=user, active=True)
        self.fields["appointment"].queryset = Appointment.objects.filter(tenant=tenant, professional__user=user)

    def clean_odontogram_json(self):
        try:
            return validate_odontogram(json.loads(self.cleaned_data["odontogram_json"]))
        except (TypeError, ValueError) as exc:
            raise forms.ValidationError("Odontograma inválido.") from exc

    def clean(self):
        data = super().clean()
        appointment = data.get("appointment")
        customer = data.get("customer")
        professional = data.get("professional")
        if appointment and ((customer and appointment.customer_id != customer.pk)
                or (professional and appointment.professional_id != professional.pk)):
            self.add_error("appointment", "Agendamento incompatível com paciente ou profissional.")
        return data
