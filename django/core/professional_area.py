from decimal import Decimal
from datetime import date,datetime,timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from finance.models import Product,ProfessionalCommission
from scheduling.models import Appointment, Professional
from scheduling.settlement import settle_appointment
from communications.tenant_whatsapp import send_prepared_message
from billing.entitlements import active_subscription,module_enabled
from engagement.models import WaitlistEntry
from engagement.waitlist_booking import book_waitlist_for_professional
from scheduling.availability import AvailabilityService


class ProfessionalAccessForm(forms.Form):
    email=forms.EmailField(label="E-mail de acesso")
    password1=forms.CharField(label="Senha temporária",required=False,widget=forms.PasswordInput,
                              help_text="Obrigatória na criação. Ao entrar, o profissional deverá alterá-la.")
    password2=forms.CharField(label="Confirme a senha",required=False,widget=forms.PasswordInput)
    enabled=forms.BooleanField(label="Permitir acesso",required=False,initial=True)

    def __init__(self,*args,professional,**kwargs):
        super().__init__(*args,**kwargs)
        self.professional=professional

    def clean_email(self):
        email=self.cleaned_data["email"].strip().lower()
        user=get_user_model().objects.filter(email__iexact=email).first()
        if user and user.pk!=self.professional.user_id:
            raise ValidationError("Este e-mail já pertence a outra conta.")
        return email

    def clean(self):
        data=super().clean()
        password=data.get("password1") or ""
        if not self.professional.user_id and not password:
            self.add_error("password1","Informe uma senha temporária para criar o acesso.")
        if password!=data.get("password2",""):
            self.add_error("password2","As senhas não coincidem.")
        if password:
            try:
                validate_password(password,self.professional.user)
            except ValidationError as exc:
                self.add_error("password1",exc)
        return data


@login_required
def professional_access(request,pk):
    if not request.user.is_superuser and request.user.role not in {
        "owner","manager","tenant-admin","barber-manager","arena-manager","auto-manager"
    }:
        raise PermissionDenied("Somente a gestão da empresa pode liberar contas profissionais.")
    tenant=request.user.tenant
    if not tenant and request.user.is_superuser:
        from .portal import _require_tenant
        tenant=_require_tenant(request)
    professional=get_object_or_404(Professional.objects.select_related("user"),pk=pk,tenant=tenant)
    initial={"email":professional.user.email if professional.user_id else professional.email,
             "enabled":professional.user.is_active if professional.user_id else True}
    form=ProfessionalAccessForm(request.POST or None,professional=professional,initial=initial)
    if request.method=="POST" and form.is_valid():
        with transaction.atomic():
            # The linked user is optional; avoid an outer join in FOR UPDATE.
            professional=Professional.objects.select_for_update().get(pk=professional.pk)
            data=form.cleaned_data
            if professional.user_id:
                user=professional.user
                if user.tenant_id!=tenant.pk:
                    raise PermissionDenied("Conta vinculada a outra empresa.")
                user.email=data["email"]
                previously_active=user.is_active
                user.is_active=bool(data["enabled"] and professional.active)
                user.role="professional"
                if data["password1"]:
                    user.set_password(data["password1"])
                    user.must_change_password=True
                    user.session_version+=1
                elif previously_active!=user.is_active:
                    user.session_version+=1
                user.role_links.all().delete()
                user.save()
            else:
                user=get_user_model().objects.create_user(
                    email=data["email"],password=data["password1"],tenant=tenant,
                    role="professional",is_active=bool(data["enabled"] and professional.active),
                    must_change_password=True,
                )
                professional.user=user
                professional.save(update_fields=["user"])
            professional.email=data["email"]
            professional.save(update_fields=["email"])
        messages.success(request,"Acesso do profissional atualizado. Compartilhe a senha temporária por um canal seguro.")
        return redirect("portal-resource-list","agenda","profissionais")
    return render(request,"portal/professional_access.html",{
        "form":form,"professional":professional,"tenant":tenant,
    })


@login_required
def professional_area(request):
    if request.user.role!="professional" or not request.user.tenant_id:
        raise PermissionDenied("Área exclusiva do profissional.")
    professional=get_object_or_404(
        Professional,tenant_id=request.user.tenant_id,user=request.user,active=True
    )
    if request.method=="POST" and request.POST.get("action")=="contact_return":
        from engagement.contacting import send_return_invitation
        from scheduling.models import Customer
        customer=get_object_or_404(
            Customer.objects.distinct(),pk=request.POST.get("customer"),tenant=professional.tenant,active=True,
            appointments__professional=professional,appointments__status=Appointment.Status.COMPLETED,
        )
        try:
            send_return_invitation(
                tenant=professional.tenant,customer=customer,user=request.user,professional=professional
            )
        except ValueError as exc:
            messages.error(request,str(exc))
        except Exception:
            messages.error(request,"Não foi possível enviar a mensagem agora.")
        else:
            messages.success(request,"Convite de retorno enviado com seu link de agendamento.")
        return redirect("professional-area")
    now=timezone.now()
    local_now=timezone.localtime(now)
    month_start=local_now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    appointments=Appointment.objects.filter(tenant=professional.tenant,professional=professional)
    actionable=appointments.filter(status__in=[Appointment.Status.PENDING,Appointment.Status.CONFIRMED,
        Appointment.Status.WAITING,Appointment.Status.IN_PROGRESS]).select_related("customer","service")
    upcoming=actionable.filter(starts_at__gte=now).order_by("starts_at")
    current=actionable.filter(starts_at__lt=now).order_by("-starts_at")[:20]
    month_commissions=ProfessionalCommission.objects.filter(
        tenant=professional.tenant,professional=professional,created_at__gte=month_start
    ).exclude(status=ProfessionalCommission.Status.REVERSED)
    pending=month_commissions.filter(status=ProfessionalCommission.Status.PENDING).aggregate(
        amount=Sum("commission_amount"))["amount"] or Decimal("0")
    paid=month_commissions.filter(status=ProfessionalCommission.Status.PAID).aggregate(
        amount=Sum("commission_amount"))["amount"] or Decimal("0")
    projected=Decimal("0")
    if professional.commission_percent is not None:
        for item in upcoming:
            projected+=(item.service_price_snapshot if item.service_price_snapshot is not None
                        else item.service.price)*professional.commission_percent/Decimal("100")
    waitlist_enabled=not active_subscription(professional.tenant) or module_enabled(professional.tenant,"waitlist")
    waiting=(WaitlistEntry.objects.filter(tenant=professional.tenant,
        status__in=[WaitlistEntry.Status.WAITING,WaitlistEntry.Status.MATCHED],
        customer__active=True,service__active=True).filter(
        Q(professional__isnull=True)|Q(professional=professional)
    ).select_related("customer","service").order_by("preferred_date","created_at") if waitlist_enabled else WaitlistEntry.objects.none())
    if professional.services_restricted or professional.services.exists():
        waiting=waiting.filter(service__in=professional.services.filter(active=True))

    from engagement.contacting import contact_blocked
    completed_for_return=list(
        Appointment.objects.filter(
            tenant=professional.tenant,professional=professional,
            status=Appointment.Status.COMPLETED,customer__active=True,
        ).select_related("customer").order_by("customer_id","starts_at")
    )
    grouped={}
    for item in completed_for_return:
        grouped.setdefault(item.customer_id,[]).append(item)
    return_rows=[]
    for items in grouped.values():
        dates=[timezone.localtime(item.starts_at).date() for item in items]
        intervals=[max((dates[idx]-dates[idx-1]).days,1) for idx in range(1,len(dates))]
        avg_days=max(round(sum(intervals)/len(intervals)),1) if intervals else 30
        if len(intervals)>1:
            variation=sum(abs(value-avg_days) for value in intervals)/len(intervals)
            confidence=max(20,min(100,round(100-(variation/max(avg_days,1))*100)))
        else:
            confidence=60 if intervals else 20
        customer=items[-1].customer
        row=SimpleNamespace(
            customer=customer,customer_id=customer.pk,visits_count=len(items),
            avg_interval_days=avg_days,last_visit_at=items[-1].starts_at,
            next_expected_date=dates[-1]+timedelta(days=avg_days),
            confidence_score=confidence,
            contact_blocked=contact_blocked(professional.tenant,customer),
        )
        return_rows.append(row)
    return_rows.sort(key=lambda row:(row.next_expected_date,row.customer.name))
    return_rows=return_rows[:40]

    from engagement.referrals import active_referral_campaign
    referral_campaign=active_referral_campaign()
    if referral_campaign and not referral_campaign.professional_referrals_enabled:
        referral_campaign=None

    return render(request,"portal/professional_area.html",{
        "professional":professional,"upcoming":upcoming[:15],"current":current,"upcoming_count":upcoming.count(),
        "completed_month":appointments.filter(starts_at__gte=month_start,starts_at__lt=now,
                                               status=Appointment.Status.COMPLETED).count(),
        "pending_commission":pending,"paid_commission":paid,
        "projected_commission":projected,"has_projection":professional.commission_percent is not None,
        "waitlist_enabled":waitlist_enabled,"waiting":waiting[:20],"waiting_count":waiting.count(),
        "return_rows":return_rows,"referral_campaign":referral_campaign,
    })


@login_required
def professional_waitlist(request,pk):
    if request.user.role!="professional" or not request.user.tenant_id:
        raise PermissionDenied("Área exclusiva do profissional.")
    professional=get_object_or_404(Professional,tenant_id=request.user.tenant_id,user=request.user,active=True)
    if active_subscription(professional.tenant) and not module_enabled(professional.tenant,"waitlist"):
        raise PermissionDenied("A lista de espera não está incluída no plano da empresa.")
    entry=get_object_or_404(WaitlistEntry.objects.select_related("customer","service"),
        pk=pk,tenant=professional.tenant,status__in=[WaitlistEntry.Status.WAITING,WaitlistEntry.Status.MATCHED],
        customer__active=True,service__active=True,appointment__isnull=True)
    if entry.professional_id and entry.professional_id!=professional.pk:
        raise PermissionDenied("Este cliente escolheu outro profissional.")
    availability=AvailabilityService()
    if not availability.professional_offers(professional.tenant,professional.pk,entry.service_id):
        raise PermissionDenied("Este serviço não está disponível para este profissional.")
    tz=ZoneInfo(professional.tenant.timezone or "America/Recife")
    today=timezone.localdate(timezone=tz)
    raw_day=request.POST.get("day") if request.method=="POST" else request.GET.get("dia")
    try:
        day=date.fromisoformat(raw_day) if raw_day else (entry.preferred_date if entry.preferred_date and entry.preferred_date>=today else today)
    except ValueError:
        day=today
    if day<today or day>today+timedelta(days=90):
        day=today
    error=None
    if request.method=="POST":
        instant=request.POST.get("action")=="instant"
        if not instant and request.POST.get("action")!="schedule":
            error="Escolha agendar ou iniciar um atendimento avulso."
        else:
            try:
                selected=datetime.fromisoformat(request.POST.get("starts_at","")) if not instant else None
                appointment=book_waitlist_for_professional(
                    entry_id=entry.pk,professional=professional,user=request.user,
                    instant=instant,starts_at=selected,
                )
            except (ValidationError,ValueError,WaitlistEntry.DoesNotExist,Professional.DoesNotExist) as exc:
                error=" ".join(exc.messages) if isinstance(exc,ValidationError) else "Horário inválido ou cliente já atendido. Atualize a lista."
            else:
                messages.success(request,"Atendimento avulso iniciado. Registre o pagamento e produtos ao encerrar." if instant
                                 else "Cliente da lista de espera agendado e removido da fila.")
                return redirect("professional-appointment",pk=appointment.pk) if instant else redirect("professional-area")
    now=timezone.now()
    slots=[slot for slot in availability.slots(professional.tenant,entry.service_id,professional.pk,day,public_rules=False)
           if datetime.fromisoformat(slot["value"])>=now]
    return render(request,"portal/professional_waitlist.html",{
        "professional":professional,"entry":entry,"day":day,"today":today,"slots":slots,"error":error,
    })


class ReservedProductChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self,obj):
        return f"{obj.name} · R$ {obj.sale_price:.2f}"


class SettlementForm(forms.Form):
    outcome=forms.ChoiceField(label="Resultado",choices=[("completed","Atendeu"),("no_show","Não atendeu")])
    payment_method=forms.ChoiceField(label="Forma de pagamento",required=False,choices=[
        ("","Selecione"),("pix","Pix"),("card","Cartão"),("cash","Dinheiro"),
        ("transfer","Transferência"),("other","Outra"),
    ])
    reserved_products=ReservedProductChoiceField(
        label="Produtos reservados que foram vendidos",
        required=False,
        queryset=Product.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        help_text="O cliente apenas demonstrou interesse. Marque somente os produtos que realmente foram vendidos neste atendimento.",
    )
    product=forms.ModelChoiceField(label="Outro produto vendido (opcional)",required=False,queryset=Product.objects.none())
    quantity=forms.DecimalField(label="Quantidade do outro produto",min_value=Decimal("0.001"),max_digits=12,
                                decimal_places=3,initial=1)

    def __init__(self,*args,tenant,appointment=None,prepaid_full=False,**kwargs):
        super().__init__(*args,**kwargs)
        self.prepaid_full=prepaid_full
        self.fields["product"].queryset=Product.objects.filter(tenant=tenant,active=True,stock__gt=0).order_by("name")
        if appointment is not None:
            self.fields["reserved_products"].queryset=Product.objects.filter(
                tenant=tenant,active=True,reservations__appointment=appointment,
            ).distinct().order_by("name")

    def clean(self):
        data=super().clean()
        reserved=data.get("reserved_products")
        product=data.get("product")
        has_product_sale=bool(reserved or product)
        if reserved is not None and product and reserved.filter(pk=product.pk).exists():
            self.add_error("product","Este produto já foi marcado entre os itens reservados vendidos.")
        if data.get("outcome")=="completed" and not data.get("payment_method") and (not self.prepaid_full or has_product_sale):
            self.add_error("payment_method","Informe como o atendimento foi pago.")
        if data.get("outcome")=="no_show":
            if reserved:
                self.add_error("reserved_products","Não há venda de produtos em atendimento não realizado.")
            if product:
                self.add_error("product","Não há venda de produtos em atendimento não realizado.")
        return data


@login_required
def professional_appointment(request,pk):
    if request.user.role!="professional" or not request.user.tenant_id:
        raise PermissionDenied("Área exclusiva do profissional.")
    professional=get_object_or_404(Professional,tenant_id=request.user.tenant_id,user=request.user,active=True)
    appointment=get_object_or_404(
        Appointment.objects.select_related("customer","service").prefetch_related("product_reservations__product"),
        pk=pk,tenant=professional.tenant,professional=professional,
    )
    from billing.models import TenantPaymentTransaction
    paid=TenantPaymentTransaction.objects.filter(tenant=professional.tenant,
        reference_type="appointment",reference_id=appointment.pk,
        status=TenantPaymentTransaction.Status.PAID).order_by("-paid_at").first()
    prepaid_full=bool(paid and appointment.booking_payment==Appointment.BookingPayment.FULL)
    if request.method=="POST" and request.POST.get("action")=="message":
        try:
            send_prepared_message(appointment,request.POST.get("kind",""),request.user)
        except ValueError as exc:
            messages.error(request,str(exc))
        else:
            messages.success(request,"Mensagem pronta enviada ao WhatsApp do cliente.")
        return redirect("professional-appointment",pk=appointment.pk)
    form=SettlementForm(
        request.POST or None,tenant=professional.tenant,appointment=appointment,prepaid_full=prepaid_full,
    )
    if request.method=="POST" and form.is_valid():
        try:
            settle_appointment(appointment_id=appointment.pk,professional=professional,user=request.user,
                attended=form.cleaned_data["outcome"]=="completed",
                payment_method=form.cleaned_data["payment_method"] or ("pix" if prepaid_full else ""),
                reserved_product_ids=[item.pk for item in form.cleaned_data["reserved_products"]],
                product_id=form.cleaned_data["product"].pk if form.cleaned_data["product"] else None,
                quantity=form.cleaned_data["quantity"])
        except (ValidationError,Appointment.DoesNotExist) as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,"Atendimento registrado. A venda e as comissões foram lançadas quando aplicáveis.")
            return redirect("professional-area")
    return render(request,"portal/professional_appointment.html",{
        "professional":professional,"appointment":appointment,"form":form,
        "reserved_product_reservations":list(appointment.product_reservations.all()),
        "paid_booking_payment":paid,"prepaid_full":prepaid_full,
        "can_settle":appointment.status in {Appointment.Status.PENDING,Appointment.Status.CONFIRMED,
            Appointment.Status.WAITING,Appointment.Status.IN_PROGRESS} and appointment.starts_at<=timezone.now(),
    })


@login_required
def reception_appointment(request,pk):
    if request.user.role!="reception" or not request.user.tenant_id:
        raise PermissionDenied("Área exclusiva da recepção.")
    appointment=get_object_or_404(
        Appointment.objects.select_related("customer","service","professional")
        .prefetch_related("product_reservations__product"),
        pk=pk,tenant_id=request.user.tenant_id,
    )
    if not appointment.professional_id:
        messages.error(request,"Defina um profissional antes de finalizar este atendimento.")
        return redirect("portal-resource-edit","agenda","agendamentos",appointment.pk)
    professional=appointment.professional
    from billing.models import TenantPaymentTransaction
    paid=TenantPaymentTransaction.objects.filter(
        tenant=appointment.tenant,reference_type="appointment",reference_id=appointment.pk,
        status=TenantPaymentTransaction.Status.PAID,
    ).order_by("-paid_at").first()
    prepaid_full=bool(paid and appointment.booking_payment==Appointment.BookingPayment.FULL)

    if request.method=="POST" and request.POST.get("action")=="message":
        try:
            send_prepared_message(appointment,request.POST.get("kind",""),request.user)
        except ValueError as exc:
            messages.error(request,str(exc))
        else:
            messages.success(request,"Mensagem enviada ao cliente.")
        return redirect("reception-appointment",pk=appointment.pk)

    form=SettlementForm(
        request.POST or None,tenant=appointment.tenant,appointment=appointment,
        prepaid_full=prepaid_full,
    )
    if request.method=="POST" and form.is_valid():
        try:
            settle_appointment(
                appointment_id=appointment.pk,professional=professional,user=request.user,
                attended=form.cleaned_data["outcome"]=="completed",
                payment_method=form.cleaned_data["payment_method"] or ("pix" if prepaid_full else ""),
                reserved_product_ids=[item.pk for item in form.cleaned_data["reserved_products"]],
                product_id=form.cleaned_data["product"].pk if form.cleaned_data["product"] else None,
                quantity=form.cleaned_data["quantity"],
            )
        except (ValidationError,Appointment.DoesNotExist) as exc:
            form.add_error(None,exc)
        else:
            messages.success(request,"Atendimento finalizado pela recepção. Serviço e vendas foram registrados.")
            return redirect("portal-resource-list","agenda","agendamentos")

    return render(request,"portal/professional_appointment.html",{
        "professional":professional,"appointment":appointment,"form":form,
        "reserved_product_reservations":list(appointment.product_reservations.all()),
        "paid_booking_payment":paid,"prepaid_full":prepaid_full,
        "reception_mode":True,
        "can_settle":appointment.status in {
            Appointment.Status.PENDING,Appointment.Status.CONFIRMED,
            Appointment.Status.WAITING,Appointment.Status.IN_PROGRESS,
        } and appointment.starts_at<=timezone.now(),
    })
