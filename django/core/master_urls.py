from django.urls import path
from . import master

urlpatterns=[
    path("acoes/<str:action>/",master.operational_action,name="master-operational-action"),
    path("acoes/<str:action>/<int:pk>/",master.operational_action,name="master-operational-object-action"),
    path("",master.home,name="master-home"),
    path("planos/<int:pk>/modulos/",master.plan_modules,name="master-plan-modules"),
    path("<slug:slug>/",master.resource_list,name="master-resource-list"),
    path("<slug:slug>/novo/",master.resource_form,name="master-resource-create"),
    path("<slug:slug>/<int:pk>/editar/",master.resource_form,name="master-resource-edit"),
]
