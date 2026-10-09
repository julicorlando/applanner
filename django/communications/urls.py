from django.urls import path
from . import portal,tenant_chatbot
from .tenant_whatsapp import tenant_whatsapp_settings

from .delivery_center import dashboard as deliveries,retry as delivery_retry

urlpatterns=[
    path("entregas/",deliveries,name="communications-deliveries"),
    path("entregas/<int:pk>/reenviar/",delivery_retry,name="communications-delivery-retry"),
    path("chatbot/",tenant_chatbot.builder,name="tenant-whatsapp-chatbot"),
    path("chatbot/simular/",tenant_chatbot.simulate,name="tenant-whatsapp-simulate"),
    path("conectar/",tenant_whatsapp_settings,name="tenant-whatsapp-settings"),
    path("",portal.inbox,name="communications-inbox"),
    path("notificacoes/",portal.notifications,name="communications-notifications"),
    path("<int:pk>/",portal.conversation,name="communications-conversation"),
    path("<int:pk>/acao/",portal.conversation_action,name="communications-conversation-action"),
]
