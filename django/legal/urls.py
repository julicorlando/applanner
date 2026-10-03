from django.urls import path
from . import views

urlpatterns=[
    path("aceite/",views.accept,name="legal-accept"),
    path("<slug:slug>/",views.public_document,name="legal-public-document"),
]
