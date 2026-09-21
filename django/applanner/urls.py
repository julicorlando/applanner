from django.contrib import admin
from django.urls import include, path

from billing.webhooks import mercadopago_platform_webhook, mercadopago_tenant_webhook
from core.views import healthz, home
from scheduling.public_api import (
    CustomerAppointmentAPIView,
    PublicAvailabilityAPIView,
    PublicBookingAPIView,
)

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("api/scheduling/", include("scheduling.urls")),
    path("api/public/<slug:slug>/availability/", PublicAvailabilityAPIView.as_view(), name="public-availability"),
    path("api/public/<slug:slug>/book/", PublicBookingAPIView.as_view(), name="public-booking"),
    path("api/public/appointments/<str:token>/", CustomerAppointmentAPIView.as_view(), name="public-appointment-manage"),
    path("webhooks/mercadopago/", mercadopago_platform_webhook, name="mercadopago-platform-webhook"),
    path("webhooks/tenant/mercadopago/<slug:slug>/", mercadopago_tenant_webhook, name="mercadopago-tenant-webhook"),
]
