from django.contrib import admin
from django.urls import include, path
from core.views import healthz, home

urlpatterns=[
    path("healthz/",healthz,name="healthz"),
    path("",home,name="home"),
    path("admin/",admin.site.urls),
    path("api/scheduling/",include("scheduling.urls")),
]
