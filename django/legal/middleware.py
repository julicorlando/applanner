from django.db import models
from django.shortcuts import redirect

from .models import LegalAcceptance,LegalDocument


EXEMPT_PREFIXES=(
    "/legal/","/account/","/admin/","/static/","/media/","/healthz/",
    "/webhooks/","/tracking/",
)


def current_documents(audience=LegalDocument.Audience.COMPANY):
    docs=[]
    for doc_type in (
        LegalDocument.Type.TERMS,LegalDocument.Type.PRIVACY,LegalDocument.Type.CANCELLATION,
    ):
        row=LegalDocument.objects.filter(
            type=doc_type,status=LegalDocument.Status.PUBLISHED,
            audience__in=[LegalDocument.Audience.ALL,audience],
        ).order_by(
            models.Case(
                models.When(audience=audience,then=models.Value(0)),
                default=models.Value(1),
                output_field=models.IntegerField(),
            ),
            "-published_at","-id",
        ).first()
        if row:
            docs.append(row)
    return docs


class LegalAcceptanceMiddleware:
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        user=getattr(request,"user",None)
        if user and user.is_authenticated and not request.path.startswith(EXEMPT_PREFIXES):
            docs=current_documents()
            if docs:
                accepted=set(LegalAcceptance.objects.filter(
                    user=user,document_id__in=[d.pk for d in docs]
                ).values_list("document_id",flat=True))
                if any(doc.pk not in accepted for doc in docs):
                    return redirect("legal-accept")
        return self.get_response(request)
