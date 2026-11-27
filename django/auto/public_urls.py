from django.urls import path
from . import public

urlpatterns=[
    path("orcamento/<str:token>/",public.estimate,name="auto-public-estimate"),
    path("entrega/<str:token>/",public.delivery,name="auto-public-delivery"),
]
