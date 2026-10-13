from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.signing import BadSignature,SignatureExpired,loads
from django.db.models import Avg,Count
from django.http import Http404
from django.shortcuts import get_object_or_404,redirect,render
from django.views.decorators.http import require_http_methods

from .models import Appointment,AppointmentRating,Professional


@require_http_methods(["GET","POST"])
def public_rating(request,token):
    try:
        appointment_id=loads(token,salt="appointment-rating",max_age=60*60*24*30)["appointment"]
    except (BadSignature,SignatureExpired,KeyError,TypeError):
        raise Http404("Link de avaliação inválido ou expirado.")
    appointment=get_object_or_404(Appointment.objects.select_related("tenant","professional","service"),
        pk=appointment_id,status=Appointment.Status.COMPLETED)
    if request.method=="POST":
        try:
            score=int(request.POST.get("score",""))
        except ValueError:
            score=0
        if score not in range(1,6):
            messages.error(request,"Selecione uma nota de 1 a 5.")
        elif not appointment.professional_id:
            messages.error(request,"Este atendimento não possui profissional para avaliação.")
        else:
            _,created=AppointmentRating.objects.get_or_create(appointment=appointment,
                defaults={"tenant":appointment.tenant,"professional":appointment.professional,"score":score})
            if created:
                messages.success(request,"Obrigado pela avaliação!")
            return redirect("public-appointment-rating",token=token)
    return render(request,"scheduling/public_rating.html",{
        "appointment":appointment,"rating":AppointmentRating.objects.filter(appointment=appointment).first(),
    })


@login_required
def tenant_ratings(request):
    if not request.user.tenant_id or (not request.user.is_superuser and request.user.role not in {
        "owner","manager","tenant-admin","barber-manager","arena-manager","auto-manager",
    }):
        raise PermissionDenied("Somente a gestão da empresa pode consultar as avaliações.")
    tenant=request.user.tenant
    professionals=Professional.objects.filter(tenant=tenant).annotate(
        review_count=Count("appointmentrating"),rating_average=Avg("appointmentrating__score"),
    ).order_by("name")
    for professional in professionals:
        average=professional.rating_average
        professional.satisfaction_position=round((average-1)*25,1) if average is not None else None
        professional.satisfaction_label=(
            ["Muito insatisfeito","Insatisfeito","Neutro","Satisfeito","Muito satisfeito"]
            [min(4,max(0,int(average+0.5)-1))] if average is not None else "Sem notas"
        )
    recent=AppointmentRating.objects.filter(tenant=tenant).select_related("professional","appointment__customer").order_by("-created_at")[:50]
    return render(request,"portal/tenant_ratings.html",{
        "professionals":professionals,"recent":recent,"tenant":tenant,
        "total":AppointmentRating.objects.filter(tenant=tenant).count(),
    })
