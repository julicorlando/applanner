from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect,render
from django.urls import resolve,Resolver404,reverse
from django.db.models import Q
from .access import current_subscription,subscription_allows_access


class SubscriptionAccessMiddleware:
    PAYMENT_NAMES={'billing-fiscal-profile','billing-nfe-download','billing-nfe-request','billing-subscription-status','billing-subscription-checkout','billing-subscription-pix','billing-subscription-cancel','billing-account-deletion','billing-subscription-payment-method','billing-subscription-pix-refresh'}
    AUTH_NAMES={'accounts:login','accounts:logout','accounts:two-factor-challenge','accounts:change-password',
                'accounts:password-reset-request','accounts:password-reset-confirm'}
    PUBLIC_NAMES={'tenant-short-link','professional-short-link','tenant-public','professional-public','public-availability','public-booking','public-waitlist','public-arena-slots','public-arena-book'}

    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        user=request.user
        if user.is_authenticated and not user.is_superuser and user.tenant_id and user.tenant.archived_at:
            if not request.path.startswith(('/static/','/media/','/imagens/','/healthz/','/webhooks/')):
                try: archive_match=resolve(request.path_info)
                except Resolver404: archive_match=None
                if not archive_match or archive_match.view_name not in self.PAYMENT_NAMES|self.AUTH_NAMES:
                    if request.path.startswith('/api/'):
                        return JsonResponse({'detail':'Empresa arquivada pelo administrador.','code':'company_archived'},status=403)
                    return render(request,'master/archived_access.html',status=403)
        if not getattr(settings,'SUBSCRIPTION_ACCESS_ENFORCED',True):
            return self.get_response(request)
        if request.path.startswith(('/static/','/media/','/imagens/','/healthz/','/webhooks/')):
            return self.get_response(request)
        try:
            match=resolve(request.path_info)
        except Resolver404:
            return self.get_response(request)
        user=request.user
        tenant=user.tenant if user.is_authenticated and user.tenant_id and not user.is_superuser else None
        if match.view_name in self.PUBLIC_NAMES:
            from tenants.models import Tenant
            if match.view_name == 'tenant-short-link':
                tenant=Tenant.objects.filter(public_short_code=match.kwargs.get('code')).first()
            elif match.view_name == 'professional-short-link':
                from scheduling.models import Professional
                professional=Professional.objects.select_related('tenant').filter(public_short_code=match.kwargs.get('code')).first()
                tenant=professional.tenant if professional else None
            else:
                slug=match.kwargs.get('slug')
                tenant=Tenant.objects.filter(Q(public_slug=slug)|Q(slug=slug)).first()
        if not tenant or (user.is_authenticated and user.is_superuser):
            return self.get_response(request)
        request.billing_locked=not subscription_allows_access(current_subscription(tenant))
        if not request.billing_locked or match.view_name in self.PAYMENT_NAMES|self.AUTH_NAMES:
            return self.get_response(request)
        if request.path.startswith('/api/'):
            return JsonResponse({'detail':'Acesso suspenso: regularize o pagamento da assinatura.',
                                 'code':'subscription_payment_required','payment_url':reverse('billing-subscription-status')},status=402)
        if not user.is_authenticated or match.view_name in self.PUBLIC_NAMES:
            return render(request,'billing/unavailable.html',status=403)
        return redirect('billing-subscription-status')
