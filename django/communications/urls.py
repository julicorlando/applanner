from django.urls import path
from . import portal
from .tenant_whatsapp import tenant_whatsapp_settings

urlpatterns=[
    path("conectar/",tenant_whatsapp_settings,name="tenant-whatsapp-settings"),
    path("",portal.inbox,name="communications-inbox"),
    path("notificacoes/",portal.notifications,name="communications-notifications"),
    path("<int:pk>/",portal.conversation,name="communications-conversation"),
    path("<int:pk>/acao/",portal.conversation_action,name="communications-conversation-action"),
]
