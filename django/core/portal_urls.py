from django.urls import path
from . import portal
from .branding import tenant_branding
from billing.tenant_gateway import tenant_gateway
from .professional_area import professional_area, professional_access, professional_appointment
from scheduling.ratings import tenant_ratings

urlpatterns = [
    path("profissional/",professional_area,name="professional-area"),
    path("profissional/agendamento/<int:pk>/",professional_appointment,name="professional-appointment"),
    path("avaliacoes/",tenant_ratings,name="tenant-ratings"),
    path("profissionais/<int:pk>/acesso/",professional_access,name="professional-access"),
    path("pagamentos/mercado-pago/",tenant_gateway,name="tenant-payment-gateway"),
    path("minha-pagina/",tenant_branding,name="tenant-branding"),
    path("", portal.home, name="portal-home"),
    path("tenant/<int:tenant_id>/", portal.select_tenant, name="portal-select-tenant"),
    path("<slug:module_slug>/<slug:resource_slug>/", portal.resource_list, name="portal-resource-list"),
    path("<slug:module_slug>/<slug:resource_slug>/novo/", portal.resource_create, name="portal-resource-create"),
    path("<slug:module_slug>/<slug:resource_slug>/<int:pk>/", portal.resource_detail, name="portal-resource-detail"),
    path("<slug:module_slug>/<slug:resource_slug>/<int:pk>/editar/", portal.resource_edit, name="portal-resource-edit"),
]
