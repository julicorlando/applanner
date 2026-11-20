from django.urls import path
from . import portal

urlpatterns=[
    path("os/<int:pk>/",portal.job_detail,name="auto-job-detail"),
    path("os/<int:pk>/acao/",portal.job_action,name="auto-job-action"),
    path("comandas/<int:pk>/acao/",portal.command_action,name="auto-command-action"),
]
