import threading
from datetime import datetime,time,timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import close_old_connections,connections
from django.test import Client,TestCase,TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.coupons import consume_coupon
from billing.models import Coupon
from core.audit import append_audit,verify_audit_chain
from core.models import AuditLog
from finance.models import Product,Sale
from finance.services import create_sale
from legal.models import DataSubjectRequest
from operations.models import PlatformOperationSettings,PlatformSMTPSettings
from scheduling.models import (
    Appointment,Professional,ProfessionalAvailability,Service,
)
from tenants.models import Tenant


class BookingConcurrencyTests(TransactionTestCase):
    reset_sequences=True

    def setUp(self):
        self.tenant=Tenant.objects.create(
            name="Concorrência",slug="concorrencia-booking",
            public_enabled=True,public_booking_enabled=True,
            status=Tenant.Status.ACTIVE,timezone="America/Recife",
        )
        self.service=Service.objects.create(
            tenant=self.tenant,name="Corte",duration_minutes=30,price=Decimal("40.00")
        )
        self.professional=Professional.objects.create(
            tenant=self.tenant,name="Ana",services_restricted=True
        )
        self.professional.services.add(self.service)
        self.day=timezone.localdate()+timedelta(days=2)
        ProfessionalAvailability.objects.create(
            tenant=self.tenant,professional=self.professional,
            weekday=self.day.isoweekday(),start_time=time(9),end_time=time(11),
        )
        self.start=datetime.combine(
            self.day,time(9),tzinfo=ZoneInfo("America/Recife")
        )
        self.url=reverse("public-booking",args=[self.tenant.slug])

    def _payload(self,index):
        return {
            "service_id":self.service.pk,
            "professional_id":self.professional.pk,
            "starts_at":self.start.isoformat(),
            "name":f"Cliente {index}",
            "phone":f"8199999000{index}",
            "email":f"cliente{index}@example.test",
        }

    def test_two_customers_cannot_take_same_professional_slot(self):
        barrier=threading.Barrier(2)
        results=[]
        errors=[]

        def worker(index):
            close_old_connections()
            try:
                client=Client()
                barrier.wait(timeout=5)
                response=client.post(
                    self.url,self._payload(index),
                    content_type="application/json",
                    HTTP_IDEMPOTENCY_KEY=f"booking-concurrency-{index}",
                )
                results.append(response.status_code)
            except Exception as exc:
                errors.append(exc)
            finally:
                # Threads own separate DB connections; close them explicitly so
                # PostgreSQL can drop the test database after TransactionTestCase.
                connections.close_all()

        threads=[threading.Thread(target=worker,args=(index,)) for index in (1,2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=15)

        self.assertFalse(errors,errors)
        self.assertEqual(sorted(results),[201,409])
        self.assertEqual(Appointment.objects.filter(tenant=self.tenant).count(),1)

    def test_repeated_mobile_request_returns_same_booking(self):
        client=Client()
        payload=self._payload(1)
        key="booking-idempotency-fixed-001"
        first=client.post(
            self.url,payload,content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        second=client.post(
            self.url,payload,content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(first.status_code,201,first.content)
        self.assertEqual(second.status_code,200,second.content)
        self.assertEqual(second["X-Idempotent-Replay"],"true")
        self.assertEqual(first.json()["id"],second.json()["id"])
        self.assertEqual(Appointment.objects.filter(tenant=self.tenant).count(),1)

        changed={**payload,"notes":"Outra operação com a mesma chave"}
        conflict=client.post(
            self.url,changed,content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(conflict.status_code,409)


class StockAndCouponConcurrencyTests(TransactionTestCase):
    reset_sequences=True

    def setUp(self):
        self.tenant=Tenant.objects.create(
            name="Estoque concorrente",slug="estoque-concorrente",status=Tenant.Status.ACTIVE
        )
        self.user=User.objects.create_user(
            email="estoque@example.test",password="StrongPassword123!",
            tenant=self.tenant,role="owner",
        )
        self.product=Product.objects.create(
            tenant=self.tenant,name="Pomada",sale_price=Decimal("30.00"),
            cost_price=Decimal("10.00"),stock=Decimal("1.000"),
        )

    def test_two_sales_cannot_consume_same_last_stock(self):
        barrier=threading.Barrier(2)
        results=[]
        errors=[]

        def worker(index):
            close_old_connections()
            try:
                tenant=Tenant.objects.get(pk=self.tenant.pk)
                user=User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=5)
                try:
                    sale=create_sale(
                        tenant=tenant,user=user,payment_method="pix",
                        items=[{"product_id":self.product.pk,"quantity":"1"}],
                        idempotency_key=f"stock-sale-{index}",
                    )
                    results.append(("ok",sale.pk))
                except ValidationError:
                    results.append(("blocked",None))
            except Exception as exc:
                errors.append(exc)
            finally:
                # Threads own separate DB connections; close them explicitly so
                # PostgreSQL can drop the test database after TransactionTestCase.
                connections.close_all()

        threads=[threading.Thread(target=worker,args=(index,)) for index in (1,2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=15)

        self.assertFalse(errors,errors)
        self.assertEqual(sorted(result[0] for result in results),["blocked","ok"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock,Decimal("0.000"))
        self.assertEqual(Sale.objects.filter(tenant=self.tenant).count(),1)

    def test_same_sale_idempotency_key_does_not_reduce_stock_twice(self):
        sale1=create_sale(
            tenant=self.tenant,user=self.user,payment_method="pix",
            items=[{"product_id":self.product.pk,"quantity":"1"}],
            idempotency_key="sale-retry-001",
        )
        sale2=create_sale(
            tenant=self.tenant,user=self.user,payment_method="pix",
            items=[{"product_id":self.product.pk,"quantity":"1"}],
            idempotency_key="sale-retry-001",
        )
        self.assertEqual(sale1.pk,sale2.pk)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock,Decimal("0.000"))

    def test_coupon_max_uses_is_serialized(self):
        coupon=Coupon.objects.create(
            code="ULTIMO",type=Coupon.Type.FIXED,value=Decimal("10.00"),
            max_uses=1,active=True,
        )
        barrier=threading.Barrier(2)
        results=[]
        errors=[]

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    _,discount=consume_coupon(code="ULTIMO",subtotal=Decimal("50.00"))
                    results.append(("ok",discount))
                except ValidationError:
                    results.append(("blocked",Decimal("0.00")))
            except Exception as exc:
                errors.append(exc)
            finally:
                # Threads own separate DB connections; close them explicitly so
                # PostgreSQL can drop the test database after TransactionTestCase.
                connections.close_all()

        threads=[threading.Thread(target=worker) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=15)

        self.assertFalse(errors,errors)
        self.assertEqual(sorted(result[0] for result in results),["blocked","ok"])
        coupon.refresh_from_db()
        self.assertEqual(coupon.uses_count,1)


class PrivacyAuditAndOperationsTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(
            name="Privacidade",slug="privacy-prod",status=Tenant.Status.ACTIVE
        )
        self.user=User.objects.create_user(
            email="privacy@example.test",password="StrongPassword123!",
            tenant=self.tenant,role="owner",first_name="Pessoa",
        )

    def test_privacy_center_exports_and_tracks_requests_and_marketing_consent(self):
        self.client.force_login(self.user)
        grant=self.client.post(reverse("legal-privacy-center"),{"action":"grant_marketing"})
        self.assertEqual(grant.status_code,302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.marketing_consent)

        correction=self.client.post(reverse("legal-privacy-center"),{
            "action":"correction","details":"Corrigir meu telefone.",
        })
        self.assertEqual(correction.status_code,302)
        request=DataSubjectRequest.objects.get(user=self.user)
        self.assertEqual(request.request_type,DataSubjectRequest.Type.CORRECTION)
        self.assertIsNotNone(request.deadline_at)

        export=self.client.get(reverse("legal-privacy-export"))
        self.assertEqual(export.status_code,200)
        self.assertIn("application/json",export["Content-Type"])
        self.assertContains(export,"privacy@example.test")
        self.assertContains(export,"Corrigir meu telefone.",count=0)

        self.client.post(reverse("legal-privacy-center"),{"action":"withdraw_marketing"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.marketing_consent)

    def test_audit_hash_chain_detects_tampering(self):
        first=append_audit(
            tenant=self.tenant,user=self.user,action="FINANCIAL_TEST",
            entity_type="finance.Test",entity_id=1,after={"amount":"10.00"},
        )
        second=append_audit(
            tenant=self.tenant,user=self.user,action="FINANCIAL_TEST_2",
            entity_type="finance.Test",entity_id=2,
            before={"amount":"10.00"},after={"amount":"12.00"},
        )
        check=verify_audit_chain(f"tenant:{self.tenant.pk}")
        self.assertTrue(check["valid"],check)
        self.assertEqual(second.previous_hash,first.entry_hash)

        AuditLog.objects.filter(pk=first.pk).update(after={"amount":"999.00"})
        broken=verify_audit_chain(f"tenant:{self.tenant.pk}")
        self.assertFalse(broken["valid"])
        self.assertEqual(broken["broken_id"],first.pk)

    def test_maintenance_keeps_status_page_available(self):
        PlatformOperationSettings.objects.update_or_create(
            pk=1,defaults={
                "maintenance_enabled":True,
                "maintenance_message":"Atualização programada.",
                "status_page_enabled":True,
            },
        )
        self.client.logout()
        response=self.client.get("/")
        self.assertEqual(response.status_code,503)
        self.assertContains(response,"Atualização programada.",status_code=503)
        status_response=self.client.get(reverse("platform-status"))
        self.assertEqual(status_response.status_code,200)
        self.assertContains(status_response,"Status dos serviços ApPlanner")


class EmailAuthenticationHealthTests(TestCase):
    @patch("core.master_email._txt_records")
    def test_spf_dkim_dmarc_health(self,records):
        from core.master_email import email_dns_health
        config=PlatformSMTPSettings(
            from_email="contato@applanner.com.br",
            host="smtp.applanner.com.br",dkim_selector="mail",
        )
        records.side_effect=lambda name:{
            "applanner.com.br":["v=spf1 include:example.net -all"],
            "mail._domainkey.applanner.com.br":["v=DKIM1; k=rsa; p=abc"],
            "_dmarc.applanner.com.br":["v=DMARC1; p=quarantine"],
        }.get(name,[])
        health=email_dns_health(config)
        self.assertTrue(health["spf"])
        self.assertTrue(health["dkim"])
        self.assertTrue(health["dmarc"])
        self.assertEqual(health["selector"],"mail")
