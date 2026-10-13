from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from scheduling.models import Customer, Professional
from tenants.models import Tenant
from .models import FinancialTransaction, Product, ProductStockMovement, Sale
from .services import cancel_sale, create_sale


class PosServiceTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Loja",slug="loja",status=Tenant.Status.ACTIVE)
        self.user=User.objects.create(email="caixa@example.com",tenant=self.tenant)
        self.customer=Customer.objects.create(tenant=self.tenant,name="Cliente")
        self.professional=Professional.objects.create(tenant=self.tenant,name="Profissional")
        self.product=Product.objects.create(
            tenant=self.tenant,
            name="Produto",
            sku="P1",
            cost_price=Decimal("10.00"),
            sale_price=Decimal("25.00"),
            stock=Decimal("10.000"),
        )

    def test_sale_and_cancellation_keep_stock_and_finance_consistent(self):
        sale=create_sale(
            tenant=self.tenant,
            user=self.user,
            customer=self.customer,
            professional=self.professional,
            payment_method="pix",
            items=[{"product_id":self.product.pk,"quantity":"2"}],
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock,Decimal("8.000"))
        self.assertEqual(sale.status,Sale.Status.COMPLETED)
        self.assertTrue(
            FinancialTransaction.objects.filter(
                source_type="sale",source_id=sale.pk,status="paid"
            ).exists()
        )
        self.assertTrue(ProductStockMovement.objects.filter(sale=sale,type="sale").exists())

        cancel_sale(sale=sale,user=self.user,reason="Teste")
        self.product.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.product.stock,Decimal("10.000"))
        self.assertEqual(sale.status,Sale.Status.CANCELLED)
        self.assertTrue(
            ProductStockMovement.objects.filter(sale=sale,type="sale_reversal").exists()
        )
        self.assertTrue(
            FinancialTransaction.objects.filter(
                source_type="sale",source_id=sale.pk,status="cancelled"
            ).exists()
        )
