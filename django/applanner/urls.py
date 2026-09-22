from django.contrib import admin
from django.urls import include, path

from billing.webhooks import mercadopago_platform_webhook, mercadopago_tenant_webhook
from core.views import healthz, home, tenant_public
from communications.views import marketing_click, marketing_open, whatsapp_webhook
from contenthub.views import blog_post, landing, public_directory
from scheduling.public_api import (
    CustomerAppointmentAPIView,
    PublicAvailabilityAPIView,
    PublicBookingAPIView,
)

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("account/", include("accounts.urls")),
    path("legal/", include("legal.urls")),
    path("app/barbearia/", include("barber.urls")),
    path("app/auto/", include("auto.urls")),
    path("auto/", include("auto.public_urls")),
    path("app/arena/", include("arena.urls")),
    path("app/financeiro/", include("finance.urls")),
    path("app/relacionamento/", include("engagement.urls")),
    path("app/suporte/", include("operations.urls")),
    path("app/", include("core.portal_urls")),
    path("commercial/", include("commercial.urls")),
    path("master/", include("core.master_urls")),
    path("directory/", public_directory, name="public-directory"),
    path("p/<slug:slug>/", tenant_public, name="tenant-public"),
    path("blog/<slug:slug>/", blog_post, name="blog-post"),
    path("landing/<slug:slug>/", landing, name="landing"),
    path("tracking/email/<uuid:token>/open.gif", marketing_open, name="marketing-open"),
    path("tracking/email/<uuid:token>/click/", marketing_click, name="marketing-click"),
    path("webhooks/whatsapp/", whatsapp_webhook, name="whatsapp-webhook"),
    path("api/scheduling/", include("scheduling.urls")),
    path("api/public/<slug:slug>/availability/", PublicAvailabilityAPIView.as_view(), name="public-availability"),
    path("api/public/<slug:slug>/book/", PublicBookingAPIView.as_view(), name="public-booking"),
    path("api/public/appointments/<str:token>/", CustomerAppointmentAPIView.as_view(), name="public-appointment-manage"),
    path("webhooks/mercadopago/", mercadopago_platform_webhook, name="mercadopago-platform-webhook"),
    path("webhooks/tenant/mercadopago/<slug:slug>/", mercadopago_tenant_webhook, name="mercadopago-tenant-webhook"),
]
