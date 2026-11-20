from django.test import SimpleTestCase

from .models import SupportTicket
from .triage import classify_priority


class AutomaticTriageTests(SimpleTestCase):
    def test_security_and_outage_are_urgent(self):
        self.assertEqual(classify_priority("segurança","Acesso indevido",""),SupportTicket.Priority.URGENT)
        self.assertEqual(classify_priority("agenda","Sistema fora do ar",""),SupportTicket.Priority.URGENT)

    def test_payment_is_high_and_question_is_low(self):
        self.assertEqual(classify_priority("financeiro","Pagamento não recebido",""),SupportTicket.Priority.HIGH)
        self.assertEqual(classify_priority("geral","Dúvida","Como faço?"),SupportTicket.Priority.LOW)
