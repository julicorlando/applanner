import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.crypto import encrypt_text
from .customer_service_agent import service_answer, specialist_graph
from .master_graph import validate_graph
from .master_runtime import run_graph


class CustomerServiceAgentTests(SimpleTestCase):
    def setUp(self):
        self.flow = SimpleNamespace(ai_enabled=True, ai_model="test-model",
            ai_key_encrypted=encrypt_text("test-agent-key"), handoff="Equipe", fallback="Repita")
        self.node = {"id": "agent", "type": "ai", "config": {
            "variable": "resposta", "customer_service": True, "applanner_only": True,
        }, "outputs": {"next": "finish"}}

    @patch("communications.master_integrations.request_json")
    def test_human_complaint_and_payment_review_skip_provider(self, provider):
        for incoming, reason in [
            ("Quero falar com uma pessoa", "requested"),
            ("Quero reembolso", "complaint"),
            ("Já paguei e continua pendente", "payment_review"),
            ("senha: segredo-de-teste", "sensitive_data"),
        ]:
            reply = service_answer(self.flow, self.node, {}, incoming)
            self.assertTrue(reply.handoff)
            self.assertEqual(reply.reason, reason)
            self.assertNotIn("segredo-de-teste", reply.text)
        provider.assert_not_called()

    @patch("communications.master_integrations.request_json")
    def test_unknown_answer_is_handoff_not_invented_information(self, provider):
        provider.return_value = {"choices": [{"message": {"content":
            '{"in_scope":false,"fact_ids":[]}'}}]}
        result = service_answer(self.flow, self.node, {}, "Minha dúvida", facts={"public": "Informação aprovada"})
        self.assertTrue(result.handoff)
        self.assertEqual(result.reason, "unknown")

    @patch("communications.master_integrations.request_json")
    def test_only_approved_facts_and_current_message_are_sent(self, provider):
        provider.return_value = {"choices": [{"message": {"content": json.dumps({
            "in_scope": True, "fact_ids": ["service"], "answer": "Tudo grátis para sempre",
        })}}]}
        variables = {"nome": "NOME PRIVADO", "telefone": "5581999999999"}
        reply = service_answer(self.flow, self.node, variables, "Preço do corte?",
            facts={"service": "Corte: R$ 30,00"}, scope="Empresa A")
        self.assertIn("Corte: R$ 30,00", reply.text)
        self.assertNotIn("grátis para sempre", reply.text)
        payload = json.dumps(provider.call_args.args[2])
        self.assertNotIn("NOME PRIVADO", payload)
        self.assertNotIn("5581999999999", payload)
        self.assertFalse(provider.call_args.args[2]["store"])

    @patch("communications.master_integrations.request_json")
    def test_repeated_unresolved_question_reaches_human(self, provider):
        provider.return_value = {"choices": [{"message": {"content":
            '{"in_scope":true,"fact_ids":["service"]}'}}]}
        variables = {}
        first = service_answer(self.flow, self.node, variables, "Preço?", facts={"service": "R$ 30"})
        second = service_answer(self.flow, self.node, variables, "Preço?", facts={"service": "R$ 30"})
        self.assertFalse(first.handoff)
        self.assertEqual(second.reason, "repeated")

    @patch("communications.master_integrations.request_json")
    def test_invalid_fact_is_rejected(self, provider):
        provider.return_value = {"choices": [{"message": {"content":
            '{"in_scope":true,"fact_ids":["private"]}'}}]}
        with self.assertRaises(ValueError):
            service_answer(self.flow, self.node, {}, "Dúvida", facts={"public": "Permitido"})

    @patch("communications.master_integrations.request_json")
    def test_simulator_transfers_without_credits_or_following_blocks(self, provider):
        graph = {"version": 2, "start": "start", "nodes": [
            {"id": "start", "type": "start", "config": {}, "outputs": {"next": "agent"}},
            self.node,
            {"id": "finish", "type": "finish", "config": {"text": "NÃO ENVIAR"}, "outputs": {}},
        ]}
        result = run_graph(validate_graph(graph), self.flow, "agent", {}, "", "Quero reembolso", simulation=True)
        self.assertTrue(result["handoff"])
        self.assertNotIn("NÃO ENVIAR", result["messages"])
        self.assertEqual(result["context"]["variables"]["_service_agent_reason"], "complaint")
        provider.assert_not_called()

    def test_profile_requires_approved_scope_and_strict_boolean(self):
        graph = specialist_graph()
        validate_graph(graph)
        node = next(n for n in graph["nodes"] if n["type"] == "ai")
        node["config"]["applanner_only"] = False
        with self.assertRaises(ValidationError):
            validate_graph(graph)
        node["config"]["applanner_only"] = True
        node["config"]["customer_service"] = "true"
        with self.assertRaises(ValidationError):
            validate_graph(graph)

    def test_company_template_preserves_booking_and_intake(self):
        graph = validate_graph(specialist_graph(tenant=True))
        by = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(by["dados"]["type"], "commercial")
        self.assertTrue(by["ia"]["config"]["customer_service"])
        self.assertIn("agenda_url", by["servicos"]["config"]["text"])
        self.assertEqual(by["dados"]["outputs"]["next"], "humano")


class CustomerServiceQueueTests(TestCase):
    @patch("communications.master_graph_services.dispatch_delivery")
    def test_handoff_cancels_old_bot_delivery_and_persists_one_notice(self, dispatch):
        from .models import MasterWhatsAppFlow, MasterWhatsAppConversation, MasterWhatsAppMessage, MasterFlowDelivery
        from .master_graph_services import advance_graph
        flow = MasterWhatsAppFlow.objects.create(pk=1, enabled=True, graph=specialist_graph())
        conversation = MasterWhatsAppConversation.objects.create(
            wa_id="5581999999999@s.whatsapp.net", last_message_at=timezone.now(),
            flow_state="resposta", flow_revision=flow.updated_at.isoformat(),
        )
        stale = MasterFlowDelivery.objects.create(conversation=conversation, event_key="old-event", body="Resposta antiga")
        incoming = MasterWhatsAppMessage.objects.create(conversation=conversation, provider_message_id="new-event",
            direction="in", body="Quero reembolso")
        advance_graph(conversation.pk, incoming.pk)
        stale.refresh_from_db()
        conversation.refresh_from_db()
        self.assertEqual(stale.status, "cancelled")
        self.assertTrue(conversation.human_handoff)
        self.assertEqual(MasterFlowDelivery.objects.filter(conversation=conversation, status="queued").count(), 1)
        advance_graph(conversation.pk, incoming.pk)
        self.assertEqual(MasterFlowDelivery.objects.filter(conversation=conversation, status="queued").count(), 1)


class TenantCustomerServiceTests(TestCase):
    @patch("communications.master_integrations.request_json")
    def test_specialist_uses_only_the_company_catalog_and_central_key(self, provider):
        from tenants.models import Tenant
        from scheduling.models import Service
        from .models import MasterWhatsAppFlow
        from .tenant_flow import company_ai
        company = Tenant.objects.create(name="Empresa A", slug="agent-company-a", status="active")
        other = Tenant.objects.create(name="Empresa B", slug="agent-company-b", status="active")
        Service.objects.create(tenant=company, name="Corte A", price=30, duration_minutes=30)
        Service.objects.create(tenant=other, name="CATÁLOGO PRIVADO B", price=90, duration_minutes=40)
        MasterWhatsAppFlow.objects.create(pk=1, ai_enabled=True, ai_model="test-model",
            ai_key_encrypted=encrypt_text("central-agent-test"))
        provider.return_value = {"choices": [{"message": {"content":
            '{"in_scope":true,"fact_ids":["servicos"]}'}}]}
        reply = company_ai(company, SimpleNamespace(ai_enabled=True),
            {"config": {"customer_service": True}}, {"nome": "CLIENTE PRIVADO"}, "Preço do corte?")
        self.assertIn("Corte A", reply.text)
        self.assertNotIn("CATÁLOGO PRIVADO B", reply.text)
        payload = json.dumps(provider.call_args.args[2], ensure_ascii=False)
        self.assertNotIn("CATÁLOGO PRIVADO B", payload)
        self.assertNotIn("CLIENTE PRIVADO", payload)
        self.assertEqual(provider.call_args.args[3], "central-agent-test")
