from io import BytesIO
from decimal import Decimal
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from cryptography.fernet import Fernet
from PIL import Image, ImageOps, UnidentifiedImageError
from scheduling.models import Customer,Professional
from .clinic_models import ClinicPaymentMethod


class ChargeForm(forms.Form):
    request_id=forms.UUIDField(widget=forms.HiddenInput)
    customer=forms.ModelChoiceField(queryset=Customer.objects.none(),label='Paciente')
    professional=forms.ModelChoiceField(queryset=Professional.objects.none(),label='Profissional responsável (relatório individual)',required=False)
    description=forms.CharField(label='Descrição administrativa da cobrança',max_length=190)
    amount=forms.DecimalField(label='Valor total cobrado (R$)',max_digits=12,decimal_places=2,min_value=Decimal('.01'))
    count=forms.IntegerField(label='Quantidade de parcelas',min_value=1,max_value=60,initial=1)
    first_due=forms.DateField(label='Primeiro vencimento',widget=forms.DateInput(attrs={'type':'date'}))
    def __init__(self,*args,tenant,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['customer'].queryset=Customer.objects.filter(tenant=tenant,active=True).order_by('name')
        self.fields['professional'].queryset=Professional.objects.filter(tenant=tenant,active=True,user__isnull=False).order_by('name')


class ReceiptForm(forms.Form):
    request_id=forms.UUIDField(widget=forms.HiddenInput)
    amount=forms.DecimalField(label='Valor efetivamente recebido (R$)',max_digits=12,decimal_places=2,min_value=Decimal('.01'))
    method=forms.ModelChoiceField(label='Modalidade de pagamento',queryset=ClinicPaymentMethod.objects.none())
    confirmed=forms.BooleanField(label='Confirmo que este valor já foi recebido/conferido',required=True)
    def __init__(self,*args,tenant,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['method'].queryset=ClinicPaymentMethod.objects.filter(tenant=tenant,active=True).order_by('name')


class ExpenseForm(ReceiptForm):
    day=forms.DateField(label='Data da despesa',required=False,widget=forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d'),
        help_text='Hoje ou um dia anterior. Ela entra no caixa da clínica desse dia.')
    professional=forms.ModelChoiceField(label='Despesa de qual profissional (opcional)',queryset=Professional.objects.none(),required=False,
        empty_label='Despesa geral da clínica',
        help_text='Escolha o dentista quando a despesa for dele: ela sai do caixa da clínica e fica marcada para ele no fechamento.')
    description=forms.CharField(label='Descrição da despesa',max_length=190)
    field_order=['request_id','day','description','amount','method','professional','invoice','items','photo','confirmed']
    invoice=forms.CharField(label='Número da nota/cupom fiscal (opcional)',max_length=80,required=False)
    items=forms.CharField(label='Itens comprados (opcional)',max_length=3000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    photo=forms.FileField(label='Foto do comprovante (opcional, JPEG/PNG até 10 MB)',required=False)
    def __init__(self,*args,**kwargs):
        tenant=kwargs.get('tenant')
        super().__init__(*args,**kwargs)
        self.fields['amount'].label='Valor pago da despesa (R$)'
        self.fields['professional'].queryset=Professional.objects.filter(tenant=tenant,active=True).order_by('name')
        self.fields['confirmed'].label='Confirmo que esta despesa foi efetivamente paga'
        from .clinic_services import business_today
        self.today=business_today(tenant) if tenant else None
        if self.today:
            self.fields['day'].widget.attrs['max']=self.today.isoformat()
            self.fields['day'].initial=self.initial.get('day') or self.today
    def clean_day(self):
        day=self.cleaned_data.get('day') or self.today
        if self.today and day>self.today:raise ValidationError('A data da despesa não pode ser futura.')
        return day
    def clean_photo(self):
        file=self.cleaned_data.get('photo')
        if not file:return None
        if file.size>10*1024*1024:raise ValidationError('Foto deve ter até 10 MB.')
        try:
            with Image.open(file) as image:
                if image.format not in {'JPEG','PNG'} or image.width*image.height>24000000:raise ValueError
                image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((2400,2400))
                buffer=BytesIO();image.save(buffer,'JPEG',quality=88)
                return Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).encrypt(buffer.getvalue()),'image/jpeg'
        except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError):
            raise ValidationError('Envie uma foto JPEG ou PNG válida.') from None


class WithdrawalForm(forms.Form):
    request_id=forms.UUIDField(widget=forms.HiddenInput)
    professional=forms.ModelChoiceField(label='Retirada de qual profissional (opcional)',queryset=Professional.objects.none(),required=False,
        empty_label='Não é de um profissional',help_text='Sai do caixa da clínica; o profissional fica registrado na retirada.')
    amount=forms.DecimalField(label='Valor retirado (R$)',max_digits=12,decimal_places=2,min_value=Decimal('.01'))
    method=forms.ModelChoiceField(label='Forma',queryset=ClinicPaymentMethod.objects.none())
    withdrawn_by=forms.CharField(label='Retirado por',max_length=120,help_text='Quem levou o dinheiro (ex.: Dr. Jairo, sócio, banco).')
    destination=forms.ChoiceField(label='Destino',choices=[])
    notes=forms.CharField(label='Observação (opcional)',max_length=500,required=False)
    confirmed=forms.BooleanField(label='Confirmo que este dinheiro saiu da gaveta e não é um gasto',required=True)
    def __init__(self,*args,tenant,**kwargs):
        super().__init__(*args,**kwargs)
        from .clinic_models import ClinicCashWithdrawal
        self.fields['professional'].queryset=Professional.objects.filter(tenant=tenant,active=True).order_by('name')
        cash=ClinicPaymentMethod.objects.filter(tenant=tenant,active=True,kind='cash').order_by('name')
        self.fields['method'].queryset=cash
        self.fields['method'].empty_label=None
        self.fields['destination'].choices=ClinicCashWithdrawal.Destination.choices
