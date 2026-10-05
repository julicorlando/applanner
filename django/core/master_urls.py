from django.urls import path
from . import master, master_console, master_retention
from .branding import platform_homepage
from communications.master_whatsapp import master_whatsapp_flow,master_whatsapp_messages,master_whatsapp_attachment
from .master_email import email_templates,smtp_settings,waive_onboarding_email
from communications.master_marketing import campaigns,create_campaign,cancel_campaign,import_contacts
from billing.fiscal import master_fiscal_document

from finance.platform_dashboard import dashboard as finance_dashboard

from .company_health_views import dashboard as company_health_dashboard
from operations.master_support import ticket_detail as support_ticket

from operations.monitoring import dashboard as runtime_monitor

urlpatterns=[
    path("monitoramento/",runtime_monitor,name="master-runtime-monitor"),
    path("saude-empresas/",company_health_dashboard,name="master-company-health"),
    path("suporte/<int:pk>/atendimento/",support_ticket,name="master-support-ticket"),
    path("cobrancas/<int:pk>/financeiro/",master_retention.consult_accounting,name="master-financial-consult"),
    path("retencao/",master_retention.dashboard,name="master-retention"),
    path("retencao/<int:pk>/motivo/",master_retention.save_note,name="master-retention-note"),
    path("alertas/",master_console.alerts,name="master-alerts"),
    path("cobrancas/",master_console.charges,name="master-charges"),
    path("cobrancas/<int:pk>/",master_console.charge_detail,name="master-charge-detail"),
    path("cobrancas/<int:pk>/consultar/",master_console.charge_consult,name="master-charge-consult"),
    path("relatorios/",master_console.reports,name="master-reports"),
    path("empresas/<int:pk>/ficha/",master_console.company_detail,name="master-company-detail"),
    path("empresas/<int:pk>/<str:action>/confirmar/",master_console.company_lifecycle,name="master-company-lifecycle"),
    path("financeiro/painel/",finance_dashboard,name="master-finance-dashboard"),
    path("empresas/<int:pk>/acessos/",master.tenant_access,name="master-tenant-access"),
    path("empresas/<int:pk>/enviar-termos/",master.send_tenant_terms,name="master-send-tenant-terms"),
    path("usuarios/<int:pk>/excluir/",master.remove_user,name="master-user-remove"),
    path("planos/<int:pk>/excluir/",master.delete_plan,name="master-plan-delete"),
    path("marketing/",campaigns,name="master-marketing"),
    path("marketing/criar/",create_campaign,name="master-marketing-create"),
    path("marketing/importar/",import_contacts,name="master-marketing-import"),
    path("marketing/<int:pk>/cancelar/",cancel_campaign,name="master-marketing-cancel"),
    path("pagina-inicial/",platform_homepage,name="master-homepage"),
    path("pagamentos/cadastro-bancario/",master.platform_payment_gateway,name="master-platform-payment"),
    path("pagamentos/mercado-pago/",master.platform_payment_gateway,name="master-platform-payment-legacy"),
    path("email/smtp/",smtp_settings,name="master-smtp-settings"),
    path("notas-fiscais/<int:pk>/",master_fiscal_document,name="master-fiscal-document"),
    path("email/modelos/",email_templates,name="master-email-templates"),
    path("email/modelos/<slug:key>/",email_templates,name="master-email-template-edit"),
    path("onboarding/<int:pk>/dispensa-email/",waive_onboarding_email,name="master-onboarding-waive-email"),
    path("whatsapp/",master.master_whatsapp_inbox,name="master-whatsapp"),
    path("whatsapp/estado/",master.master_whatsapp_status,name="master-whatsapp-status"),
    path("whatsapp/parear/",master.master_whatsapp_connect,name="master-whatsapp-connect"),
    path("whatsapp/desconectar/",master.master_whatsapp_disconnect,name="master-whatsapp-disconnect"),
    path("whatsapp/receber/",master.master_whatsapp_receive,name="master-whatsapp-receive"),
    path("whatsapp/fluxo/",master_whatsapp_flow,name="master-whatsapp-flow"),
    path("whatsapp/anexo/<int:pk>/",master_whatsapp_attachment,name="master-whatsapp-attachment"),
    path("whatsapp/<int:pk>/mensagens/",master_whatsapp_messages,name="master-whatsapp-messages"),
    path("whatsapp/<int:pk>/",master.master_whatsapp_conversation,name="master-whatsapp-conversation"),
    path("acoes/<str:action>/",master.operational_action,name="master-operational-action"),
    path("acoes/<str:action>/<int:pk>/",master.operational_action,name="master-operational-object-action"),
    path("",master.home,name="master-home"),
    path("chatbot/",master.chatbot_flow,name="master-chatbot"),
    path("planos/<int:pk>/modulos/",master.plan_modules,name="master-plan-modules"),
    path("<slug:slug>/",master.resource_list,name="master-resource-list"),
    path("<slug:slug>/novo/",master.resource_form,name="master-resource-create"),
    path("<slug:slug>/<int:pk>/editar/",master.resource_form,name="master-resource-edit"),
]
