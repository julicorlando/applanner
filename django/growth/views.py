from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.signing import BadSignature,SignatureExpired,loads
from django.http import Http404
from django.shortcuts import get_object_or_404,redirect,render

from .models import PlatformReferral
from .referrals import active_referral_campaign,referral_profile,save_referral_pix


@login_required
def referral_program(request):
    if request.user.role not in {"owner","professional"} and not request.user.is_superuser:
        raise PermissionDenied("O programa de indicação está disponível para empresas e profissionais.")
    campaign=active_referral_campaign()
    if not campaign:
        raise Http404("Nenhuma campanha de indicação ativa.")
    profile=referral_profile(request.user)
    url=request.build_absolute_uri(f"/cadastro/?ref={profile.referral_code}")
    rows=PlatformReferral.objects.filter(referrer_user=request.user).select_related(
        "referred_tenant","campaign"
    ).order_by("-created_at")[:100]
    return render(request,"growth/referral_program.html",{
        "campaign":campaign,"profile":profile,"referral_url":url,"rows":rows,
    })


def referral_pix(request,token):
    try:
        payload=loads(token,salt="platform-referral-pix",max_age=60*60*24*14)
        referral=PlatformReferral.objects.select_related(
            "referrer_user","referrer_professional","referred_tenant"
        ).get(pk=int(payload["referral"]))
    except (BadSignature,SignatureExpired,KeyError,ValueError,TypeError,PlatformReferral.DoesNotExist):
        raise Http404("Link inválido ou expirado.")
    if referral.status not in {PlatformReferral.Status.AWAITING_PIX,PlatformReferral.Status.READY}:
        raise Http404("Esta indicação não está aguardando dados de pagamento.")
    error=""
    if request.method=="POST":
        try:
            save_referral_pix(referral=referral,pix_key=request.POST.get("pix_key",""))
        except ValueError as exc:
            error=str(exc)
        else:
            messages.success(request,"Chave Pix enviada com segurança. O Master já pode concluir o benefício.")
            return redirect("referral-pix",token=token)
    return render(request,"growth/referral_pix.html",{"referral":referral,"error":error})
