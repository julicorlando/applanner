import math
from django.http import JsonResponse
from django.shortcuts import get_object_or_404,render
from tenants.models import Tenant,Unit
from .models import BlogPost,FAQItem,LandingPage,PlatformFeatureFlag




def feature_enabled(key,default=False):
    row=PlatformFeatureFlag.objects.filter(key=key).only("enabled").first()
    return row.enabled if row else default


def faq_page(request):
    rows=FAQItem.objects.filter(active=True).order_by("sort_order","question")
    return render(request,"contenthub/faq.html",{"faqs":rows})

def public_directory(request):
    rows=Tenant.objects.filter(public_enabled=True,status__in=[Tenant.Status.ACTIVE,Tenant.Status.TRIAL],deleted_at__isnull=True).order_by("name")[:200]
    data=[]
    for tenant in rows:
        units=list(tenant.units.filter(active=True).values(
            "name","city","state","latitude","longitude","phone","whatsapp","website"
        ))
        data.append({
            "name":tenant.name,"slug":tenant.public_slug or tenant.slug,
            "category":tenant.category,"description":tenant.description,
            "units":units,
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
    value=math.sin(dlat/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dlon/2)**2
    return radius*2*math.atan2(math.sqrt(value),math.sqrt(1-value))


def public_directory_page(request):
    rows=Tenant.objects.filter(
        public_enabled=True,status__in=[Tenant.Status.ACTIVE,Tenant.Status.TRIAL],deleted_at__isnull=True
    ).prefetch_related("units").order_by("name")
    lat=request.GET.get("lat")
    lon=request.GET.get("lon")
    postal_code=(request.GET.get("cep") or "").strip()
    try:
        if lat is not None and lon is not None:
            latitude,longitude=float(lat),float(lon)
            if not (math.isfinite(latitude) and math.isfinite(longitude) and -90<=latitude<=90 and -180<=longitude<=180):
                raise ValueError
        else:
            latitude=longitude=None
    except (TypeError,ValueError):
        latitude=longitude=None
    if latitude is None and postal_code:
        from tenants.geocoding import coordinates_for_postal_code,normalize_postal_code
        postal_code=normalize_postal_code(postal_code)
        coords=coordinates_for_postal_code(postal_code) if postal_code else None
        if coords:
            latitude,longitude=coords
    cards=[]
    for tenant in rows[:300]:
        units=list(tenant.units.filter(active=True).order_by("-is_primary","name"))
        distances=[]
        if latitude is not None:
            distances=[
                (_distance_km(latitude,longitude,unit.latitude,unit.longitude),unit)
                for unit in units if unit.latitude is not None and unit.longitude is not None
            ]
            distances.sort(key=lambda item:item[0])
        cards.append({
            "tenant":tenant,"units":units,
            "nearest_unit":distances[0][1] if distances else (units[0] if units else None),
            "distance_km":distances[0][0] if distances else None,
        })
    if latitude is not None:
        cards.sort(key=lambda row:(row["distance_km"] is None,row["distance_km"] or 0,row["tenant"].name))
    return render(request,"contenthub/directory.html",{
        "cards":cards,"located":latitude is not None,"postal_code":postal_code,
    })
