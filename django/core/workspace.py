"""Desktop navigation uses the portal's existing entitlement and RBAC decisions."""

from django.urls import reverse


def navigation(request):
    user = getattr(request, "user", None)
    commercial_workspace = request.path.startswith("/commercial/") and not request.path.startswith(("/commercial/c/", "/commercial/proposta/"))
    private = commercial_workspace or request.path == "/" or request.path.startswith(
        ("/app/", "/master/", "/billing/", "/account/", "/admin/", "/legal/privacidade/meus-dados/")
    )
    if not user or not user.is_authenticated or not private:
        return {}

    def link(title, url, icon="home"):
        return {"title": title, "url": url, "icon": icon, "active": request.path == url}

    tenant = user.tenant if user.tenant_id else None
    if user.is_superuser and request.path.startswith('/app/'):
        from tenants.models import Tenant
        tenant = Tenant.objects.filter(pk=request.session.get('portal_tenant_id'), deleted_at__isnull=True, archived_at__isnull=True).first()
    groups = []
    if getattr(request, "billing_locked", False):
        groups = [
            {
                "title": "Assinatura",
                "items": [
                    link("Pagamento", reverse("billing-subscription-status"), "card")
                ],
            }
        ]
    elif user.is_superuser and not request.path.startswith('/app/'):
        groups = [
            {
                "title": "Plataforma",
                "items": [
                    link("Visão geral", reverse("master-home")),
                    link(
                        "Empresas",
                        reverse("master-resource-list", args=["empresas"]),
                        "users",
                    ),
                    link(
                        "Planos",
                        reverse("master-resource-list", args=["planos"]),
                        "card",
                    ),
                    link("Financeiro", reverse("master-finance-dashboard"), "card"),
                ],
            },
            {
                "title": "Relacionamento",
                "items": [
                    link(
                        "Leads",
                        reverse("master-resource-list", args=["leads"]),
                        "users",
                    ),
                    link("WhatsApp", reverse("master-whatsapp"), "chat"),
                    link("Campanhas", reverse("master-marketing"), "chat"),
                    link("Campanhas sociais", reverse("commercial-social-list"), "chat"),
                ],
            },
        ]
        from .master import MASTER_RESOURCES
        groups.append({'title': 'Todas as funções Master', 'items': [
            link(config['title'], reverse('master-resource-list', args=[slug]), 'home')
            for slug, config in MASTER_RESOURCES.items()
            if slug not in {'empresas', 'planos', 'leads'}
        ]})
        groups.append({'title': 'Centrais e configurações', 'items': [
            link(title, reverse(route), icon) for title, route, icon in [
                ('Importar base de clientes', 'master-customer-import', 'users'),
                ('Clientes de desenvolvimento', 'development-clients', 'users'),
                ('Comercial', 'commercial-dashboard', 'users'),
                ('Cadastro bancário', 'master-platform-payment', 'card'),
                ('Cobranças', 'master-charges', 'card'),
                ('Relatórios', 'master-reports', 'card'),
                ('Retenção', 'master-retention', 'users'),
                ('Saúde das empresas', 'master-company-health', 'users'),
                ('Monitoramento', 'master-runtime-monitor', 'home'),
                ('Alertas', 'master-alerts', 'home'),
                ('Personalização da plataforma', 'master-homepage', 'home'),
                ('E-mail SMTP', 'master-smtp-settings', 'chat'),
                ('Modelos de e-mail', 'master-email-templates', 'chat'),
                ('Fluxo WhatsApp', 'master-whatsapp-flow', 'chat'),
                ('Chatbot', 'master-chatbot', 'chat'),
                ('Push e SMS', 'master-delivery-providers', 'chat'),
                ('Central NFS-e', 'master-nfse-center', 'card'),
                ('Configuração fiscal', 'master-fiscal-settings', 'card'),
                ('Abrir operação de empresa', 'portal-home', 'home'),
            ]
        ]})
    elif user.role in {'master-finance', 'master-support', 'master-commercial'}:
        definitions = {
            'master-finance': [('Financeiro', 'master-finance-dashboard'), ('Cobranças', 'master-charges'), ('Relatórios', 'master-reports')],
            'master-support': [('Alertas', 'master-alerts'), ('Saúde das empresas', 'master-company-health'), ('Monitoramento', 'master-runtime-monitor')],
            'master-commercial': [('Retenção', 'master-retention'), ('Saúde das empresas', 'master-company-health')],
        }
        groups = [{'title': 'Plataforma', 'items': [link(title, reverse(route)) for title, route in definitions[user.role]]}]
        if user.role == 'master-support':
            groups[0]['items'].extend(link(title, reverse('master-resource-list', args=[slug])) for title, slug in [('Chamados', 'suporte'), ('Incidentes', 'incidentes')])
    elif commercial_workspace and not user.tenant_id:
        from commercial.models import CommercialProfile
        if CommercialProfile.objects.filter(user=user,active=True).exists():
            groups = [{"title":"Comercial", "items":[
                link("Funil de vendas",reverse("commercial-dashboard"),"users"),
                link("Campanhas sociais",reverse("commercial-social-list"),"chat"),
                link("Nova proposta",reverse("commercial-proposal-create"),"card"),
            ]}]
    elif user.role == "professional":
        groups = [
            {
                "title": "Meu trabalho",
                "items": [
                    link(
                        "Minha agenda e ganhos",
                        reverse("professional-area"),
                        "calendar",
                    ),
                    link('Bloqueios e pausas', reverse('professional-blocks'), 'calendar'),
                    link('Calendário · dia, semana e mês', reverse('operation-calendar'), 'calendar'),
                    link('Notificações', reverse('professional-notification-preferences'), 'chat'),
                    link('Indicações', reverse('professional-referrals'), 'users'),
                ],
            }
        ]
    else:
        from tenants.models import Tenant

        from .portal import available_modules

        tenant = user.tenant if user.tenant_id else None
        if user.is_superuser:
            tenant = Tenant.objects.filter(
                pk=request.session.get("portal_tenant_id"),
                deleted_at__isnull=True,
                archived_at__isnull=True,
            ).first()
        if tenant:
            groups.append(
                {
                    "title": "Visão geral",
                    "items": [
                        link("Dashboard", reverse("home")),
                        link("Central operacional", reverse("portal-home")),
                    ],
                }
            )
            icons = {
                "agenda": "calendar",
                "financeiro": "card",
                "comunicacao": "chat",
                "relacionamento": "users",
                "barbearia": "scissors",
                "arena": "calendar",
            }
            for module in available_modules(user, tenant):
                items = [
                    link(
                        resource["title"],
                        reverse(
                            "portal-resource-list",
                            args=[module["slug"], resource["slug"]],
                        ),
                        icons.get(module["slug"], "home"),
                    )
                    for resource in module["resources"]
                ]
                if module['slug']=='barbearia' and user.role not in ['reception','professional']:
                    items.insert(0,link('Agenda inteligente e retorno',reverse('beauty-intelligence'),'scissors'))
                groups.append({"title": module["title"], "items": items})
            routes = {(m['slug'], r['slug']) for m in available_modules(user, tenant) for r in m['resources']}
            if ('agenda', 'agendamentos') in routes or ('arena', 'reservas') in routes:
                groups[0]['items'].extend([
                    link('Agenda · dia, semana e mês', reverse('operation-calendar'), 'calendar'),
                    link('Atendimentos de hoje', reverse('operation-today'), 'calendar'),
                ])
            if ('agenda', 'expedientes') in routes:
                groups.append({'title': 'Cadastro em massa', 'items': [
                    link('Expediente e intervalo em massa', reverse('bulk-work-schedule'), 'calendar'),
                ]})
            from accounts.permissions import has_capability
            if has_capability(user, 'agenda.manage'):
                groups.append({'title': 'Configuração da operação', 'items': [
                    link('Primeiros passos', reverse('portal-setup')),
                    link('Personalização e logos', reverse('tenant-branding') + '?company=1'),
                    link('Configuração por unidade', reverse('unit-schedule-settings'), 'calendar'),
                    link('Diagnóstico', reverse('portal-diagnostics')),
                ]})
            if user.is_superuser or user.role in {'owner', 'manager', 'tenant-admin', 'barber-manager', 'arena-manager', 'auto-manager'}:
                groups.append({'title': 'Gestão e acessos', 'items': [
                    link('Indicadores', reverse('operation-performance'), 'card'),
                    link('Funil de agendamento', reverse('booking-funnel'), 'users'),
                    link('Acesso da recepção', reverse('reception-access'), 'users'),
                ]})
            if user.is_superuser or user.role == 'owner':
                groups[-1]['items'].extend([
                    link('Meu plano e pagamento', reverse('billing-subscription-status'), 'card'),
                    link('Recebimentos', reverse('tenant-payment-gateway'), 'card'),
                    link('Avaliações da equipe', reverse('tenant-ratings'), 'users'),
                    link('WhatsApp da empresa', reverse('tenant-whatsapp-settings'), 'chat'),
                ])
    if tenant and not getattr(request, "billing_locked", False):
        from django.core.exceptions import PermissionDenied
        from billing.entitlements import module_enabled
        from healthcare.services import assert_clinical_access
        try:
            assert_clinical_access(user)
        except PermissionDenied:
            pass
        else:
            clinical=[]
            if module_enabled(tenant,"dentistry"):
                clinical.append(link("Odontologia",reverse("dental-home"),"users"))
            if module_enabled(tenant,"physiotherapy"):
                clinical.append(link("Fisioterapia",reverse("portal-resource-list",args=["saude","prontuarios"]),"users"))
            if clinical:
                groups.append({"title":"Atendimento clínico","items":clinical})
    if not groups:
        groups = [{'title': 'Minha conta', 'items': [link('Início', '/'), link('Explorar estabelecimentos', reverse('public-directory'), 'calendar')]}]
    account = [link('Segurança da conta', '/account/2fa/setup/'),
               link('Documentação e API', reverse('accounts:documentation')),
               link('Meus dados e privacidade', reverse('legal-privacy-center'))]
    if user.is_superuser or (user.tenant_id and user.role != 'professional'):
        account.insert(0, link('Notificações neste dispositivo', reverse('user-notification-preferences'), 'chat'))
    if not getattr(request, 'billing_locked', False):
        groups.append({'title': 'Conta e ferramentas', 'items': account})
        if user.is_superuser or tenant:
            groups[-1]['items'].insert(0, link('Buscar', reverse('master-global-search' if user.is_superuser else 'professional-search' if user.role == 'professional' else 'operation-search'), 'users'))
        if user.is_superuser:
            groups[-1]['items'].append(link('Central Master', reverse('master-home')))
            if user.is_staff:
                groups[-1]['items'].append(link('Administração', '/admin/'))
    seen = set()
    for group in groups:
        group['items'] = [item for item in group['items'] if not (item['url'] in seen or seen.add(item['url']))]
    return {
        "workspace_groups": groups,
        "workspace_tenant": tenant,
        "workspace_master": user.is_superuser and not request.path.startswith('/app/'),
    }
