from django.urls import path
from . import portal
from .receipt import receipt
from .gift_portal import use_gift

urlpatterns=[
    path("comandas/<int:pk>/vale/",use_gift,name="barber-command-gift"),
    path("comandas/<int:pk>/recibo/",receipt,name="barber-command-receipt"),
    path("comandas/nova/",portal.command_create,name="barber-command-create"),
    path("comandas/<int:pk>/",portal.command_detail,name="barber-command-detail"),
    path("comandas/<int:pk>/acao/",portal.command_action,name="barber-command-action"),
]
