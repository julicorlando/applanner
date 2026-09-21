from django.urls import path
from . import views

app_name="accounts"

urlpatterns=[
    path("login/",views.login_view,name="login"),
    path("2fa/challenge/",views.two_factor_challenge,name="two-factor-challenge"),
    path("2fa/setup/",views.two_factor_setup,name="two-factor-setup"),
    path("2fa/disable/",views.two_factor_disable,name="two-factor-disable"),
    path("logout/",views.logout_view,name="logout"),
]
