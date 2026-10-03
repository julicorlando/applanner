"""Keep acquisition context across public journeys and classify lead origin automatically."""
import uuid
from urllib.parse import urlparse

from .models import AcquisitionEvent


UTM_FIELDS={"utm_source":"source","utm_medium":"medium","utm_campaign":"campaign",
            "utm_content":"content","utm_term":"term"}
CLICK_IDS={
    "gclid":("google_ads","paid_search"),
    "fbclid":("meta_ads","paid_social"),
    "ttclid":("tiktok_ads","paid_social"),
    "msclkid":("microsoft_ads","paid_search"),
}
SOCIAL_HOSTS={
    "instagram.com":"instagram","facebook.com":"facebook","fb.com":"facebook",
    "tiktok.com":"tiktok","linkedin.com":"linkedin","youtube.com":"youtube",
    "youtu.be":"youtube","x.com":"x","twitter.com":"x",
}
SEARCH_HOSTS={"google.":"google_organic","bing.com":"bing_organic","duckduckgo.com":"duckduckgo_organic"}


def _host(referrer):
    try:
        return (urlparse(referrer).hostname or "").lower()
    except ValueError:
        return ""


def _automatic_source(request):
    for key,(source,medium) in CLICK_IDS.items():
        if request.GET.get(key):
            return {"source":source,"medium":medium,"content":key}
    referrer=(request.META.get("HTTP_REFERER") or "").strip()
    host=_host(referrer)
    for domain,source in SOCIAL_HOSTS.items():
        if host==domain or host.endswith("."+domain):
            return {"source":source,"medium":"organic_social"}
    for fragment,source in SEARCH_HOSTS.items():
        if fragment in host:
            return {"source":source,"medium":"organic_search"}
    if host:
        return {"source":"referral","medium":"referral","content":host[:120]}
    return {"source":"direct","medium":"direct"}


def capture_attribution(request):
    if request.method!="GET":
        return
    values={field:(request.GET.get(parameter) or "").strip()[:120]
            for parameter,field in UTM_FIELDS.items() if parameter in request.GET}
    automatic=_automatic_source(request)
    for key,value in automatic.items():
        values.setdefault(key,value)
    referral=(request.GET.get("ref") or "").strip()[:32]
    if referral:
        values["referral_code"]=referral
        values["source"]="indique_ganhe"
        values["medium"]="referral"
    if values:
        request.session["acquisition_context"]={**(request.session.get("acquisition_context") or {}),**values}


def current_attribution(request):
    context=dict(request.session.get("acquisition_context") or {})
    if not context:
        context=_automatic_source(request)
    return context


def record_acquisition(request,event_name,*,tenant=None,user=None,segment="",marketing_consent=False):
    if not request.session.session_key:
        request.session.save()
    context=current_attribution(request)
    return AcquisitionEvent.objects.create(
        session_key=request.session.session_key[:40],event_id=uuid.uuid4(),
        event_name=event_name,tenant=tenant,user=user,segment=segment[:40],
        source=context.get("source",""),medium=context.get("medium",""),
        campaign=context.get("campaign",""),content=context.get("content",""),
        term=context.get("term",""),event_url=request.build_absolute_uri()[:500],
        referrer=(request.META.get("HTTP_REFERER") or "")[:500],
        marketing_consent=marketing_consent,
    )
