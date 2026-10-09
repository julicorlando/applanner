"""Activation and account usage indicators, without treating public visits as usage."""
from datetime import timedelta
from django.db.models import Max,Min
from django.utils import timezone
from billing.access import subscription_allows_access
from .activation import activation_status

def company_health(tenant):
    from scheduling.models import Appointment
    from arena.models import Reservation
    from operations.models import TenantActivity
    now=timezone.now();recent=now-timedelta(days=7)
    appointments=Appointment.objects.filter(tenant=tenant)
    reservations=Reservation.objects.filter(tenant=tenant)
    first=min([v for v in [appointments.aggregate(v=Min('created_at'))['v'],reservations.aggregate(v=Min('created_at'))['v']] if v],default=None)
    activity=TenantActivity.objects.filter(tenant=tenant).first()
    units=[activation_status(tenant,u) for u in tenant.units.filter(active=True)]
    subscription=tenant.subscriptions.order_by('-started_at','-pk').first()
    paid=bool(subscription and subscription.payments.filter(purpose='subscription',environment='production',status='paid').exists())
    reasons=[]
    if paid and not first: reasons.append('Contratou e ainda não registrou o primeiro agendamento.')
    if not units or any(not u['ready'] for u in units): reasons.append('Configuração de unidade incompleta.')
    last_login=tenant.users.filter(is_active=True,deleted_at__isnull=True,is_superuser=False).aggregate(v=Max('last_login'))['v']
    last_activity=activity.last_active_at if activity else None
    reference=last_activity or last_login
    if reference and reference<recent: reasons.append('Sem atividade da conta nos últimos 7 dias.')
    if subscription and not subscription_allows_access(subscription): reasons.append('Assinatura sem acesso liberado.')
    return {'company':tenant,'last_login':last_login,'last_activity':last_activity,'first_booking':first,'recent_bookings':appointments.filter(created_at__gte=recent).count()+reservations.filter(created_at__gte=recent).count(),'paid':paid,'units':units,'reasons':reasons,'attention':bool(reasons)}
