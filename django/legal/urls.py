from django.urls import path
from . import views

urlpatterns=[path("aceite/",views.accept,name="legal-accept")]
