from django.urls import path
from . import views

urlpatterns=[
    path("planos/",views.plans,name="billing-plans"),
    path("planos/monte-o-seu/",views.custom_plan,name="billing-custom-plan"),
    path("cadastro/",views.signup,name="billing-signup"),
    path("billing/assinatura/",views.subscription_status,name="billing-subscription-status"),
    path("billing/assinatura/pagar/",views.subscription_checkout,name="billing-subscription-checkout"),
    path("billing/assinatura/pix/",views.subscription_pix,name="billing-subscription-pix"),
    path("billing/modulos/",views.subscription_modules,name="billing-subscription-modules"),
]
