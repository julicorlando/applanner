from django import forms
from scheduling.models import Customer,Professional
from .models import ClinicalRegistration,ClinicalAttachment,ClinicalTreatmentPlan
from .clinical import periodontal_chart,treatment_lines


class RegistrationForm(forms.ModelForm):
    class Meta:
        model=ClinicalRegistration
        fields=["professional","council","number","jurisdiction","specialties"]
        labels={"professional":"Profissional","council":"Conselho","number":"Número do registro",
                "jurisdiction":"UF (CRO) ou região (CREFITO)","specialties":"Especialidades"}
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        qs=Professional.objects.filter(tenant_id=user.tenant_id,active=True)
        if user.role not in {"owner","tenant-admin"}:qs=qs.filter(user=user)
        self.fields["professional"].queryset=qs


class StructuredClinicalForm(forms.Form):
    customer=forms.ModelChoiceField(queryset=Customer.objects.none(),label="Paciente")
    professional=forms.ModelChoiceField(queryset=Professional.objects.none(),label="Profissional responsável")
    notes=forms.CharField(label="Observações",required=False,max_length=10000,widget=forms.Textarea)
    payload=forms.JSONField(widget=forms.HiddenInput,initial=dict)
    def __init__(self,*args,user,kind,**kwargs):
        self.kind=kind
        super().__init__(*args,**kwargs)
        self.fields["customer"].queryset=Customer.objects.filter(tenant_id=user.tenant_id,active=True)
        self.fields["professional"].queryset=Professional.objects.filter(tenant_id=user.tenant_id,user=user,active=True)
    def clean_payload(self):
        data=self.cleaned_data["payload"]
        if self.kind=="periodontal":return {"chart":periodontal_chart(data)}
        lines,total=treatment_lines(data)
        return {"lines":lines,"total":str(total)}


class RectificationForm(forms.Form):
    reason=forms.CharField(label="Motivo da retificação",max_length=2000,widget=forms.Textarea(attrs={"rows":2}))
    correction=forms.CharField(label="Retificação / complemento clínico",max_length=20000,widget=forms.Textarea(attrs={"rows":5}))


class AttachmentForm(forms.Form):
    kind=forms.ChoiceField(label="Tipo de documento",choices=ClinicalAttachment.Kind.choices)
    upload=forms.FileField(label="PDF estático ou imagem (até 10 MB)")
    attestation=forms.BooleanField(required=False,label="Confirmo a ciência/autorização do paciente e a autenticidade do documento anexado")


class CareGrantForm(forms.Form):
    grantee=forms.ModelChoiceField(label="Profissional autorizado",queryset=Professional.objects.none())
    reason=forms.CharField(label="Justificativa clínica e autorização",max_length=2000,widget=forms.Textarea(attrs={"rows":2}))
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["grantee"].queryset=Professional.objects.filter(tenant_id=user.tenant_id,active=True,user__isnull=False).exclude(user=user)


class FollowUpForm(forms.Form):
    due_at=forms.DateField(label="Data de retorno",widget=forms.DateInput(attrs={"type":"date"}))
    note=forms.CharField(label="Orientações para o retorno",max_length=2000,widget=forms.Textarea(attrs={"rows":2}))


class TreatmentStatusForm(forms.Form):
    status=forms.ChoiceField(choices=ClinicalTreatmentPlan.Status.choices,label="Situação do tratamento")
    attestation=forms.BooleanField(required=False,label="O paciente aprovou o plano e o orçamento apresentados")
