from django.urls import path
from . import portal, operation_insights
from .branding import tenant_branding
from .unit_settings import unit_schedule_settings
from billing.tenant_gateway import tenant_gateway
from .professional_area import professional_area, professional_access, professional_appointment, professional_waitlist, reception_appointment
from scheduling.ratings import tenant_ratings
from engagement.referrals import referrals

from .booking_funnel import dashboard as booking_funnel

urlpatterns = [
    path("funil-agendamento/",booking_funnel,name="booking-funnel"),
    path('hoje/',operation_insights.today,name='operation-today'),
    path('hoje/<int:pk>/acao/',operation_insights.appointment_action,name='operation-today-action'),
    path('indicadores/',operation_insights.performance,name='operation-performance'),
    path('cliente/<int:pk>/historico/',operation_insights.customer_history,name='customer-history'),
    path("configuracao-unidade/",unit_schedule_settings,name="unit-schedule-settings"),
    path("primeiros-passos/",portal.setup_checklist,name="portal-setup"),
    path("diagnostico/",portal.operation_diagnostics,name="portal-diagnostics"),
    path("recepcao/novo/",portal.reception_access,name="reception-access"),
    path("recepcao/agendamento/<int:pk>/",reception_appointment,name="reception-appointment"),
    path("profissional/",professional_area,name="professional-area"),
    path("profissional/indicacoes/",referrals,name="professional-referrals"),
    path("profissional/espera/<int:pk>/",professional_waitlist,name="professional-waitlist"),
    path("profissional/agendamento/<int:pk>/",professional_appointment,name="professional-appointment"),
    path("avaliacoes/",tenant_ratings,name="tenant-ratings"),
    path("profissionais/<int:pk>/acesso/",professional_access,name="professional-access"),
    path("cadastro-bancario/",tenant_gateway,name="tenant-payment-gateway"),
    path("pagamentos/mercado-pago/",tenant_gateway,name="tenant-payment-gateway-legacy"),
    path("minha-pagina/",tenant_branding,name="tenant-branding"),
    path("", portal.home, name="portal-home"),
    path("tenant/<int:tenant_id>/", portal.select_tenant, name="portal-select-tenant"),
    path("<slug:module_slug>/<slug:resource_slug>/", portal.resource_list, name="portal-resource-list"),
    path("<slug:module_slug>/<slug:resource_slug>/novo/", portal.resource_create, name="portal-resource-create"),
    path("<slug:module_slug>/<slug:resource_slug>/<int:pk>/", portal.resource_detail, name="portal-resource-detail"),
    path("<slug:module_slug>/<slug:resource_slug>/<int:pk>/editar/", portal.resource_edit, name="portal-resource-edit"),
]
