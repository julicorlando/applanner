from django.urls import path
from . import portal

urlpatterns=[
    path("",portal.inbox,name="communications-inbox"),
    path("notificacoes/",portal.notifications,name="communications-notifications"),
    path("<int:pk>/",portal.conversation,name="communications-conversation"),
    path("<int:pk>/acao/",portal.conversation_action,name="communications-conversation-action"),
]
