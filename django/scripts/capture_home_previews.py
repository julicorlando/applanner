"""Capture the real application with disposable, explicitly synthetic data.

Optional tooling: pip install playwright; playwright install chromium.
Always uses a NEW SQLite database under /tmp. Never reads a deployment database.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from datetime import datetime, time, timedelta
from urllib.parse import urlsplit
from wsgiref.simple_server import make_server

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="applanner-home-preview-") as temporary:
        os.environ.update(
            DJANGO_SETTINGS_MODULE="applanner.test_settings",
            DATABASE_URL="sqlite:///" + str(Path(temporary) / "preview.sqlite3"),
            DJANGO_DEBUG="true", DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost,testserver",
            DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
            DJANGO_FIELD_ENCRYPTION_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode(),
            SECURE_SSL_REDIRECT="false", PUBLIC_BASE_URL="http://127.0.0.1:8765",
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            CELERY_BROKER_URL="memory://", CELERY_RESULT_BACKEND="cache+memory://",
        )
        import django
        from django.conf import settings
        settings.MEDIA_ROOT = Path(temporary) / "media"
        settings.STORAGES = {
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        settings.DATABASES["default"]["CONN_MAX_AGE"] = 0
        django.setup()
        from django.core.management import call_command
        from django.core.wsgi import get_wsgi_application
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.test import Client
        from django.urls import reverse
        from django.utils import timezone
        from zoneinfo import ZoneInfo
        from accounts.models import User
        from tenants.models import Tenant, Unit, UnitBusinessHours
        from scheduling.models import (Appointment, Customer, Professional, ProfessionalAvailability,
                                       ProfessionalBreak, Service, TenantScheduleSettings)
        from playwright.sync_api import sync_playwright

        call_command("migrate", verbosity=0, interactive=False)
        call_command("seed_modules", preserve_existing=True, verbosity=0)
        tenant = Tenant.objects.create(
            name="Barbearia demonstração", slug="demonstracao-home", public_slug="demonstracao-home",
            category="Barbearia", status="active", public_enabled=True, public_booking_enabled=True,
            public_headline="Seu próximo cuidado começa aqui.",
            description="Ambiente local de demonstração. Todos os nomes, serviços e agendamentos são fictícios.")
        unit = Unit.objects.create(
            tenant=tenant, name="Unidade demonstração", is_primary=True, address="Endereço demonstrativo",
            address_number="100", city="Recife", state="PE", postal_code="50000-000",
            latitude=-8.05, longitude=-34.9)
        owner = User.objects.create_user(
            email="gestor@example.test", first_name="Gestor demonstração", role="owner", tenant=tenant)
        services = [Service.objects.create(tenant=tenant, unit=unit, name=name,
                    duration_minutes=duration, price=price) for name, duration, price in
                    [("Corte masculino", 30, 45), ("Barba completa", 30, 35), ("Corte e barba", 60, 75)]]
        professionals = [Professional.objects.create(tenant=tenant, unit=unit, name=name,
                         specialty="Barbeiro", public_slug=f"profissional-{index}") for index, name in
                         enumerate(["Profissional Ana", "Profissional Bruno", "Profissional Caio"], 1)]
        for weekday in range(1, 8):
            UnitBusinessHours.objects.create(tenant=tenant, unit=unit, weekday=weekday,
                                             opens_at=time(9), closes_at=time(20))
            for professional in professionals:
                ProfessionalAvailability.objects.create(tenant=tenant, professional=professional,
                    weekday=weekday, start_time=time(9), end_time=time(20))
                ProfessionalBreak.objects.create(tenant=tenant, professional=professional,
                    weekday=weekday, start_time=time(12), end_time=time(13), label="Intervalo")
        TenantScheduleSettings.objects.create(tenant=tenant, minimum_notice_minutes=0)
        tz = ZoneInfo(tenant.timezone)
        today = timezone.now().astimezone(tz).date()
        monday = today - timedelta(days=today.weekday())
        for day_index in range(7):
            for index, hour in enumerate([10, 14, 16]):
                day = monday + timedelta(days=day_index)
                customer = Customer.objects.create(tenant=tenant,
                    name=f"Cliente demonstração {day_index * 3 + index + 1}",
                    phone=f"819{day_index * 3 + index + 1:08d}")
                start = datetime.combine(day, time(hour), tzinfo=tz)
                Appointment.objects.create(
                    tenant=tenant, unit=unit, customer=customer, professional=professionals[index],
                    service=services[index], starts_at=start,
                    ends_at=start + timedelta(minutes=services[index].duration_minutes),
                    status="confirmed", source="internal")
        session_client = Client()
        session_client.force_login(owner)
        cookie = session_client.cookies[settings.SESSION_COOKIE_NAME].value
        server = make_server("127.0.0.1", 8765, StaticFilesHandler(get_wsgi_application()))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                              locale="pt-BR", color_scheme="light", reduced_motion="reduce")
                context.route("**/*", lambda route: route.continue_()
                              if urlsplit(route.request.url).hostname in {"127.0.0.1", "localhost"}
                              else route.abort())
                context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": cookie,
                                      "url": "http://127.0.0.1:8765"}])
                page = context.new_page()
                response = page.goto("http://127.0.0.1:8765" + reverse("operation-calendar") +
                                     f"?mode=week&unit={unit.pk}&date={today.isoformat()}")
                if response.status != 200:
                    raise RuntimeError("A captura da agenda não retornou 200.")
                page.locator("#workspace-sidebar").wait_for(state="visible")
                page.locator(".calendar-event").first.wait_for(state="visible")
                page.evaluate("document.fonts.ready")
                agenda = page.screenshot(animations="disabled")
                for width in [640, 960, 1440]:
                    output_image(f"homepage-agenda-20261020-{width}.webp", agenda, width)
                context.close()
                mobile = browser.new_context(viewport={"width": 390, "height": 844},
                    device_scale_factor=2, is_mobile=True, has_touch=True,
                    locale="pt-BR", color_scheme="light", reduced_motion="reduce")
                mobile.route("**/*", lambda route: route.continue_()
                             if urlsplit(route.request.url).hostname in {"127.0.0.1", "localhost"}
                             else route.abort())
                phone = mobile.new_page()
                response = phone.goto("http://127.0.0.1:8765" + reverse("tenant-public", args=[tenant.slug]) +
                                      f"?unit={unit.pk}")
                if response.status != 200:
                    raise RuntimeError("A página pública não retornou 200.")
                phone.locator("#public-booking").wait_for(state="visible")
                phone.select_option("#booking-service", str(services[0].pk))
                phone.get_by_role("button", name="Continuar", exact=True).click()
                phone.locator("#booking-professional").wait_for(state="visible")
                phone.select_option("#booking-professional", str(professionals[0].pk))
                phone.locator("#agendar").evaluate("element => element.scrollIntoView({block:'start'})")
                phone.evaluate("document.fonts.ready")
                phone.wait_for_timeout(1200)
                picture = phone.screenshot(animations="disabled")
                for width in [390, 780]:
                    output_image(f"homepage-booking-20261020-{width}.webp", picture, width)
                mobile.close()
                for width in [320, 390, 768, 1440]:
                    for theme in ["light", "dark"]:
                        qa = browser.new_context(viewport={"width": width, "height": 1000 if width > 700 else 844},
                            locale="pt-BR", color_scheme=theme, reduced_motion="reduce")
                        qa.route("**/*", lambda route: route.continue_()
                                 if urlsplit(route.request.url).hostname in {"127.0.0.1", "localhost"}
                                 else route.abort())
                        check = qa.new_page()
                        errors = []
                        check.on("pageerror", lambda error: errors.append(str(error)))
                        response = check.goto("http://127.0.0.1:8765/", wait_until="networkidle")
                        if response.status != 200:
                            raise RuntimeError("A home não retornou 200.")
                        check.evaluate("document.fonts.ready")
                        height = check.evaluate("document.documentElement.scrollHeight")
                        for position in range(0, height, 700):
                            check.evaluate("position => window.scrollTo(0, position)", position)
                            check.wait_for_timeout(60)
                        check.evaluate("window.scrollTo(0,0)")
                        check.wait_for_timeout(150)
                        overflow = check.evaluate("document.documentElement.scrollWidth > innerWidth")
                        broken = check.locator("img").evaluate_all("images => images.filter(image => !image.complete || !image.naturalWidth).map(image => image.getAttribute('src'))")
                        if overflow or broken or errors:
                            raise RuntimeError("Home QA: " + json.dumps({"width": width, "theme": theme,
                                               "overflow": overflow, "broken": broken, "errors": errors}))
                        print("APPLANNER_HOME_QA " + json.dumps({"width": width, "theme": theme,
                              "horizontal_overflow": False, "broken_images": 0, "javascript_errors": 0}), flush=True)
                        if theme == "light" and width in [390, 1440]:
                            output_image(f"homepage-proof-{width}.webp", check.screenshot(animations="disabled"), width)
                        qa.close()
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
        print("APPLANNER_CAPTURE_OK", json.dumps({"source": os.environ.get("GITHUB_SHA", ""),
              "synthetic_data": True, "production_access": False}), flush=True)


def output_image(name, content, width):
    with Image.open(io.BytesIO(content)) as source:
        resized = source.resize((width, round(source.height * width / source.width)), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        resized.convert("RGB").save(buffer, format="WEBP", quality=83, method=6)
    data = buffer.getvalue()
    print("APPLANNER_IMAGE_START " + name, flush=True)
    encoded = base64.b64encode(data).decode()
    for offset in range(0, len(encoded), 8192):
        print("APPLANNER_IMAGE_DATA " + encoded[offset:offset + 8192], flush=True)
    print("APPLANNER_IMAGE_END " + name + " " + hashlib.sha256(data).hexdigest(), flush=True)


if __name__ == "__main__":
    main()
