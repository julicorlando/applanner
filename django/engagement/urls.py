from django.urls import path
from . import portal

urlpatterns=[
    path("pacotes/",portal.packages,name="engagement-packages"),
    path("fidelidade/",portal.loyalty,name="engagement-loyalty"),
    path("espera/",portal.waitlist,name="engagement-waitlist"),
]
