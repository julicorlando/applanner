from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect,render
from django.urls import resolve,Resolver404,reverse
from django.db.models import Q
from .access import current_subscription,subscription_allows_access


class SubscriptionAccessMiddleware:
    PAYMENT_NAMES={'billing-subscription-status','billing-subscription-checkout','billing-subscription-pix'}
    AUTH_NAMES={'accounts:login','accounts:logout','accounts:two-factor-challenge','accounts:change-password',
                'accounts:password-reset-request','accounts:password-reset-confirm'}
    PUBLIC_NAMES={'tenant-public','professional-public','public-availability','public-booking','public-waitlist','public-arena-slots','public-arena-book'}

    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
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
