import uuid
import base64
import binascii
from io import BytesIO
from django import forms
from django.utils import timezone
from PIL import Image
from scheduling.models import Customer, Professional, Appointment
from .models import PhysiotherapyAssessmentDocument

TEXT_FIELDS = {
    "chief_complaint": "Queixa principal",
    "medical_history": "História clínica (resumo)",
    "medications_allergies": "Medicamentos, alergias e precauções",
    "functional_limits": "Avaliação funcional e limitações",
    "posture_notes": "Observações posturais",
    "gait_notes": "Observações da marcha",
    "medical_diagnosis": "Diagnóstico médico informado",
    "physiotherapy_diagnosis": "Diagnóstico fisioterapêutico",
    "neurological_assessment": "Avaliação neurológica, quando aplicável",
    "initial_evolution": "Conduta / evolução inicial",
    "prognosis": "Prognóstico e reavaliação prevista",
    "guidance": "Orientações e próxima conduta",
}
POSTURE = [
    ("postural_change", "Alteração postural"),
    ("asymmetric_shoulders", "Ombros assimétricos"),
    ("hyperlordosis", "Hiperlordose"),
    ("scoliosis", "Escoliose"),
    ("other", "Outros achados"),
]
SIDES = [
    ("", "Sem lateralidade"),
    ("right", "Direita"),
    ("left", "Esquerda"),
    ("bilateral", "Bilateral"),
]


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        if not data:
            return []
        items = data if isinstance(data, (list, tuple)) else [data]
        if len(items) > 10:
            raise forms.ValidationError("Envie até dez arquivos por vez.")
        return [super(MultipleFileField, self).clean(item, initial) for item in items]


class AssessmentForm(forms.Form):
    submission_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(), label="Paciente"
    )
    professional = forms.ModelChoiceField(
        queryset=Professional.objects.none(), label="Profissional responsável"
    )
    appointment = forms.ModelChoiceField(
        queryset=Appointment.objects.none(),
        required=False,
        label="Atendimento vinculado",
    )
    evaluation_date = forms.DateField(
        label="Data da avaliação",
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    version = forms.IntegerField(min_value=0, initial=0, widget=forms.HiddenInput)
    blood_pressure = forms.RegexField(
        regex=r"^\d{1,3}/\d{1,3}$",
        required=False,
        max_length=12,
        label="Pressão arterial",
        error_messages={"invalid": "Use o formato 120/80, ou deixe sem preenchimento."},
        widget=forms.TextInput(attrs={"placeholder": "Não aferida"}),
    )
    heart_rate = forms.IntegerField(
        required=False, min_value=0, max_value=400, label="Frequência cardíaca (bpm)"
    )
    respiratory_rate = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=150,
        label="Frequência respiratória (irpm)",
    )
    oxygen_saturation = forms.IntegerField(
        required=False, min_value=0, max_value=100, label="SpO₂ (%)"
    )
    temperature = forms.DecimalField(
        required=False,
        min_value=20,
        max_value=50,
        max_digits=3,
        decimal_places=1,
        label="Temperatura (°C)",
    )
    pain_level = forms.IntegerField(
        required=False, min_value=0, max_value=10, label="Escala de dor (EVA)"
    )
    posture = forms.MultipleChoiceField(
        choices=POSTURE,
        required=False,
        label="Postura",
        widget=forms.CheckboxSelectMultiple,
    )
    gait = forms.ChoiceField(
        required=False,
        label="Marcha",
        choices=[
            ("", "Não avaliada"),
            ("normal", "Preservada"),
            ("mild", "Levemente alterada"),
            ("altered", "Alterada"),
            ("assisted", "Com auxílio"),
        ],
    )
    rom = forms.JSONField(required=False, initial=list, widget=forms.HiddenInput)
    strength = forms.JSONField(required=False, initial=list, widget=forms.HiddenInput)
    special_tests = forms.JSONField(
        required=False, initial=list, widget=forms.HiddenInput
    )
    body_findings = forms.JSONField(
        required=False, initial=dict, widget=forms.HiddenInput
    )
    goals = forms.JSONField(required=False, initial=list, widget=forms.HiddenInput)
    treatment_plan = forms.JSONField(
        required=False, initial=list, widget=forms.HiddenInput
    )
    signature_png = forms.CharField(
        required=False, max_length=100000, widget=forms.HiddenInput
    )
    attestation = forms.BooleanField(
        required=False,
        label="Confirmo a autoria e a revisão dos dados desta avaliação.",
    )
    documents = MultipleFileField(
        required=False,
        label="Anexos / documentos",
        widget=MultipleFileInput(attrs={"accept": ".pdf,.png,.jpg,.jpeg,.tif,.tiff"}),
    )
    remove_documents = forms.ModelMultipleChoiceField(
        queryset=PhysiotherapyAssessmentDocument.objects.none(),
        required=False,
        widget=forms.MultipleHiddenInput,
    )

    def __init__(self, *args, user, assessment=None, finalizing=False, **kwargs):
        self.finalizing = finalizing
        self.user = user
        super().__init__(*args, **kwargs)
        for key, label in TEXT_FIELDS.items():
            self.fields[key] = forms.CharField(
                label=label,
                required=False,
                max_length=12000,
                widget=forms.Textarea(attrs={"rows": 3}),
            )
        self.fields["customer"].queryset = Customer.objects.filter(
            tenant_id=user.tenant_id, active=True
        )
        self.fields["professional"].queryset = Professional.objects.filter(
            tenant_id=user.tenant_id, user=user, active=True
        )
        data = self.data if self.is_bound else self.initial
        patient = data.get("customer") or (
            assessment.customer_id if assessment else None
        )
        professional = data.get("professional") or (
            assessment.professional_id if assessment else None
        )
        if assessment:
            self.fields["customer"].disabled = True
            self.fields["professional"].disabled = True
            self.fields["customer"].initial = assessment.customer_id
            self.fields["professional"].initial = assessment.professional_id
            self.fields["customer"].queryset = Customer.objects.filter(
                pk=assessment.customer_id, tenant_id=user.tenant_id
            )
            patient = assessment.customer_id
            professional = assessment.professional_id
            self.fields["remove_documents"].queryset = assessment.documents.filter(
                removed_at__isnull=True
            )
        if str(patient or "").isdigit() and str(professional or "").isdigit():
            self.fields["appointment"].queryset = (
                Appointment.objects.filter(
                    tenant_id=user.tenant_id,
                    customer_id=patient,
                    professional_id=professional,
                    professional__user=user,
                )
                .exclude(status__in=["cancelled", "canceled"])
                .order_by("-starts_at")
            )
        if finalizing:
            for name in ("chief_complaint", "appointment", "attestation"):
                self.fields[name].required = True
        for name, field in self.fields.items():
            if not field.widget.is_hidden:
                field.widget.attrs.setdefault("class", "pa-input")

    def clean_signature_png(self):
        value = self.cleaned_data.get("signature_png", "")
        if not value:
            return ""
        try:
            if not value.startswith("data:image/png;base64,"):
                raise ValueError()
            raw = base64.b64decode(value.split(",", 1)[1], validate=True)
            if len(raw) > 64000:
                raise ValueError()
            with Image.open(BytesIO(raw)) as picture:
                if (
                    picture.format != "PNG"
                    or picture.width > 1800
                    or picture.height > 600
                    or picture.width < 20
                    or picture.height < 20
                ):
                    raise ValueError()
                picture.load()
        except (
            ValueError,
            OSError,
            binascii.Error,
            Image.DecompressionBombError,
        ) as exc:
            raise forms.ValidationError(
                "Assinatura deve ser PNG válido de até 64 KB."
            ) from exc
        return value

    def clean_body_findings(self):
        # Reuse the exact regions, laterality and validation used by clinical evolutions.
        from core.portal import PhysiotherapyRecordForm

        proxy = PhysiotherapyRecordForm()
        proxy.cleaned_data = {
            "body_findings": self.cleaned_data.get("body_findings") or {}
        }
        return proxy.clean_body_findings()

    def clean(self):
        data = super().clean()
        for name in ("rom", "strength", "special_tests", "goals", "treatment_plan"):
            rows = data.get(name) or []
            if not isinstance(rows, list) or len(rows) > 40:
                self.add_error(name, "Informe até 40 itens válidos.")
                continue
            cleaned = []
            for item in rows:
                if not isinstance(item, dict):
                    self.add_error(name, "Item inválido.")
                    break
                text = item.get("text", "")
                if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                    self.add_error(name, "Preencha a descrição dos itens adicionados.")
                    break
                result = {"text": text.strip()}
                if name in {"rom", "strength", "special_tests"}:
                    if item.get("side", "") not in dict(SIDES):
                        self.add_error(name, "Lateralidade inválida.")
                        break
                    result["side"] = item.get("side", "")
                if name in {"rom", "strength"}:
                    number = item.get("value")
                    high = 360 if name == "rom" else 5
                    if (
                        isinstance(number, bool)
                        or not isinstance(number, (int, float))
                        or not 0 <= number <= high
                    ):
                        self.add_error(
                            name, "Informe medida válida de 0 a " + str(high) + "."
                        )
                        break
                    result["value"] = number
                elif name == "special_tests":
                    if item.get("result") not in {"positive", "negative", "not_tested"}:
                        self.add_error(name, "Resultado de teste inválido.")
                        break
                    result["result"] = item["result"]
                elif name == "goals":
                    if not isinstance(item.get("achieved", False), bool):
                        self.add_error(name, "Situação do objetivo inválida.")
                        break
                    result["achieved"] = item.get("achieved", False)
                elif name == "treatment_plan":
                    frequency = item.get("frequency", "")
                    if not isinstance(frequency, str) or len(frequency) > 100:
                        self.add_error(name, "Frequência inválida.")
                        break
                    result["frequency"] = frequency
                cleaned.append(result)
            if name not in self.errors:
                data[name] = cleaned
        if self.finalizing:
            for name in ("goals", "treatment_plan"):
                if not data.get(name) and name not in self.errors:
                    self.add_error(name, "Informe pelo menos um item para finalizar.")
        return data
