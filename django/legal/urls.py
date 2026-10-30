from django.urls import path
from . import views

urlpatterns=[
    path("aceite/",views.accept,name="legal-accept"),
    path("privacidade/meus-dados/",views.privacy_center,name="legal-privacy-center"),
    path("privacidade/meus-dados/exportar/",views.privacy_export,name="legal-privacy-export"),
    path("privacidade/solicitacao/",views.public_privacy_request,name="legal-public-privacy-request"),
    path("<slug:slug>/",views.public_document,name="legal-public-document"),
]
