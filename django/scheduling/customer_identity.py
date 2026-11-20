"""Tenant-scoped identity resolution without public overwrites of customer history."""
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Replace, Trim

from communications.phone import whatsapp_number
from tenants.models import Tenant
from .models import Customer


def contact_values(name, phone, email=""):
    name=str(name or "").strip()
    phone=whatsapp_number(phone)
    email=str(email or "").strip().lower()
    if not 2 <= len(name) <= 150:
        raise ValidationError("Informe seu nome entre 2 e 150 caracteres.")
    if not phone.isdigit() or len(phone) not in (12,13) or not phone.startswith("55"):
        raise ValidationError("Informe um telefone brasileiro válido com DDD. Nome e telefone são obrigatórios.")
    if email:
        validate_email(email)
    return name,phone,email


def identity_matches(tenant, phone, email=""):
    digits=F("phone")
    for separator in ("+"," ","(",")","-",".","\t","\n","\r"):
        digits=Replace(digits,Value(separator),Value(""))
    by_phone=Customer.objects.filter(tenant=tenant).annotate(contact_digits=Trim(digits))\
        .filter(contact_digits__in=[phone,phone[2:]]).order_by("pk")
    by_email=Customer.objects.filter(tenant=tenant,email__iexact=email).order_by("pk") if email else Customer.objects.none()
    return by_phone,by_email


@transaction.atomic
def resolve_customer(tenant, name, phone, email=""):
    name,phone,email=contact_values(name,phone,email)
    # Serialize first bookings even when different professionals/courts are chosen.
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    phones,emails=identity_matches(tenant,phone,email)
    by_phone,by_email=list(phones[:2]),list(emails[:2])
    if len(by_phone)>1 or len(by_email)>1 or (by_phone and by_email and by_phone[0].pk!=by_email[0].pk):
        raise ValidationError("Não foi possível vincular os contatos a um único cadastro. Procure o estabelecimento para conferir seus dados.")
    existing=(by_phone or by_email)
    if existing:
        # Only an authenticated manager may change existing identity/contact data.
        return existing[0],True
    return Customer.objects.create(tenant=tenant,name=name,phone=phone,email=email),False
