from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.signing import dumps
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from communications.models import Notification
from finance.models import FinancialTransaction, ProfessionalCommission
from finance.services import create_sale
from .models import Appointment, AppointmentSettlement


@transaction.atomic
def settle_appointment(
    *,appointment_id,professional,user,attended,payment_method="",
    reserved_product_ids=None,product_id=None,quantity=1,
):
    appointment=Appointment.objects.select_for_update().select_related("service","customer","tenant").get(
        pk=appointment_id,tenant=professional.tenant,professional=professional,
    )
    if hasattr(appointment,"settlement") or appointment.status not in {
        Appointment.Status.PENDING,Appointment.Status.CONFIRMED,
        Appointment.Status.WAITING,Appointment.Status.IN_PROGRESS,
    }:
        raise ValidationError("Este atendimento já foi encerrado ou cancelado.")
    if appointment.starts_at>timezone.now():
        raise ValidationError("O atendimento só pode ser encerrado depois do início do horário.")
    if attended and payment_method not in {"pix","card","cash","transfer","other"}:
        raise ValidationError("Escolha a forma de pagamento recebida.")
    from billing.models import TenantPaymentTransaction
    paid_online=TenantPaymentTransaction.objects.filter(tenant=appointment.tenant,
        reference_type="appointment",reference_id=appointment.pk,
        status=TenantPaymentTransaction.Status.PAID).exists()
    finance_method=("pix+"+payment_method if attended and paid_online and
        appointment.booking_payment==Appointment.BookingPayment.PARTIAL else payment_method)
    raw_reserved=reserved_product_ids or []
    try:
        reserved_ids=list(dict.fromkeys(int(value) for value in raw_reserved))
    except (TypeError,ValueError):
        raise ValidationError("Produtos reservados inválidos.")
    if not attended and (product_id or reserved_ids):
        raise ValidationError("Não é possível vender produtos em um atendimento não realizado.")

    sale_items=[]
    if reserved_ids:
        from finance.models import ProductReservation
        reservations=list(
            ProductReservation.objects.select_for_update().select_related("product").filter(
                appointment=appointment,tenant=appointment.tenant,product_id__in=reserved_ids,
                product__active=True,
            )
        )
        if len(reservations)!=len(reserved_ids):
            raise ValidationError("Um dos produtos selecionados não pertence à reserva deste atendimento.")
        by_product={row.product_id:row for row in reservations}
        for product_id_reserved in reserved_ids:
            row=by_product[product_id_reserved]
            sale_items.append({
                "product_id":row.product_id,
                "quantity":row.quantity,
                "unit_price":row.unit_price_snapshot,
            })

    if product_id:
        try:
            product_id=int(product_id)
            quantity=Decimal(str(quantity))
        except (TypeError,ValueError,ArithmeticError):
            raise ValidationError("Produto ou quantidade inválidos.")
        if product_id in reserved_ids:
            raise ValidationError("Este produto já foi marcado entre os produtos reservados vendidos.")
        sale_items.append({"product_id":product_id,"quantity":quantity})

    now=timezone.now()
    sale=None
    if attended:
        if sale_items:
            sale=create_sale(tenant=appointment.tenant,user=user,customer=appointment.customer,
                             professional=professional,payment_method=payment_method,
                             items=sale_items)
        price=appointment.service_price_snapshot
        if price is None:
            price=appointment.service.price
        if price>0:
            FinancialTransaction.objects.get_or_create(
                tenant=appointment.tenant,idempotency_key=f"appointment:{appointment.pk}",
                defaults={"appointment":appointment,"source_type":"appointment","source_id":appointment.pk,
                          "type":FinancialTransaction.Type.INCOME,"description":f"Atendimento #{appointment.pk}",
                          "amount":price,"payment_method":finance_method,"competence_at":timezone.localdate(),
                          "status":FinancialTransaction.Status.PAID,"paid_at":now},
            )
            if professional.commission_percent:
                amount=(price*professional.commission_percent/Decimal("100")).quantize(Decimal("0.01"))
                if amount>0:
                    ProfessionalCommission.objects.get_or_create(
                        tenant=appointment.tenant,professional=professional,source_type="appointment",
                        source_id=appointment.pk,
                        defaults={"gross_amount":price,"rate_percent":professional.commission_percent,
                                  "commission_amount":amount},
                    )
    settlement=AppointmentSettlement.objects.create(
        appointment=appointment,tenant=appointment.tenant,professional=professional,
        attended=attended,payment_method=payment_method if attended else "",sale=sale,settled_by=user,
    )
    appointment.status=Appointment.Status.COMPLETED if attended else Appointment.Status.NO_SHOW
    appointment.service_completed_at=now
    appointment.save(update_fields=["status","service_completed_at","updated_at"])
    if attended:
        from communications.tenant_whatsapp import queue_appointment_whatsapp
        queue_appointment_whatsapp(appointment,"feedback")
    if attended and appointment.customer.email:
        token=dumps({"appointment":appointment.pk},salt="appointment-rating")
        from django.conf import settings
        url=settings.PUBLIC_BASE_URL.rstrip("/")+reverse("public-appointment-rating",args=[token])
        Notification.objects.create(tenant=appointment.tenant,customer=appointment.customer,
            channel=Notification.Channel.EMAIL,template_key="appointment_rating",
            destination=appointment.customer.email,payload={
                "appointment_id":appointment.pk,"subject":"Como foi seu atendimento?",
                "text":f"Olá, {appointment.customer.name}. Avalie seu atendimento de 1 a 5: {url}",
            })
    return settlement
