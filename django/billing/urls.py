from django.urls import path
from . import views
from .fiscal import download_fiscal_document,request_fiscal_document

urlpatterns=[
    path("planos/",views.plans,name="billing-plans"),
    path("planos/monte-o-seu/",views.custom_plan,name="billing-custom-plan"),
    path("cadastro/",views.signup,name="billing-signup"),
    path("billing/assinatura/",views.subscription_status,name="billing-subscription-status"),
    path("billing/assinatura/forma-pagamento/",views.subscription_payment_method,name="billing-subscription-payment-method"),
    path("billing/assinatura/cancelar/",views.cancel_platform_subscription,name="billing-subscription-cancel"),
    path("billing/conta/solicitar-exclusao/",views.request_account_deletion,name="billing-account-deletion"),
    path("billing/assinatura/pagar/",views.subscription_checkout,name="billing-subscription-checkout"),
    path("billing/assinatura/pix/",views.subscription_pix,name="billing-subscription-pix"),
    path("billing/nfe/<int:payment_id>/solicitar/",request_fiscal_document,name="billing-nfe-request"),
    path("billing/nfe/<int:pk>/<str:kind>/",download_fiscal_document,name="billing-nfe-download"),
    path("billing/modulos/",views.subscription_modules,name="billing-subscription-modules"),
]
