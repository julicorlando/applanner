from django.urls import path
from . import portal

urlpatterns=[path("chamados/<int:pk>/",portal.ticket_detail,name="support-ticket-detail")]
