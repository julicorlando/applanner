from django.urls import path
from . import master

urlpatterns=[
    path("",master.home,name="master-home"),
    path("<slug:slug>/",master.resource_list,name="master-resource-list"),
    path("<slug:slug>/novo/",master.resource_form,name="master-resource-create"),
    path("<slug:slug>/<int:pk>/editar/",master.resource_form,name="master-resource-edit"),
]
