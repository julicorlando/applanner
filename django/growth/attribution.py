"""Keep acquisition context across a public form's GET and POST."""
import uuid

from .models import AcquisitionEvent


UTM_FIELDS={"utm_source":"source","utm_medium":"medium","utm_campaign":"campaign",
            "utm_content":"content","utm_term":"term"}


def capture_attribution(request):
    if request.method!="GET":
        return
    values={field:(request.GET.get(parameter) or "").strip()[:120]
            for parameter,field in UTM_FIELDS.items() if parameter in request.GET}
    if values:
        request.session["acquisition_context"]=values


def record_acquisition(request,event_name,*,tenant=None,user=None,segment="",marketing_consent=False):
    if not request.session.session_key:
        request.session.save()
    context=request.session.get("acquisition_context") or {}
    return AcquisitionEvent.objects.create(
        session_key=request.session.session_key[:40],event_id=uuid.uuid4(),
        event_name=event_name,tenant=tenant,user=user,segment=segment[:40],
        source=context.get("source",""),medium=context.get("medium",""),
        campaign=context.get("campaign",""),content=context.get("content",""),
        term=context.get("term",""),event_url=request.build_absolute_uri()[:500],
        referrer=(request.META.get("HTTP_REFERER") or "")[:500],
        marketing_consent=marketing_consent,
    )
