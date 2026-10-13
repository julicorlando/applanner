"""Keep acquisition context across public forms and infer common channels automatically."""
import uuid
from urllib.parse import urlparse

from .models import AcquisitionEvent


UTM_FIELDS={"utm_source":"source","utm_medium":"medium","utm_campaign":"campaign",
            "utm_content":"content","utm_term":"term"}

SOCIAL_HOSTS={
    "instagram.com":"instagram","l.instagram.com":"instagram",
    "facebook.com":"facebook","m.facebook.com":"facebook","l.facebook.com":"facebook",
    "tiktok.com":"tiktok","www.tiktok.com":"tiktok",
    "linkedin.com":"linkedin","www.linkedin.com":"linkedin",
    "youtube.com":"youtube","youtu.be":"youtube",
    "x.com":"x","twitter.com":"x",
}


def _host(referrer):
    try:
        return (urlparse(referrer or "").hostname or "").lower()
    except ValueError:
        return ""


def infer_attribution(request):
    values={}
    for parameter,field in UTM_FIELDS.items():
        value=(request.GET.get(parameter) or "").strip()
        if value:
            values[field]=value[:120]

    click_sources=(
        ("fbclid","meta_ads"),
        ("gclid","google_ads"),
        ("ttclid","tiktok_ads"),
        ("msclkid","microsoft_ads"),
    )
    if not values.get("source"):
        for parameter,source in click_sources:
            click_id=(request.GET.get(parameter) or "").strip()
            if click_id:
                values.update({"source":source,"medium":"paid","content":click_id[:120]})
                break

    if not values.get("source"):
        host=_host(request.META.get("HTTP_REFERER"))
        for known,source in SOCIAL_HOSTS.items():
            if host==known or host.endswith("."+known):
                values.update({"source":source,"medium":"social"})
                break

    if not values.get("source") and request.session.get("referral_code"):
        values.update({"source":"referral","medium":"referral"})

    if not values.get("source"):
        values.update({"source":"organic","medium":"organic"})
    return values


def capture_attribution(request):
    if request.method!="GET":
        return
    current=request.session.get("acquisition_context") or {}
    inferred=infer_attribution(request)
    # Explicit UTMs/click identifiers from the latest landing page supersede old values;
    # otherwise preserve the first meaningful campaign in the session.
    if any(key in request.GET for key in (*UTM_FIELDS.keys(),"fbclid","gclid","ttclid","msclkid")):
        current=inferred
    elif not current:
        current=inferred
    elif request.session.get("referral_code"):
        current={**current,"source":"referral","medium":"referral"}
    request.session["acquisition_context"]=current


def acquisition_context(request):
    context=request.session.get("acquisition_context") or {}
    return context or infer_attribution(request)


def record_acquisition(request,event_name,*,tenant=None,user=None,segment="",marketing_consent=False):
    if not request.session.session_key:
        request.session.save()
    context=acquisition_context(request)
    return AcquisitionEvent.objects.create(
        session_key=request.session.session_key[:40],event_id=uuid.uuid4(),
        event_name=event_name,tenant=tenant,user=user,segment=segment[:40],
        source=context.get("source",""),medium=context.get("medium",""),
        campaign=context.get("campaign",""),content=context.get("content",""),
        term=context.get("term",""),event_url=request.build_absolute_uri()[:500],
        referrer=(request.META.get("HTTP_REFERER") or "")[:500],
        marketing_consent=marketing_consent,
    )
