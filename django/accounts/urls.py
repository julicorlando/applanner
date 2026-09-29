from django.urls import path
from . import views
from . import api_access

app_name="accounts"

urlpatterns=[
    path("documentacao-api/",api_access.documentation,name="documentation"),
    path("documentacao-api/tokens/<int:pk>/revogar/",api_access.revoke_token,name="api-token-revoke"),
    path("login/",views.login_view,name="login"),
    path("2fa/challenge/",views.two_factor_challenge,name="two-factor-challenge"),
    path("2fa/setup/",views.two_factor_setup,name="two-factor-setup"),
    path("2fa/disable/",views.two_factor_disable,name="two-factor-disable"),
    path("password/change/",views.change_password,name="change-password"),
    path("password-reset/",views.password_reset_request,name="password-reset-request"),
    path("password-reset/<str:token>/",views.password_reset_confirm,name="password-reset-confirm"),
    path("verification/send/",views.send_verification,name="send-verification"),
    path("verify-email/<str:token>/",views.verify_email,name="verify-email"),
    path("logout/",views.logout_view,name="logout"),
]
