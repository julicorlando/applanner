import hashlib
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from core.audit import append_audit, client_ip
from growth.attribution import record_acquisition
from growth.models import AcquisitionEvent
from .models import Lead, LeadHistory, SocialCampaign, SocialCampaignContact, SocialCampaignMedia
from .social_forms import CampaignContactForm, SocialCampaignForm, SocialMediaForm
from .views import _require_commercial


def campaign_access(user):
    _require_commercial(user)
    if user.tenant_id and not user.is_superuser:
        raise PermissionDenied('Campanhas de aquisição da plataforma são restritas ao Comercial do ApPlanner.')
    rows=SocialCampaign.objects.all()
    return rows if user.is_superuser else rows.filter(owner=user)


def _campaign(request,pk):
    return get_object_or_404(campaign_access(request.user),pk=pk)


def _tracking(request,row,channel=None):
    channel=channel if channel in ('instagram','facebook') else row.channel
    if channel=='meta':
        channel='instagram'
    return {'source':channel,'medium':'paid_social' if row.paid else 'social','campaign':row.tracking_code}


def _link(request,row,channel=None,signup=False):
    context=_tracking(request,row,channel)
    query=urlencode({'utm_'+key:value for key,value in context.items()})
    path=reverse('billing-signup') if signup else reverse('commercial-social-public',args=[row.code])
    return request.build_absolute_uri(path)+'?'+query


def _stats(row):
    events=AcquisitionEvent.objects.filter(campaign=row.tracking_code)
    return {'visits':events.filter(event_name='PageView').values('session_key').distinct().count(),
            'contacts':row.contacts.count(),
            'registrations':events.filter(event_name='CompleteRegistration',tenant__isnull=False).values('tenant_id').distinct().count()}


@login_required
@never_cache
@require_GET
def campaigns(request):
    rows=campaign_access(request.user).annotate(contact_count=Count('contacts')).order_by('-created_at')
    status=request.GET.get('status','')
    if status in SocialCampaign.Status.values:
        rows=rows.filter(status=status)
    return render(request,'commercial/social_list.html',{'campaigns':rows[:100],'status':status,'statuses':SocialCampaign.Status.choices})


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def campaign_edit(request,pk=None):
    rows=campaign_access(request.user)
    row=get_object_or_404(rows,pk=pk) if pk else SocialCampaign(owner=request.user)
    form=SocialCampaignForm(request.POST if request.method=='POST' else None,instance=row)
    if request.method=='POST' and form.is_valid():
        row=form.save()
        append_audit(user=request.user,action='social_campaign_saved',entity_type='commercial.SocialCampaign',entity_id=row.pk,request=request)
        messages.success(request,'Campanha salva. A página permanece no estado atual; nenhum anúncio foi publicado.')
        return redirect('commercial-social-detail',pk=row.pk)
    return render(request,'commercial/social_form.html',{'form':form,'campaign':row})


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def campaign_detail(request,pk):
    row=_campaign(request,pk)
    media_form=SocialMediaForm()
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='upload':
            media_form=SocialMediaForm(request.POST,request.FILES)
            if media_form.is_valid():
                with transaction.atomic():
                    row=SocialCampaign.objects.select_for_update().get(pk=row.pk)
                    if row.media.count()>=10:
                        media_form.add_error(None,'Cada campanha aceita até 10 mídias.')
                    else:
                        asset=media_form.save(commit=False)
                        asset.campaign=row
                        for key,value in media_form.media_info.items():
                            setattr(asset,key,value)
                        asset.size_bytes=asset.file.size
                        asset.save()
                        append_audit(user=request.user,action='social_media_uploaded',entity_type='commercial.SocialCampaignMedia',entity_id=asset.pk,request=request)
                        messages.success(request,'Mídia adicionada à campanha.')
                        return redirect('commercial-social-detail',pk=pk)
        elif action in ('activate','pause'):
            row.status=SocialCampaign.Status.ACTIVE if action=='activate' else SocialCampaign.Status.PAUSED
            row.save(update_fields=['status','updated_at'])
            append_audit(user=request.user,action='social_campaign_'+action,entity_type='commercial.SocialCampaign',entity_id=row.pk,request=request)
            messages.success(request,'Página de captação ativada.' if action=='activate' else 'Página pausada. Anúncios externos devem ser pausados também no Meta Business Suite.')
            return redirect('commercial-social-detail',pk=pk)
        else:
            return HttpResponse(status=400)
    contacts=row.contacts.select_related('lead')
    if not request.user.is_superuser:
        contacts=contacts.filter(Q(lead__assigned_to=request.user)|Q(lead__assigned_to__isnull=True))
    contacts=contacts.order_by('-created_at')[:50]
    return render(request,'commercial/social_detail.html',{'campaign':row,'media_form':media_form,'media':row.media.order_by('pk'),
        'stats':_stats(row),'contacts':contacts,'instagram_link':_link(request,row,'instagram'),
        'facebook_link':_link(request,row,'facebook'),'signup_link':_link(request,row,signup=True)})


def _media_response(asset,download=False):
    try:
        response=FileResponse(asset.file.open('rb'),content_type=asset.content_type,as_attachment=download,
            filename='applanner-campanha-'+str(asset.pk)+('.mp4' if asset.is_video else '.jpg'))
    except (FileNotFoundError,OSError):
        from django.http import Http404
        raise Http404('Mídia indisponível.')
    response['X-Content-Type-Options']='nosniff'
    response['Cache-Control']='private, no-store'
    return response


@login_required
@require_GET
def campaign_media(request,pk):
    asset=get_object_or_404(SocialCampaignMedia.objects.filter(campaign__in=campaign_access(request.user)),pk=pk)
    return _media_response(asset,download=request.GET.get('download')=='1')


@require_GET
def public_media(request,code,pk):
    asset=get_object_or_404(SocialCampaignMedia,campaign__code=code,campaign__status=SocialCampaign.Status.ACTIVE,pk=pk)
    return _media_response(asset)


@never_cache
@require_http_methods(['GET','POST'])
def public_campaign(request,code):
    row=get_object_or_404(SocialCampaign,code=code,status=SocialCampaign.Status.ACTIVE)
    previous=request.session.get('acquisition_context') or {}
    previous_source=previous.get('source') if previous.get('campaign')==row.tracking_code else None
    context=_tracking(request,row,request.GET.get('utm_source') or previous_source)
    request.session['acquisition_context']=context
    form=CampaignContactForm(request.POST if request.method=='POST' else None)
    done=request.session.get('social_campaign_received')==str(row.code) and request.GET.get('recebido')=='1'
    if request.method=='POST':
        ip_digest=hashlib.sha256((settings.SECRET_KEY+str(client_ip(request))).encode()).hexdigest()
        key='social-contact-rate:'+ip_digest
        cache.add(key,0,3600)
        try:
            attempts=cache.incr(key)
        except ValueError:
            attempts=1
            cache.set(key,1,3600)
        if attempts>8:
            form.add_error(None,'Muitas tentativas. Aguarde um pouco antes de enviar novamente.')
        elif form.is_valid():
            data=form.cleaned_data
            if not data['website']:
                identity=hashlib.sha256((settings.SECRET_KEY+data['email'].strip().lower()).encode()).hexdigest()
                with transaction.atomic():
                    get_object_or_404(SocialCampaign.objects.select_for_update(),pk=row.pk,status=SocialCampaign.Status.ACTIVE)
                    # A repeated submission never overwrites contact preferences or creates another lead.
                    if not SocialCampaignContact.objects.filter(campaign=row,identity_hash=identity).exists():
                        lead=Lead.objects.select_for_update().filter(
                            Q(email__iexact=data['email'].strip())|Q(phone=data['phone']),anonymized_at__isnull=True
                        ).order_by('pk').first()
                        if lead is None:
                            lead=Lead.objects.create(name=data['name'],business_type=data['business'],email=data['email'].strip().lower(),
                                phone=data['phone'],source=context['source'],source_medium=context['medium'],source_campaign=row.tracking_code,
                                consent_granted=True,consent_version='social_contact_v1',consent_purpose='Contato solicitado sobre o ApPlanner',
                                consent_at=timezone.now(),consent_user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:500],
                                retention_until=timezone.now()+timedelta(days=180),ip_hash=ip_digest)
                            LeadHistory.objects.create(lead=lead,action=LeadHistory.Action.CREATED,notes='Formulário da campanha '+row.name[:140])
                        SocialCampaignContact.objects.create(campaign=row,lead=lead,identity_hash=identity)
                        record_acquisition(request,'Lead',marketing_consent=data['marketing'])
            request.session['social_campaign_received']=str(row.code)
            return redirect(reverse('commercial-social-public',args=[row.code])+'?recebido=1')
    elif not done:
        # First-party visit count, at most one event per session/campaign each day.
        if not request.session.session_key:
            request.session.save()
        key='social-visit:'+str(row.code)+':'+request.session.session_key
        if cache.add(key,True,86400):
            record_acquisition(request,'PageView')
    return render(request,'commercial/social_public.html',{'campaign':row,'form':form,'done':done,
        'media':row.media.order_by('pk')[:10],'signup_link':_link(request,row,context['source'],signup=True)})
