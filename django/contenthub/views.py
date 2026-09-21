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
