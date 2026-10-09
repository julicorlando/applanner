from datetime import time
from django.test import TestCase
from django.urls import reverse
from core.portal import _model_form, _value, PORTAL_MODULES
from core.templatetags.display_pt import homologation_record
from core.test_post_deploy_fixes import PostDeployFixesTests
from operations.models import SupportTicket
from tenants.models import Unit, UnitBusinessHours
from scheduling.models import Appointment, Professional, Service
from billing.models import TenantModuleAddon


class AuditUXTests(TestCase):
    def setUp(self):
        PostDeployFixesTests.setUp(self)

    def test_unit_is_named_once_in_agenda_and_form(self):
        unit=Unit.objects.create(tenant=self.tenant,name=self.tenant.name)
        appointment=PostDeployFixesTests.appointment(self,unit=unit,status='confirmed')
        self.assertEqual(_value(appointment,'unit'),unit.name)
        form=_model_form(Appointment,PORTAL_MODULES['agenda']['resources']['agendamentos'],tenant=self.tenant,unit=unit)
        self.assertEqual(form.fields['unit'].label_from_instance(unit),unit.name)
        response=self.client.get(reverse('portal-resource-list',args=['agenda','agendamentos']))
        self.assertNotContains(response,f'{self.tenant.name} — {unit.name}')

    def test_guide_follows_selected_unit_without_counting_another_team(self):
        first=Unit.objects.create(tenant=self.tenant,name='Centro',address='Rua A',city='Recife',state='PE')
        second=Unit.objects.create(tenant=self.tenant,name='Norte')
        self.professional.unit=first
        self.professional.save()
        self.service.unit=first
        self.service.save()
        UnitBusinessHours.objects.create(tenant=self.tenant,unit=first,weekday=4,opens_at=time(9),closes_at=time(18))
        response=self.client.get(reverse('portal-setup'),{'unit':first.pk})
        self.assertEqual(response.context['setup_unit'],first)
        self.assertTrue(all(step['done'] for step in response.context['guided_steps'][:5]))
        self.assertEqual([step['title'] for step in response.context['guided_steps'][2:5]],
            ['Cadastre sua equipe','Defina horários de atendimento compatíveis com os serviços','Cadastre serviços e responsáveis'])
        response=self.client.get(reverse('portal-setup'),{'unit':second.pk})
        self.assertFalse(any(step['done'] for step in response.context['guided_steps'][:5]))
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.onboarding_step,5)

    def test_extra_request_is_a_draft_until_owner_submits_and_does_not_activate_addon(self):
        url=reverse('portal-resource-create',args=['suporte','chamados'])
        response=self.client.get(url,{'request':'professional-extra'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Informe o valor vigente definido pelo Master')
        self.assertFalse(SupportTicket.objects.exists())
        initial=response.context['form'].initial
        response=self.client.post(url,initial)
        self.assertEqual(response.status_code,302)
        ticket=SupportTicket.objects.get()
        self.assertEqual(ticket.tenant,self.tenant)
        self.assertEqual(ticket.user,self.owner)
        self.assertEqual(ticket.category,'professional-extra')
        self.assertFalse(TenantModuleAddon.objects.exists())
        self.assertEqual(Professional.objects.filter(tenant=self.tenant,active=True).count(),2)

    def test_homologation_badge_preserves_records_and_does_not_match_normal_names(self):
        appointment=PostDeployFixesTests.appointment(self,status='confirmed')
        self.assertFalse(homologation_record(appointment))
        self.service.name='Serviço QA — Auditoria'
        self.service.save()
        self.assertTrue(homologation_record(appointment))
        response=self.client.get(reverse('portal-resource-list',args=['agenda','agendamentos']))
        self.assertContains(response,'title="Identificado pelo nome do cadastro. Revise antes de atender."')
        appointment.refresh_from_db()
        self.assertEqual(appointment.status,'confirmed')
        self.assertFalse(homologation_record(Service(name='Esquadria')))
        self.assertFalse(homologation_record(Professional(name='Ana QA Consultoria')))
