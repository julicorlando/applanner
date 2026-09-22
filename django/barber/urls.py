from django.urls import path
from . import portal

urlpatterns=[
    path("comandas/nova/",portal.command_create,name="barber-command-create"),
    path("comandas/<int:pk>/",portal.command_detail,name="barber-command-detail"),
    path("comandas/<int:pk>/acao/",portal.command_action,name="barber-command-action"),
]
