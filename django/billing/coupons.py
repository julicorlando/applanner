from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Coupon


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


@transaction.atomic
def consume_coupon(*,code,subtotal):
    """Consume one coupon use safely under concurrent requests."""
    normalized=(code or "").strip()
    if not normalized:
        raise ValidationError("Informe o cupom.")
    coupon=Coupon.objects.select_for_update().filter(code__iexact=normalized).first()
    if not coupon or not coupon.active:
        raise ValidationError("Cupom inválido ou inativo.")

    now=timezone.now()
    if coupon.valid_from and coupon.valid_from>now:
        raise ValidationError("Este cupom ainda não está válido.")
    if coupon.valid_until and coupon.valid_until<now:
        raise ValidationError("Este cupom expirou.")
    if coupon.max_uses is not None and coupon.uses_count>=coupon.max_uses:
        raise ValidationError("Este cupom atingiu o limite de utilizações.")

    subtotal=_money(subtotal)
    if subtotal<=0:
        raise ValidationError("Valor da compra inválido para cupom.")

    if coupon.type==Coupon.Type.PERCENT:
        if coupon.value<=0 or coupon.value>100:
            raise ValidationError("Percentual do cupom inválido.")
        discount=(subtotal*Decimal(coupon.value)/Decimal("100")).quantize(Decimal("0.01"))
    else:
        discount=_money(coupon.value)

    discount=min(discount,subtotal)
    coupon.uses_count+=1
    coupon.save(update_fields=["uses_count","updated_at"])
    return coupon,discount
