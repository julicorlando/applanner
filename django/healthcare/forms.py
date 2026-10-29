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
        for name,label in DENTAL_DETAILS.items():
            self.fields[name]=forms.CharField(label=label,required=False,max_length=20000,widget=forms.Textarea(attrs={"rows":2}))
        self.fields["customer"].queryset = Customer.objects.filter(tenant=tenant)
        self.fields["professional"].queryset = Professional.objects.filter(tenant=tenant, user=user, active=True)
        self.fields["appointment"].queryset = Appointment.objects.filter(tenant=tenant, professional__user=user)
        from .models import ClinicalTreatmentPlan
        from .services import clinical_records_for
        self.fields["plan_reference"]=forms.ModelChoiceField(label="Plano de tratamento relacionado",required=False,queryset=ClinicalTreatmentPlan.objects.filter(entry__in=clinical_records_for(user=user,tenant=tenant)).select_related("entry__customer"))

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
        reference=data.get("plan_reference")
        if reference and customer and reference.entry.customer_id!=customer.pk:
            self.add_error("plan_reference","O plano de tratamento pertence a outro paciente.")
        return data


DENTAL_DETAILS={
    "chief_complaint":"Queixa principal","medical_history":"Histórico médico e odontológico",
    "previous_treatments":"Tratamentos anteriores","allergies":"Alergias e alertas",
    "medications":"Medicamentos","systemic_conditions":"Condições sistêmicas",
    "extraoral_exam":"Exame extraoral","intraoral_exam":"Exame intraoral",
    "signs_symptoms":"Sinais e sintomas","diagnosis":"Diagnóstico",
    "diagnostic_hypotheses":"Hipóteses diagnósticas","materials":"Materiais utilizados",
    "anesthesia":"Anestesia","complications":"Intercorrências",
    "postoperative_guidance":"Orientações pós-operatórias","return_followup":"Retornos e acompanhamento",
}
