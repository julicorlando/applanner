"""Birthday opt-in uses the existing notification queue and tenant-owned gateway."""
from calendar import isleap
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from billing.access import current_subscription,subscription_allows_access
from billing.entitlements import module_enabled,is_healthcare_tenant
from core.audit import append_audit
from scheduling.models import Customer
from .birthday_models import BirthdaySettings,BirthdayDelivery
from .models import Notification,TenantWhatsAppConnection,WhatsAppConversation,WhatsAppMessage
from .phone import whatsapp_number


def local_now(tenant):
    try:zone=ZoneInfo(tenant.timezone)
    except (ZoneInfoNotFoundError,ValueError):zone=timezone.get_default_timezone()
    return timezone.localtime(timezone.now(),zone)


def is_birthday(birth,day):
    if not birth or birth>day:return False
    return (birth.month,birth.day)==(day.month,day.day) or (birth.month==2 and birth.day==29 and not isleap(day.year) and (day.month,day.day)==(2,28))


def usable(config):
    tenant=config.tenant
    if (not config.enabled or tenant.archived_at or tenant.deleted_at or not is_healthcare_tenant(tenant)
        or (settings.SUBSCRIPTION_ACCESS_ENFORCED and not subscription_allows_access(current_subscription(tenant)))):return False
    if config.channel=='whatsapp':
        return module_enabled(tenant,'whatsapp') and TenantWhatsAppConnection.objects.filter(tenant=tenant,enabled=True).exists()
    return config.channel=='email'


def destination(customer,channel):
    return whatsapp_number(customer.phone) if channel=='whatsapp' else customer.email


@transaction.atomic
def queue_tenant(tenant_id):
    config=BirthdaySettings.objects.select_for_update(of=('self',)).select_related('tenant').filter(tenant_id=tenant_id,enabled=True).first()
    if not config or not usable(config):return 0
    now=local_now(config.tenant);day=now.date()
    if not config.hour<=now.hour<21:return 0
    customers=Customer.objects.filter(tenant_id=tenant_id,active=True,consent_marketing=True,birth_date__month=day.month)
    customers=customers.exclude(birthday_deliveries__tenant_id=tenant_id,birthday_deliveries__year=day.year).order_by('pk')
    count=0
    for customer in customers.only('pk','tenant_id','name','phone','email','birth_date','active','consent_marketing')[:500]:
        if not is_birthday(customer.birth_date,day):continue
        target=destination(customer,config.channel)
        if not target or (config.channel=='whatsapp' and not 10<=len(target)<=15):continue
        text=config.message.replace('{nome}',(customer.name.split()[0] if customer.name.split() else 'cliente')).replace('{empresa}',config.tenant.name)
        notice=Notification.objects.create(tenant_id=tenant_id,customer=customer,channel=config.channel,template_key='customer_birthday',
            destination=target,payload={'text':text,'subject':'Feliz aniversário!','birthday_date':day.isoformat()})
        BirthdayDelivery.objects.create(tenant_id=tenant_id,customer=customer,year=day.year,day=day,notification=notice)
        count+=1
    return count


def validate_delivery(notification):
    row=BirthdayDelivery.objects.select_related('customer','tenant').filter(notification=notification,tenant_id=notification.tenant_id).first()
    config=BirthdaySettings.objects.filter(tenant_id=notification.tenant_id).select_related('tenant').first()
    valid=bool(row and config and usable(config) and row.customer.tenant_id==row.tenant_id
        and row.customer.active and row.customer.consent_marketing and notification.customer_id==row.customer_id
        and local_now(row.tenant).date()==row.day and is_birthday(row.customer.birth_date,row.day)
        and config.hour<=local_now(row.tenant).hour<21 and config.channel==notification.channel
        and destination(row.customer,config.channel)==notification.destination)
    if not valid:
        notification.status='skipped';notification.save(update_fields=['status'])
    return row if valid else None


def send_birthday_whatsapp(notification,row):
    from .tenant_whatsapp import gateway
    body=notification.payload['text']
    sent=gateway(row.tenant,'POST','send',{'to':notification.destination,'text':body,
        'idempotencyKey':f'birthday_{row.tenant_id}_{row.customer_id}_{row.year}'})
    conversation,_=WhatsAppConversation.objects.get_or_create(tenant=row.tenant,wa_id=notification.destination,
        defaults={'customer':row.customer,'contact_name':row.customer.name,'last_message_at':timezone.now()})
    WhatsAppMessage.objects.get_or_create(tenant=row.tenant,provider_message_id=sent['id'],defaults={'conversation':conversation,
        'direction':'out','sender_type':'system','message_type':'text','body':body,'status':'sent','sent_at':timezone.now()})
    return sent['id']


class BirthdayForm(forms.ModelForm):
    class Meta:
        model=BirthdaySettings
        fields=['enabled','channel','hour','message']
        labels={'enabled':'Ativar felicitações automáticas','channel':'Canal de envio','hour':'Hora inicial do envio (fuso da clínica)','message':'Mensagem'}
        widgets={'message':forms.Textarea(attrs={'rows':3})}
    def clean_hour(self):
        value=self.cleaned_data['hour']
        if not 8<=value<=20:raise forms.ValidationError('Escolha uma hora entre 8h e 20h.')
        return value


@login_required
@never_cache
def configuration(request):
    from finance.clinic_services import access
    tenant=access(request.user)
    if request.user.role not in {'owner','tenant-admin','manager'}:raise PermissionDenied('A gestão configura as mensagens automáticas.')
    config,_=BirthdaySettings.objects.get_or_create(tenant=tenant)
    form=BirthdayForm(request.POST or None,instance=config)
    if request.method=='POST' and form.is_valid():
        form.save()
        append_audit(tenant=tenant,user=request.user,request=request,action='clinic.birthday.settings.saved',entity_type='BirthdaySettings',entity_id=config.pk,after={'enabled':config.enabled,'channel':config.channel})
        messages.success(request,'Automação de aniversário configurada.')
        return redirect('clinic-birthday-settings')
    rows=BirthdayDelivery.objects.filter(tenant=tenant).select_related('customer','notification').order_by('-day','-pk')[:100]
    return render(request,'finance/clinic_birthdays.html',{'form':form,'rows':rows,'connected':TenantWhatsAppConnection.objects.filter(tenant=tenant,enabled=True).exists()})
