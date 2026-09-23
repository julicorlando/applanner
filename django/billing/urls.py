from django.urls import path
from . import views

urlpatterns=[
    path("planos/",views.plans,name="billing-plans"),
    path("cadastro/",views.signup,name="billing-signup"),
    path("billing/assinatura/",views.subscription_status,name="billing-subscription-status"),
    path("billing/modulos/",views.subscription_modules,name="billing-subscription-modules"),
]
