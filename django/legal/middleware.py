from django.shortcuts import redirect

from .models import LegalAcceptance,LegalDocument


EXEMPT_PREFIXES=(
    "/legal/","/account/","/admin/","/static/","/media/","/healthz/",
    "/webhooks/","/tracking/",
)


def current_documents(user=None):
    """Published documents the person must accept. The Política de Uso only for people working in a company."""
    from .use_policy import applies_to
    types=[LegalDocument.Type.TERMS,LegalDocument.Type.PRIVACY]
    if user is not None and applies_to(user):
        types.append(LegalDocument.Type.USE_POLICY)
    docs=[]
    for doc_type in types:
        row=LegalDocument.objects.filter(
            type=doc_type,status=LegalDocument.Status.PUBLISHED,requires_acceptance=True
        ).order_by("-published_at","-id").first()
        if row:
            docs.append(row)
    return docs


class LegalAcceptanceMiddleware:
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        user=getattr(request,"user",None)
        if user and user.is_authenticated and not getattr(request,"billing_locked",False) and not request.path.startswith(EXEMPT_PREFIXES):
            docs=current_documents(user)
            if docs:
                accepted=set(LegalAcceptance.objects.filter(
                    user=user,document_id__in=[d.pk for d in docs]
                ).values_list("document_id",flat=True))
                if any(doc.pk not in accepted for doc in docs):
                    return redirect("legal-accept")
        return self.get_response(request)
