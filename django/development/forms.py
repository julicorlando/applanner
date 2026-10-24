import hashlib
import re
import uuid
from decimal import Decimal
from string import Formatter
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from communications.phone import whatsapp_number
from core.crypto import encrypt_text
from finance.models import PlatformBankAccount
from .models import Client, Charge


class RevenueFilterForm(forms.Form):
    month = forms.DateField(
        label="Mês inicial",
        input_formats=["%Y-%m"],
        widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"}),
    )
    client = forms.ModelChoiceField(
        label="Cliente",
        queryset=Client.objects.none(),
        required=False,
        empty_label="Todos os clientes",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.order_by("name", "pk")

    def clean_month(self):
        value = self.cleaned_data["month"]
        if not 2000 <= value.year <= 2100:
            raise ValidationError("Selecione um mês entre 2000 e 2100.")
        return value.replace(day=1)


def validate_document(value, kind):
    value = re.sub(r"\D", "", value)
    size = 11 if kind == "cpf" else 14
    if len(value) != size or len(set(value)) == 1:
        raise ValidationError("Informe um CPF/CNPJ válido.")
    for length in (size - 2, size - 1):
        weights = (
            list(range(length + 1, 1, -1))
            if kind == "cpf"
            else (
                [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
                if length == 12
                else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
            )
        )
        remainder = (
            sum(int(digit) * weight for digit, weight in zip(value[:length], weights))
            % 11
        )
        if int(value[length]) != (0 if remainder < 2 else 11 - remainder):
            raise ValidationError("Informe um CPF/CNPJ válido.")
    return value


def validate_template(value):
    fields = set()
    try:
        for _, field, fmt, conversion in Formatter().parse(value):
            if field is not None:
                if (
                    field not in {"nome", "descricao", "valor", "vencimento", "link"}
                    or fmt
                    or conversion
                ):
                    raise ValueError
                fields.add(field)
    except ValueError as exc:
        raise ValidationError(
            "Use somente {nome}, {descricao}, {valor}, {vencimento} e {link}."
        ) from exc
    if "link" not in fields:
        raise ValidationError("Inclua {link} para o cliente acessar o pagamento.")
    return value


class ClientForm(forms.ModelForm):
    document = forms.CharField(label="CPF / CNPJ", max_length=25)
    email = forms.EmailField(label="E-mail de acesso")

    class Meta:
        model = Client
        labels = {"kind": "Tipo de cliente"}
        fields = [
            "kind",
            "document",
            "name",
            "company_name",
            "email",
            "phone",
            "website",
            "active",
            "reminders_enabled",
            "message_template",
        ]
        widgets = {"message_template": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["document"].initial = self.instance.document
            self.fields["email"].initial = self.instance.user.email
            self.fields["email"].disabled = True
        self.fields[
            "message_template"
        ].help_text = "Variáveis: {nome}, {descricao}, {valor}, {vencimento}, {link}. O link é obrigatório."

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        users = get_user_model().objects.filter(email__iexact=email)
        if self.instance.pk:
            users = users.exclude(pk=self.instance.user_id)
        if users.exists():
            raise ValidationError(
                "Este e-mail já possui uma conta. Use outro e-mail; acessos existentes são preservados."
            )
        return email

    def clean_phone(self):
        number = whatsapp_number(self.cleaned_data["phone"])
        if not re.fullmatch(r"55[1-9][0-9]{9,10}", number):
            raise ValidationError("Informe um WhatsApp brasileiro com DDD.")
        return number

    def clean_message_template(self):
        return validate_template(self.cleaned_data["message_template"])

    def clean(self):
        data = super().clean()
        if data.get("kind") and data.get("document"):
            try:
                value = validate_document(data["document"], data["kind"])
            except ValidationError as exc:
                self.add_error("document", exc)
            else:
                digest = hashlib.sha256(value.encode()).hexdigest()
                if (
                    Client.objects.filter(document_hash=digest)
                    .exclude(pk=self.instance.pk)
                    .exists()
                ):
                    self.add_error("document", "CPF/CNPJ já cadastrado nesta área.")
                self.instance.document_hash = digest
                self.instance.document_encrypted = encrypt_text(value)
        return data


class ChargeForm(forms.ModelForm):
    creation_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    boleto_pdf = forms.FileField(
        label="Boleto em PDF (opcional, até 5 MB)",
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf"}),
    )

    class Meta:
        model = Charge
        fields = [
            "description",
            "amount",
            "due_date",
            "bank",
            "boleto_url",
            "barcode",
            "online_payments_enabled",
        ]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["creation_key"].initial = self.instance.creation_key
        self.fields["bank"].queryset = PlatformBankAccount.objects.filter(
            status="active", deleted_at__isnull=True
        )
        self.fields["bank"].label = "Conta bancária já cadastrada"
        self.fields["online_payments_enabled"].help_text = (
            "Pix com confirmação automática e cartão usam o Mercado Pago ativo e validado do Master. "
            "O recebedor é a conta do provedor; a conta bancária selecionada acima continua sendo usada para Pix direto/boleto."
        )
        self.fields["bank"].label_from_instance = lambda bank: (
            f"{bank.bank_name} · {bank.holder_name}"
        )
        if not self.instance.pk:
            self.fields["bank"].initial = (
                self.fields["bank"].queryset.filter(is_default=True).first()
            )

    def clean_boleto_url(self):
        value = self.cleaned_data["boleto_url"]
        if value and not value.startswith("https://"):
            raise ValidationError("Use o link HTTPS fornecido pelo banco.")
        return value

    def clean_boleto_pdf(self):
        source = self.cleaned_data.get("boleto_pdf")
        if source:
            if (
                not 0 < source.size <= 5 * 1024 * 1024
                or not source.name.lower().endswith(".pdf")
                or source.read(5) != b"%PDF-"
            ):
                raise ValidationError("Envie um PDF válido de até 5 MB.")
            source.seek(0)
        return source

    def clean_barcode(self):
        value = re.sub(r"[ .-]", "", self.cleaned_data["barcode"])
        if value and (not value.isdigit() or len(value) not in {44, 47, 48}):
            raise ValidationError(
                "Informe uma linha digitável de 44, 47 ou 48 dígitos."
            )
        return value

    def clean(self):
        data = super().clean()
        if not (
            data.get("online_payments_enabled")
            or data.get("bank")
            or data.get("boleto_url")
            or data.get("boleto_pdf")
            or self.instance.boleto_encrypted
        ):
            raise ValidationError("Selecione uma conta bancária ou forneça um boleto.")
        if data.get("online_payments_enabled") and not (
            data.get("bank")
            or data.get("boleto_url")
            or data.get("boleto_pdf")
            or self.instance.boleto_encrypted
        ):
            from .payments import configured_gateway

            if not configured_gateway() or (
                data.get("amount") and data["amount"] < Decimal("0.50")
            ):
                raise ValidationError(
                    "Sem boleto/conta bancária, configure o provedor do Master e um valor online de pelo menos R$ 0,50."
                )
        return data


class PaymentDocumentForm(forms.Form):
    document = forms.CharField(
        label="CPF ou CNPJ cadastrado",
        max_length=18,
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "off", "autofocus": True}
        ),
    )

    def clean_document(self):
        value = re.sub(r"\D", "", self.cleaned_data["document"])
        if len(value) not in {11, 14}:
            raise ValidationError(
                "Informe o CPF ou CNPJ cadastrado para esta cobrança."
            )
        return value


class SettlementForm(forms.Form):
    note = forms.CharField(
        label="Referência do comprovante / motivo", max_length=500, min_length=5
    )


class PasswordForm(forms.Form):
    password = forms.CharField(label="Crie sua senha", widget=forms.PasswordInput)
    confirmation = forms.CharField(
        label="Confirme sua senha", widget=forms.PasswordInput
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        from django.contrib.auth.password_validation import validate_password

        data = super().clean()
        if data.get("password") != data.get("confirmation"):
            self.add_error("confirmation", "As senhas não conferem.")
        if data.get("password"):
            try:
                validate_password(data["password"], user=self.user)
            except ValidationError as exc:
                self.add_error("password", exc)
        return data
