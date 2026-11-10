from django.urls import path
from . import portal

urlpatterns=[
    path("chamados/<int:pk>/",portal.ticket_detail,name="support-ticket-detail"),
    path("chamados/<int:pk>/iniciar-acesso/",portal.start_access,name="support-start-access"),
    path("encerrar-acesso/",portal.end_access,name="support-end-access"),
]
