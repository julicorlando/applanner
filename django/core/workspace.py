"""Desktop navigation uses the portal's existing entitlement and RBAC decisions."""

from django.urls import reverse


def navigation(request):
    user = getattr(request, "user", None)
    commercial_workspace = request.path.startswith("/commercial/") and not request.path.startswith(("/commercial/c/", "/commercial/proposta/"))
    private = commercial_workspace or request.path == "/" or request.path.startswith(
        ("/app/", "/master/", "/billing/", "/account/")
    )
    if not user or not user.is_authenticated or not private:
        return {}

    def link(title, url, icon="home"):
        return {"title": title, "url": url, "icon": icon, "active": request.path == url}

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
    elif user.is_superuser and (
        request.path == "/" or request.path.startswith("/master/") or commercial_workspace
    ):
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
                    )
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
                groups.append({"title": module["title"], "items": items})
    if not groups:
        return {}
    return {
        "workspace_groups": groups,
        "workspace_master": user.is_superuser
        and (request.path == "/" or request.path.startswith("/master/") or commercial_workspace),
    }
