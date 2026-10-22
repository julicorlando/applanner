from django.urls import path
from . import views

urlpatterns = [
    path(
        "envio/<int:pk>/tentar/",
        views.retry_delivery,
        name="development-delivery-retry",
    ),
    path("", views.clients, name="development-clients"),
    path("novo/", views.client_form, name="development-client-create"),
    path("<int:pk>/", views.client_detail, name="development-client"),
    path("<int:pk>/editar/", views.client_form, name="development-client-edit"),
    path("<int:pk>/convite/", views.resend_invite, name="development-client-invite"),
    path(
        "<int:client_pk>/cobranca/nova/",
        views.charge_form,
        name="development-charge-create",
    ),
    path(
        "<int:client_pk>/cobranca/<int:pk>/editar/",
        views.charge_form,
        name="development-charge-edit",
    ),
    path(
        "cobranca/<int:pk>/<str:action>/",
        views.settlement,
        name="development-settlement",
    ),
]
