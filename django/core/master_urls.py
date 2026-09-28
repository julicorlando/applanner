from django.urls import path
from . import master

urlpatterns=[
    path("pagamentos/mercado-pago/",master.platform_payment_gateway,name="master-platform-payment"),
    path("whatsapp/",master.master_whatsapp_inbox,name="master-whatsapp"),
    path("whatsapp/estado/",master.master_whatsapp_status,name="master-whatsapp-status"),
    path("whatsapp/parear/",master.master_whatsapp_connect,name="master-whatsapp-connect"),
    path("whatsapp/desconectar/",master.master_whatsapp_disconnect,name="master-whatsapp-disconnect"),
    path("whatsapp/receber/",master.master_whatsapp_receive,name="master-whatsapp-receive"),
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
