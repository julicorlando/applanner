from django.urls import path
from . import portal

urlpatterns = [
    path("", portal.home, name="portal-home"),
    path("tenant/<int:tenant_id>/", portal.select_tenant, name="portal-select-tenant"),
    path("<slug:module_slug>/<slug:resource_slug>/", portal.resource_list, name="portal-resource-list"),
    path("<slug:module_slug>/<slug:resource_slug>/novo/", portal.resource_create, name="portal-resource-create"),
    path("<slug:module_slug>/<slug:resource_slug>/<int:pk>/", portal.resource_detail, name="portal-resource-detail"),
    path("<slug:module_slug>/<slug:resource_slug>/<int:pk>/editar/", portal.resource_edit, name="portal-resource-edit"),
]
