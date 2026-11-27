from datetime import timedelta
from unittest.mock import patch
from django.test import Client
from django.template import Template, RequestContext
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from scheduling.models import Appointment, Professional
from .test_waiting_room import WaitingRoomTests
from .operation_models import ClinicRoom, DailyRoomSelection, WaitingRoomCall
from .rooms import current_room


class ClinicRoomTests(WaitingRoomTests):
    def select(self, **data):
        return self.client.post(reverse('waiting-room-select'), {'room': self.room.pk, **data})

    def test_room_registration_requires_admin_and_tenant_scope(self):
        url = reverse('waiting-room-rooms')
        self.assertEqual(self.client.post(url, {'action': 'create', 'name': '  Consultório   03  '}).status_code, 302)
        room = ClinicRoom.objects.get(name='Consultório 03')
        self.assertEqual(room.tenant, self.tenant)
        self.assertEqual(self.client.post(url, {'action': 'create', 'name': room.name}).status_code, 409)
        self.assertEqual(self.client.post(url, {'action': 'deactivate', 'room': room.pk}).status_code, 302)
        room.refresh_from_db(); self.assertFalse(room.active)
        self.assertEqual(self.client.post(url, {'action': 'activate', 'room': room.pk}).status_code, 302)
        reception = User.objects.create_user(email='room-reception@test.invalid', tenant=self.tenant, role='reception')
        self.client.force_login(reception)
        self.assertEqual(self.client.post(url, {'action': 'create', 'name': 'Proibida'}).status_code, 403)
        self.assertFalse(ClinicRoom.objects.filter(name='Proibida').exists())

    def test_choice_persists_across_login_and_changes_and_finishes_day(self):
        second = ClinicRoom.objects.create(tenant=self.tenant, name='Sala 03')
        self.assertEqual(self.select(room=second.pk, next='/app/clinica/').url, '/app/clinica/')
        self.client.logout(); self.client.force_login(self.owner)
        self.assertEqual(current_room(self.owner), second)
        self.assertContains(self.client.get(reverse('waiting-room-console')), 'Sala de hoje:')
        self.assertEqual(self.call(room=second.name).status_code, 302)
        self.assertEqual(WaitingRoomCall.objects.get().room, second.name)
        self.assertEqual(self.select(action='finish').status_code, 302)
        self.assertIsNone(current_room(self.owner))
        self.assertEqual(self.call().status_code, 400)
        self.assertEqual(self.select().status_code, 302)
        self.assertEqual(current_room(self.owner), self.room)
        self.assertEqual(DailyRoomSelection.objects.filter(user=self.owner).count(), 1)

    def test_daily_expiry_and_no_reprompt_after_finish(self):
        today = timezone.localdate()
        with patch('healthcare.rooms.timezone.localdate', return_value=today + timedelta(days=1)):
            self.assertIsNone(current_room(self.owner))
            response = self.client.get(reverse('waiting-room-console'))
            self.assertContains(response, 'data-auto-open="true"')
            self.select(action='finish')
            response = self.client.get(reverse('waiting-room-console'))
            self.assertContains(response, 'data-auto-open="false"')
        self.assertEqual(current_room(self.owner), self.room)

    def test_other_clinic_inactive_rooms_and_arbitrary_names_cannot_be_used(self):
        from tenants.models import Tenant
        other = Tenant.objects.create(name='Outra clínica', slug='room-other', category='fisioterapia')
        foreign = ClinicRoom.objects.create(tenant=other, name='Sala estrangeira')
        self.assertEqual(self.select(room=foreign.pk).status_code, 404)
        self.assertEqual(self.call(room='Sala não cadastrada').status_code, 409)
        self.room.active=False; self.room.save()
        self.assertIsNone(current_room(self.owner))
        self.assertEqual(self.select().status_code, 404)
        self.assertEqual(self.call().status_code, 400)
        self.assertFalse(WaitingRoomCall.objects.exists())

    def test_room_choice_is_per_user_and_reception_can_only_select_own_room(self):
        reception = User.objects.create_user(email='own-room@test.invalid', tenant=self.tenant, role='reception')
        self.client.force_login(reception)
        self.assertIsNone(current_room(reception))
        self.assertEqual(self.select(user=self.owner.pk).status_code, 302)
        self.assertEqual(current_room(reception), self.room)
        self.select(action='finish')
        self.assertIsNone(current_room(reception))
        self.assertEqual(current_room(self.owner), self.room)

    def test_csrf_and_safe_return_and_optional_module(self):
        secure_client=Client(enforce_csrf_checks=True);secure_client.force_login(self.owner)
        self.assertEqual(secure_client.post(reverse('waiting-room-select'), {'room':self.room.pk}).status_code, 403)
        self.assertEqual(self.select(next='https://evil.invalid/app/').url, reverse('waiting-room-console'))
        self.entitlement.enabled=False;self.entitlement.save()
        self.assertEqual(self.select().status_code,403)
        self.assertEqual(self.client.post(reverse('waiting-room-rooms'), {'action':'create','name':'Sem módulo'}).status_code,403)

    def test_patient_call_template_filters_by_patient_and_returns_to_record(self):
        request = self.client.get(reverse('waiting-room-console')).wsgi_request
        rendered=Template('{% load room_calls %}{% patient_tv_call patient_id %}').render(RequestContext(request, {'patient_id':self.patient.pk}))
        self.assertIn('Chamar paciente', rendered)
        self.assertIn(f'value="{self.appointment.pk}"', rendered)
        self.assertIn('Sala 02', rendered)
        self.assertEqual(self.call(next='/app/clinica/paciente/1/').url, '/app/clinica/paciente/1/')
        rendered=Template('{% load room_calls %}{% patient_tv_call patient_id %}').render(RequestContext(request, {'patient_id':self.patient.pk+999}))
        self.assertNotIn(f'value="{self.appointment.pk}"', rendered)
        self.assertIn('Não há atendimento atual autorizado', rendered)

    def test_clinician_only_sees_own_appointments_in_patient_chart_call(self):
        colleague = User.objects.create_user(email='room-colleague@test.invalid', tenant=self.tenant, role='professional')
        professional = Professional.objects.create(tenant=self.tenant, user=colleague, name='Colega')
        # Owner has administrative agenda visibility; clinical role is separately restricted.
        self.owner.role='professional';self.owner.save()
        other = Appointment.objects.create(tenant=self.tenant, customer=self.patient, professional=professional,
            service=self.service, starts_at=self.appointment.starts_at, ends_at=self.appointment.ends_at)
        with patch('healthcare.operation_access.assert_clinical_access'):
            request=self.client.get(reverse('waiting-room-console')).wsgi_request
            rendered=Template('{% load room_calls %}{% patient_tv_call patient_id %}').render(RequestContext(request, {'patient_id':self.patient.pk}))
            self.assertIn(f'value="{self.appointment.pk}"', rendered)
            self.assertNotIn(f'value="{other.pk}"', rendered)
            self.assertEqual(self.call(appointment=other.pk).status_code,404)
