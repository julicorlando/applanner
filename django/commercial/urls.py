from django.urls import path
from . import views, social_views

urlpatterns = [
    path("campanhas/",social_views.campaigns,name="commercial-social-list"),
    path("campanhas/nova/",social_views.campaign_edit,name="commercial-social-create"),
    path("campanhas/<int:pk>/",social_views.campaign_detail,name="commercial-social-detail"),
    path("campanhas/<int:pk>/editar/",social_views.campaign_edit,name="commercial-social-edit"),
    path("midias/<int:pk>/",social_views.campaign_media,name="commercial-social-media"),
    path("c/<uuid:code>/",social_views.public_campaign,name="commercial-social-public"),
    path("c/<uuid:code>/midia/<int:pk>/",social_views.public_media,name="commercial-social-public-media"),
    path("proposta/<str:token>/",views.public_proposal,name="commercial-public-proposal"),
    path("",views.dashboard,name="commercial-dashboard"),
    path("leads/novo/",views.prospect_create,name="commercial-prospect-create"),
    path("leads/<int:pk>/excluir/",views.lead_delete,name="commercial-lead-delete"),
    path("leads/<int:pk>/",views.lead_detail,name="commercial-lead-detail"),
    path("propostas/nova/",views.proposal_create,name="commercial-proposal-create"),
    path("propostas/<int:pk>/",views.proposal_detail,name="commercial-proposal-detail"),
    path("propostas/<int:pk>/acao/",views.proposal_action,name="commercial-proposal-action"),
    path("comissoes/<int:pk>/acao/",views.commission_action,name="commercial-commission-action"),
]
