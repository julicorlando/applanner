"""What the clinic's front desk may do, decided by the clinic's manager (gestor).

Stored per company in tenant.metadata["reception_permissions"]; only the reception role is limited.
Every change is audited.
"""
from django.core.exceptions import PermissionDenied

MANAGERS = {"owner", "tenant-admin", "manager"}

PERMISSIONS = [
    ("prontuarios", "Ver os prontuários dos pacientes", True),
    ("evolucao", "Registrar evolução e plano de tratamento no prontuário", True),
    ("cadastro", "Cadastrar e editar pacientes", True),
    ("agenda", "Ver a agenda e agendar atendimentos", True),
    ("caixa", "Receber pagamentos no caixa", True),
    ("despesas", "Lançar despesas", True),
    ("abrir_fechar", "Abrir e fechar caixas", True),
    ("dias_anteriores", "Lançar e corrigir em dias anteriores e em caixas já fechados", True),
    ("apagar_lancamento", "Apagar lançamento do caixa sem pedir ao gestor", False),
]
LABELS = {key: label for key, label, _ in PERMISSIONS}


def current(tenant):
    stored = (getattr(tenant, "metadata", None) or {}).get("reception_permissions") or {}
    values = {key: bool(stored.get(key, default)) for key, _, default in PERMISSIONS}
    if (tenant.metadata or {}).get("clinical_reception_billing") is False and not stored:
        for key in ("caixa", "despesas", "abrir_fechar"):  # antiga chave "recepção não opera o caixa"
            values[key] = False
    return values


def allowed(user, key):
    """Only the reception role is limited; everyone else follows their own role."""
    if getattr(user, "role", "") != "reception" or not getattr(user, "tenant_id", None):
        return True
    return current(user.tenant).get(key, False)


def require(user, key):
    if not allowed(user, key):
        raise PermissionDenied(f"O gestor não liberou para a recepção: {LABELS[key].lower()}.")


def is_manager(user):
    return getattr(user, "role", "") in MANAGERS


def save(tenant, user, values, request=None):
    from core.audit import append_audit
    if not is_manager(user) or user.tenant_id != tenant.pk:
        raise PermissionDenied("Somente o gestor da empresa altera as permissões da recepção.")
    before = current(tenant)
    after = {key: bool(values.get(key)) for key, _, _ in PERMISSIONS}
    metadata = dict(tenant.metadata or {})
    metadata["reception_permissions"] = after
    metadata.pop("clinical_reception_billing", None)
    type(tenant).objects.filter(pk=tenant.pk).update(metadata=metadata)
    tenant.metadata = metadata
    append_audit(tenant=tenant, user=user, request=request, action="clinic.reception_permissions.updated",
                 entity_type="Tenant", entity_id=tenant.pk, before=before, after=after)
    return after
