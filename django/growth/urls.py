from django.urls import path
from . import views

urlpatterns=[
    path("indique-e-ganhe/",views.referral_program,name="referral-program"),
    path("indique/pix/<str:token>/",views.referral_pix,name="referral-pix"),
]
