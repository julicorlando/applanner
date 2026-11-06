from django.urls import path
from . import views

urlpatterns = [
    path("cobranca/<str:token>/", views.payment_link, name="development-payment-link"),
    path("ativar/<str:token>/", views.activate, name="development-activate"),
    path("pagamentos/", views.portal, name="development-payments"),
    path("pagamentos/<int:pk>/", views.charge_detail, name="development-charge"),
    path("pagamentos/<int:pk>/boleto/", views.boleto, name="development-boleto"),
    path("pagamentos/<int:pk>/pix/", views.pix, name="development-pix"),
    path("pagamentos/<int:pk>/cartao/", views.card, name="development-card"),
    path(
        "pagamentos/<int:pk>/consultar/",
        views.refresh_payment,
        name="development-payment-refresh",
    ),
]
