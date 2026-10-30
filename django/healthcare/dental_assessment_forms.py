from decimal import Decimal, InvalidOperation
from django import forms
from .assessment_forms import AssessmentForm as BaseAssessmentForm
from .forms import DENTAL_DETAILS
from .models import DentalAssessmentDocument
from .dentistry import validate_odontogram, ALL_TEETH

TEXT_FIELDS = {**DENTAL_DETAILS, "lifestyle_habits": "Hábitos e estilo de vida", "family_history": "História familiar", "complementary_notes": "Observações complementares", "findings": "Exame clínico (resumo)", "initial_evolution": "Evolução clínica", "guidance": "Orientações ao paciente"}
SYSTEMIC = [(x, x) for x in ("Diabetes", "Hipertensão", "Cardiopatia", "Alergias", "Uso de medicamentos", "Outros")]
DENTAL = [(x, x) for x in ("Bruxismo", "Tratamento ortodôntico", "Tratamento endodôntico", "Tratamento periodontal", "Cirurgias prévias", "Outros")]
GUIDANCE = [(x, x) for x in ("Higiene bucal adequada", "Evitar alimentos duros", "Retorno conforme agendamento", "Sinais de alerta", "Outros")]


class AssessmentForm(BaseAssessmentForm):
    remove_documents = forms.ModelMultipleChoiceField(queryset=DentalAssessmentDocument.objects.none(), required=False, widget=forms.MultipleHiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        keep = {"submission_key", "customer", "professional", "appointment", "evaluation_date", "version", "signature_png", "attestation", "documents", "remove_documents"}
        for key in list(self.fields):
            if key not in keep:
                del self.fields[key]
        for key, label in TEXT_FIELDS.items():
            self.fields[key] = forms.CharField(label=label, required=self.finalizing and key in {"chief_complaint", "findings"}, max_length=20000, widget=forms.Textarea(attrs={"rows": 3, "class": "pa-input"}))
        self.fields["documents"].widget.attrs["accept"] = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.dcm"
        self.fields["upload_kind"] = forms.ChoiceField(label="Tipo do exame / anexo", choices=[("radiograph","Radiografia"),("photo","Foto clínica"),("document","Documento")], initial="document", required=False)
        self.fields["professional"].label = "Cirurgião-dentista responsável"
        for name, label, choices in (("systemic_flags", "Condições sistêmicas", SYSTEMIC), ("dental_flags", "Histórico odontológico", DENTAL), ("guidance_flags", "Orientações", GUIDANCE)):
            self.fields[name] = forms.MultipleChoiceField(label=label, choices=choices, required=False, widget=forms.CheckboxSelectMultiple)
        self.fields["odontogram_json"] = forms.JSONField(initial=dict, required=False, widget=forms.HiddenInput(attrs={"data-chart-input": ""}))
        self.fields["goals"] = forms.JSONField(label="Diagnóstico", initial=list, required=self.finalizing, widget=forms.HiddenInput)
        self.fields["treatment_plan"] = forms.JSONField(label="Plano de tratamento", initial=list, required=self.finalizing, widget=forms.HiddenInput)

    def clean_odontogram_json(self):
        return validate_odontogram(self.cleaned_data.get("odontogram_json") or {})

    def clean(self):
        data = forms.Form.clean(self)
        for name in ("goals", "treatment_plan"):
            rows = data.get(name) or []
            if not isinstance(rows, list) or len(rows) > 40:
                self.add_error(name, "Informe até 40 itens válidos.")
                continue
            clean = []
            for item in rows:
                if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip() or len(item["text"]) > 1000:
                    self.add_error(name, "Preencha a descrição do item.")
                    break
                row = {"text": item["text"].strip()}
                if name == "treatment_plan" and len(row["text"]) > 200:
                    self.add_error(name, "Procedimento deve ter até 200 caracteres.")
                    break
                if name == "treatment_plan":
                    tooth = item.get("tooth", "")
                    status = item.get("status", "pending")
                    if tooth not in ALL_TEETH | {""} or status not in {"pending", "review", "approved", "completed", "declined"}:
                        self.add_error(name, "Dente ou situação inválida.")
                        break
                    try:
                        amount = Decimal(str(item.get("amount", "0")))
                        if not amount.is_finite() or not 0 <= amount <= Decimal("999999.99") or amount.as_tuple().exponent < -2:
                            raise InvalidOperation
                    except (InvalidOperation, ValueError):
                        self.add_error(name, "Valor inválido; informe até duas casas decimais.")
                        break
                    row.update(tooth=tooth, status=status, amount=str(amount))
                clean.append(row)
            if name not in self.errors:
                data[name] = clean
        return data
