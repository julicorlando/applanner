import hashlib

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404,render

from .models import DeliveryTerm,Estimate
from .services import accept_delivery_term,respond_estimate


def estimate(request,token):
    row=get_object_or_404(
        Estimate.objects.select_related(
            "job__vehicle","job__appointment__customer"
        ).prefetch_related("items"),
        public_token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    error=""
    if request.method=="POST":
        action=request.POST.get("action")
        if action not in {"approve","reject"}:
            error="Ação inválida."
        else:
            try:
                respond_estimate(
                    token=token,
                    approved=action=="approve",
                    customer_note=request.POST.get("customer_note",""),
                )
                row.refresh_from_db()
            except ValidationError as exc:
                error=str(exc)
    return render(request,"auto/public_estimate.html",{"estimate":row,"error":error})


def delivery(request,token):
    row=get_object_or_404(
        DeliveryTerm.objects.select_related(
            "job__vehicle","job__appointment__customer"
        ),
        public_token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    error=""
    if request.method=="POST":
        try:
            accept_delivery_term(
                token=token,
                name=request.POST.get("accepted_name",""),
                ip=request.META.get("REMOTE_ADDR"),
            )
            row.refresh_from_db()
        except ValidationError as exc:
            error=str(exc)
    return render(request,"auto/public_delivery.html",{"term":row,"error":error})
