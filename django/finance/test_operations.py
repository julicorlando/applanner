from django.test import TestCase
from accounts.models import User
from finance.models import CashSession,Product
from finance.services import close_cash_session,create_sale,open_cash_session
from tenants.models import Tenant


class FinanceOperationsTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Finance",slug="finance-test")
        self.user=User.objects.create_user(email="finance@example.com",password="StrongPassword123!",tenant=self.tenant)
        self.product=Product.objects.create(tenant=self.tenant,name="Pomada",sale_price="20",cost_price="5",stock="10")

    def test_sale_decrements_stock_and_cash_closes(self):
        session=open_cash_session(tenant=self.tenant,user=self.user,opening_amount="100")
        create_sale(tenant=self.tenant,user=self.user,items=[{"product_id":self.product.pk,"quantity":2}],payment_method="dinheiro")
        self.product.refresh_from_db()
        self.assertEqual(str(self.product.stock),"8.000")
        close_cash_session(session=session,user=self.user,closing_amount="140")
        session.refresh_from_db()
        self.assertEqual(str(session.expected_amount),"140.00")
        self.assertEqual(str(session.difference_amount),"0.00")
