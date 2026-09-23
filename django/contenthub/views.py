import math
from django.http import JsonResponse
from django.shortcuts import get_object_or_404,render
from tenants.models import Tenant,Unit
from .models import BlogPost,LandingPage


def public_directory(request):
    rows=Tenant.objects.filter(public_enabled=True,status=Tenant.Status.ACTIVE).order_by("name")[:200]
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
        public_enabled=True,status=Tenant.Status.ACTIVE
    ).prefetch_related("units").order_by("name")
    lat=request.GET.get("lat")
    lon=request.GET.get("lon")
    cards=[]
    for tenant in rows[:300]:
        units=list(tenant.units.filter(active=True).order_by("-is_primary","name"))
        distances=[]
        if lat and lon:
            try:
                distances=[
                    _distance_km(lat,lon,unit.latitude,unit.longitude)
                    for unit in units if unit.latitude is not None and unit.longitude is not None
                ]
            except (TypeError,ValueError):
                distances=[]
        cards.append({
            "tenant":tenant,"units":units,
            "distance_km":min(distances) if distances else None,
        })
    if lat and lon:
        cards.sort(key=lambda row:(row["distance_km"] is None,row["distance_km"] or 0,row["tenant"].name))
    return render(request,"contenthub/directory.html",{"cards":cards,"lat":lat,"lon":lon})
