from django.urls import path
from . import views

urlpatterns=[
    path("aceite/",views.accept,name="legal-accept"),
    path("<str:doc_type>/<str:audience>/",views.public_document,name="legal-public"),
]
