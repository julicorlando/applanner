from django.contrib import admin
from accounts.api_access import api_resource
from django.urls import include, path

from billing.webhooks import mercadopago_platform_webhook, mercadopago_tenant_webhook
from core.views import healthz, home, professional_public, tenant_public
from operations.status_page import public_status
from core.branding import public_platform_logo, public_tenant_image, public_professional_image, public_blog_image
from tenants.onboarding import onboarding
from communications.views import marketing_click, marketing_open, marketing_unsubscribe, whatsapp_webhook
from communications.tenant_whatsapp import tenant_whatsapp_receive
from contenthub.views import blog_post, landing, public_directory, public_directory_page
from engagement.referrals import referral_redirect
from scheduling.public_views import appointment_page
from scheduling.ratings import public_rating
from scheduling.public_api import (
    CustomerAppointmentAPIView,
    PublicAvailabilityAPIView,
    PublicBookingAPIView, PublicWaitlistAPIView,
)
from arena.public import CourtSlotsAPIView, CourtBookingAPIView, court_reservation_page

urlpatterns = [
    path("api/v1/<slug:key>/",api_resource,name="personal-api-list"),
    path("api/v1/<slug:key>/<int:pk>/",api_resource,name="personal-api-detail"),
    path("inicio/",onboarding,name="tenant-onboarding"),
    path("healthz/", healthz, name="healthz"),
    path("status/", public_status, name="platform-status"),
    path("imagens/logo/",public_platform_logo,name="public-platform-logo"),
    path("imagens/empresa/<int:pk>/<str:kind>/",public_tenant_image,name="public-tenant-image"),
    path("imagens/profissional/<int:pk>/",public_professional_image,name="public-professional-image"),
    path("imagens/noticia/<int:pk>/",public_blog_image,name="public-blog-image"),
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("account/", include("accounts.urls")),
    path("", include("billing.urls")),
    path("legal/", include("legal.urls")),
    path("app/barbearia/", include("barber.urls")),
    path("app/auto/", include("auto.urls")),
    path("auto/", include("auto.public_urls")),
    path("app/arena/", include("arena.urls")),
    path("app/financeiro/", include("finance.urls")),
    path("app/relacionamento/", include("engagement.urls")),
    path("app/suporte/", include("operations.urls")),
    path("app/comunicacao/", include("communications.urls")),
    path("app/", include("core.portal_urls")),
    path("commercial/", include("commercial.urls")),
    path("master/", include("core.master_urls")),
    path("indique/<str:code>/",referral_redirect,name="public-referral"),
    path("directory/", public_directory_page, name="public-directory"),
    path("api/directory/", public_directory, name="public-directory-api"),
    path("estabelecimentos/", public_directory_page, name="public-directory-page"),
    path("p/<slug:slug>/profissional/<slug:professional_slug>/", professional_public, name="professional-public"),
    path("p/<slug:slug>/", tenant_public, name="tenant-public"),
    path("agendamento/<str:token>/", appointment_page, name="public-appointment-page"),
    path("arena/reserva/<str:token>/",court_reservation_page,name="public-arena-reservation"),
    path("avaliar/<str:token>/", public_rating, name="public-appointment-rating"),
    path("blog/<slug:slug>/", blog_post, name="blog-post"),
    path("landing/<slug:slug>/", landing, name="landing"),
    path("tracking/email/<uuid:token>/open.gif", marketing_open, name="marketing-open"),
    path("tracking/email/unsubscribe/<str:token>/", marketing_unsubscribe, name="marketing-unsubscribe"),
    path("tracking/email/<uuid:token>/click/", marketing_click, name="marketing-click"),
    path("webhooks/whatsapp/", whatsapp_webhook, name="whatsapp-webhook"),
    path("webhooks/tenant-whatsapp/", tenant_whatsapp_receive, name="tenant-whatsapp-receive"),
    path("api/scheduling/", include("scheduling.urls")),
    path("api/public/<slug:slug>/availability/", PublicAvailabilityAPIView.as_view(), name="public-availability"),
    path("api/public/<slug:slug>/arena/slots/",CourtSlotsAPIView.as_view(),name="public-arena-slots"),
    path("api/public/<slug:slug>/arena/book/",CourtBookingAPIView.as_view(),name="public-arena-book"),
    path("api/public/<slug:slug>/book/", PublicBookingAPIView.as_view(), name="public-booking"),
    path("api/public/<slug:slug>/waitlist/", PublicWaitlistAPIView.as_view(), name="public-waitlist"),
    path("api/public/appointments/<str:token>/", CustomerAppointmentAPIView.as_view(), name="public-appointment-manage"),
    path("webhooks/pagamentos/", mercadopago_platform_webhook, name="payment-platform-webhook"),
    path("webhooks/tenant/pagamentos/<slug:slug>/", mercadopago_tenant_webhook, name="payment-tenant-webhook"),
    path("webhooks/mercadopago/", mercadopago_platform_webhook, name="mercadopago-platform-webhook"),
    path("webhooks/tenant/mercadopago/<slug:slug>/", mercadopago_tenant_webhook, name="mercadopago-tenant-webhook"),
]
