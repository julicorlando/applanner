from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, RequestFactory
from django.urls import reverse

from accounts.models import User
from scheduling.models import Appointment, Customer, Professional, ProfessionalAvailability, ProfessionalBreak, Service
from tenants.models import Tenant, Unit
from .workspace import navigation
from .calendar_windows import open_windows


class SidebarCalendarTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Demonstração', slug='sidebar-demo', category='Barbearia', status='active')
        self.unit = Unit.objects.create(tenant=self.tenant, name='Centro', is_primary=True)
        self.owner = User.objects.create_user(email='sidebar-owner@example.test', role='owner', tenant=self.tenant)
        self.pro = Professional.objects.create(tenant=self.tenant, unit=self.unit, name='Ana')
        self.service = Service.objects.create(tenant=self.tenant, unit=self.unit, name='Corte', duration_minutes=30, price=40)
        self.customer = Customer.objects.create(tenant=self.tenant, name='Cliente', phone='81900001111')
        self.tz = ZoneInfo('America/Recife')
        self.day = date(2030, 2, 4)
        ProfessionalAvailability.objects.create(tenant=self.tenant, professional=self.pro, weekday=1, start_time=time(9), end_time=time(18))
        ProfessionalBreak.objects.create(tenant=self.tenant, professional=self.pro, weekday=1, start_time=time(12), end_time=time(13))

    def request(self, user, path='/app/'):
        request = RequestFactory().get(path)
        request.user = user
        request.session = {}
        return request

    def test_master_sidebar_contains_entire_resource_catalog_and_centres(self):
        from .master import MASTER_RESOURCES
        master = User.objects.create_superuser(email='sidebar-master@example.test', password='Local-test-1!')
        data = navigation(self.request(master, '/master/'))
        urls = [item['url'] for group in data['workspace_groups'] for item in group['items']]
        self.assertEqual(len(urls), len(set(urls)))
        for slug in MASTER_RESOURCES:
            self.assertIn(reverse('master-resource-list', args=[slug]), urls)
        self.assertIn(reverse('master-homepage'), urls)
        self.assertIn(reverse('master-platform-payment'), urls)

    def test_private_shell_has_sidebar_and_no_topbar_for_owner_and_professional(self):
        for role in ['owner', 'professional']:
            user = self.owner if role == 'owner' else User.objects.create_user(email='sidebar-pro@example.test', role=role, tenant=self.tenant)
            self.client.force_login(user)
            response = self.client.get('/account/2fa/setup/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'id="workspace-sidebar"')
            self.assertNotContains(response, '<header class="topbar">')
            self.assertContains(response, 'Logo ApPlanner')
            self.assertContains(response, 'action="/account/logout/"')

    def test_month_boundaries_leap_year_navigation_and_scope(self):
        self.client.force_login(self.owner)
        with patch('core.calendar_view.access', return_value=(self.tenant, self.unit, False)):
            response = self.client.get(reverse('operation-calendar'), {'mode': 'month', 'date': '2032-02-15'})
        self.assertEqual(response.status_code, 200)
        columns = response.context['columns']
        self.assertEqual(columns[0]['day'].weekday(), 0)
        self.assertIn(date(2032, 2, 29), [column['day'] for column in columns])
        self.assertEqual(response.context['previous'], date(2032, 1, 1))
        self.assertEqual(response.context['next'], date(2032, 3, 1))
        self.assertContains(response, 'calendar-board--month')
        outsider = Professional.objects.create(tenant=Tenant.objects.create(name='Outra', slug='sidebar-other'), name='Outro')
        with patch('core.calendar_view.access', return_value=(self.tenant, self.unit, False)):
            response = self.client.get(reverse('operation-calendar'), {'resource': outsider.pk})
        self.assertEqual(response.status_code, 404)

    def test_open_windows_subtract_break_booking_and_buffer(self):
        from scheduling.models import TenantScheduleSettings
        TenantScheduleSettings.objects.create(tenant=self.tenant, buffer_minutes=10)
        row = Appointment.objects.create(tenant=self.tenant, unit=self.unit, professional=self.pro, service=self.service, customer=self.customer,
            starts_at=datetime(2030, 2, 4, 10, tzinfo=self.tz), ends_at=datetime(2030, 2, 4, 11, tzinfo=self.tz), status='confirmed')
        windows = open_windows(self.tenant, self.unit, [self.pro], [self.day], [row], [], self.tz)[self.day]
        self.assertEqual([(item['start'].strftime('%H:%M'), item['end'].strftime('%H:%M')) for item in windows], [('09:00', '09:50'), ('11:10', '12:00'), ('13:00', '18:00')])
        self.assertEqual(open_windows(self.tenant, self.unit, [self.pro], [self.day + timedelta(days=1)], [], [], self.tz)[self.day + timedelta(days=1)], [])

    def test_billing_lock_keeps_only_payment_and_no_management(self):
        request = self.request(self.owner)
        request.billing_locked = True
        urls = [item['url'] for group in navigation(request)['workspace_groups'] for item in group['items']]
        self.assertEqual(urls, [reverse('billing-subscription-status')])

    def test_professional_calendar_only_exposes_own_rows(self):
        user = User.objects.create_user(email='calendar-professional@example.test', role='professional', tenant=self.tenant)
        self.pro.user = user
        self.pro.save(update_fields=['user'])
        other = Professional.objects.create(tenant=self.tenant, unit=self.unit, name='Outra pessoa')
        for professional in [self.pro, other]:
            Appointment.objects.create(tenant=self.tenant, unit=self.unit, professional=professional, service=self.service, customer=self.customer,
                starts_at=datetime(2030, 2, 4, 10, tzinfo=self.tz), ends_at=datetime(2030, 2, 4, 11, tzinfo=self.tz), status='confirmed')
        self.client.force_login(user)
        response = self.client.get(reverse('operation-calendar'), {'date': '2030-02-04', 'mode': 'day'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([resource.pk for resource in response.context['resources']], [self.pro.pk])
        self.assertEqual(response.context['appointment_count'], 1)
        self.assertFalse(response.context['can_move'])

    def test_arena_windows_account_for_real_blocks(self):
        from arena.models import Court, CourtHours, CourtBlock
        court = Court.objects.create(tenant=self.tenant, unit=self.unit, name='Quadra', slug='court-test')
        CourtHours.objects.create(tenant=self.tenant, court=court, weekday=1, start_time=time(9), end_time=time(18))
        block = CourtBlock.objects.create(tenant=self.tenant, court=court, starts_at=datetime(2030, 2, 4, 12, tzinfo=self.tz), ends_at=datetime(2030, 2, 4, 14, tzinfo=self.tz))
        windows = open_windows(self.tenant, self.unit, [court], [self.day], [], [block], self.tz, arena=True)[self.day]
        self.assertEqual([(item['start'].hour, item['end'].hour) for item in windows], [(9, 12), (14, 18)])
