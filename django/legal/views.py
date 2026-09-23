from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect,render

from .middleware import current_documents
from .models import LegalAcceptance


def _client_ip(request):
    forwarded=(request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or None


@login_required
def accept(request):
    docs=current_documents()
    accepted=set(LegalAcceptance.objects.filter(
        user=request.user,document_id__in=[d.pk for d in docs]
    ).values_list("document_id",flat=True))
    pending=[doc for doc in docs if doc.pk not in accepted]
    if not pending:
        return redirect("/")
    if request.method=="POST":
        if request.POST.get("accept")!="yes":
            return render(request,"legal/accept.html",{"documents":pending,"error":"É necessário aceitar os documentos para continuar."},status=400)
        for doc in pending:
            LegalAcceptance.objects.get_or_create(
                user=request.user,document=doc,
                defaults={
                    "tenant":getattr(request.user,"tenant",None),
                    "ip_address":_client_ip(request),
                    "user_agent":(request.META.get("HTTP_USER_AGENT") or "")[:500],
                },
            )
        return redirect(request.GET.get("next") or "/")
    return render(request,"legal/accept.html",{"documents":pending})
