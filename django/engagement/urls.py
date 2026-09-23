from django.urls import path
from . import portal

urlpatterns=[
    path("inteligencia/",portal.intelligence,name="engagement-intelligence"),
    path("dominios/",portal.domains,name="engagement-domains"),
    path("pacotes/",portal.packages,name="engagement-packages"),
    path("fidelidade/",portal.loyalty,name="engagement-loyalty"),
    path("espera/",portal.waitlist,name="engagement-waitlist"),
]
