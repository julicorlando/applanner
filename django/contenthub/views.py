import math
from django.http import JsonResponse
from django.shortcuts import get_object_or_404,render
from tenants.models import Tenant
from .models import BlogPost,LandingPage
from core.public_identity import verification_status


def public_directory(request):
    rows=Tenant.objects.filter(
        public_enabled=True,
        status__in=[Tenant.Status.ACTIVE,Tenant.Status.TRIAL],
        deleted_at__isnull=True,
    ).prefetch_related("units").order_by("name")[:200]
    data=[]
    for tenant in rows:
        verified=verification_status(tenant)["verified"]
        active_units=list(tenant.units.filter(active=True).order_by("-is_primary","name","pk"))
        has_primary=any(unit.is_primary for unit in active_units)
        for index,unit in enumerate(active_units):
            display_primary=unit.is_primary or (not has_primary and index==0)
            data.append({
                "name":tenant.name if display_primary else f"{tenant.name} · {unit.name}",
                "tenant_name":tenant.name,"verified":verified,
                "logo_url":f"/imagens/empresa/{tenant.pk}/logo/?unit={unit.pk}" if (unit.logo or tenant.logo) else "",
                "unit":{"id":unit.pk,"name":unit.name,"city":unit.city,"state":unit.state,
                        "latitude":unit.latitude,"longitude":unit.longitude,"phone":unit.phone,
                        "whatsapp":unit.whatsapp,"website":unit.website},
                "slug":tenant.public_slug or tenant.slug,
                "booking_url":f"/p/{tenant.public_slug or tenant.slug}/?unit={unit.pk}#agendar",
                "category":tenant.category,"description":tenant.description,
            })
    return JsonResponse({"results":data})


def landing(request,slug):
    page=get_object_or_404(LandingPage,slug=slug,locale=request.LANGUAGE_CODE,active=True)
    return render(request,"contenthub/landing.html",{"page":page})


def blog_post(request,slug):
    post=get_object_or_404(BlogPost,slug=slug,status=BlogPost.Status.PUBLISHED)
    return render(request,"contenthub/blog_post.html",{"post":post})


def _distance_km(lat1,lon1,lat2,lon2):
    radius=6371.0088
    a1,a2=math.radians(float(lat1)),math.radians(float(lat2))
    dlat=a2-a1
    dlon=math.radians(float(lon2)-float(lon1))
    value=min(1.0,max(0.0,math.sin(dlat/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dlon/2)**2))
    return radius*2*math.atan2(math.sqrt(value),math.sqrt(1-value))


def public_directory_page(request):
    rows=Tenant.objects.filter(
        public_enabled=True,status__in=[Tenant.Status.ACTIVE,Tenant.Status.TRIAL],
        deleted_at__isnull=True,
    ).prefetch_related("units").order_by("name")
    lat=request.GET.get("lat")
    lon=request.GET.get("lon")
    try:
        if lat is not None and lon is not None:
            latitude,longitude=float(lat),float(lon)
            if not (math.isfinite(latitude) and math.isfinite(longitude) and -90<=latitude<=90 and -180<=longitude<=180):
                raise ValueError
        else:
            latitude=longitude=None
    except (TypeError,ValueError):
        latitude=longitude=None

    cards=[]
    for tenant in rows[:300]:
        verified=verification_status(tenant)["verified"]
        active_units=list(tenant.units.filter(active=True).order_by("-is_primary","name","pk"))
        has_primary=any(unit.is_primary for unit in active_units)
        for index,unit in enumerate(active_units):
            display_primary=unit.is_primary or (not has_primary and index==0)
            distance=None
            if latitude is not None and unit.latitude is not None and unit.longitude is not None:
                distance=_distance_km(latitude,longitude,unit.latitude,unit.longitude)
            cards.append({
                "tenant":tenant,"unit":unit,"nearest_unit":unit,"verified":verified,
                "distance_km":distance,
                "display_name":tenant.name if display_primary else f"{tenant.name} · {unit.name}",
            })
    if latitude is not None:
        cards=[row for row in cards if row["distance_km"] is not None and row["distance_km"]<=30]
        cards.sort(key=lambda row:(row["distance_km"] is None,row["distance_km"] or 0,row["display_name"]))
    else:
        cards.sort(key=lambda row:(row["tenant"].name,not row["unit"].is_primary,row["unit"].name))
    return render(request,"contenthub/directory.html",{"cards":cards,"located":latitude is not None})

