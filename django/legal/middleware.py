from django.shortcuts import redirect

from .models import LegalAcceptance,LegalDocument


EXEMPT_PREFIXES=(
    "/legal/","/account/","/admin/","/static/","/media/","/healthz/",
    "/webhooks/","/tracking/",
)


def current_documents():
    docs=[]
    for doc_type in (LegalDocument.Type.TERMS,LegalDocument.Type.PRIVACY):
        row=LegalDocument.objects.filter(
            type=doc_type,status=LegalDocument.Status.PUBLISHED
        ).order_by("-published_at","-id").first()
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
