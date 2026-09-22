from django.urls import path
from . import views

urlpatterns = [
    path("proposta/<str:token>/",views.public_proposal,name="commercial-public-proposal"),
    path("",views.dashboard,name="commercial-dashboard"),
    path("leads/<int:pk>/",views.lead_detail,name="commercial-lead-detail"),
    path("propostas/nova/",views.proposal_create,name="commercial-proposal-create"),
    path("propostas/<int:pk>/",views.proposal_detail,name="commercial-proposal-detail"),
    path("propostas/<int:pk>/acao/",views.proposal_action,name="commercial-proposal-action"),
    path("comissoes/<int:pk>/acao/",views.commission_action,name="commercial-commission-action"),
]
