"""Audit codes ("master.patient_record.viewed") as sentences the Master can read."""

CATEGORIES = {
    "prontuario": ("Prontuários", ("master.patient_record", "clinical.", "healthcare.", "dental.", "medical_record")),
    "caixa": ("Caixa e financeiro", ("clinic.cash", "clinic.receipt", "clinic.expense", "clinic.charge", "finance.")),
    "acesso": ("Acessos e usuários", ("master.access", "access.", "user.", "auth.", "accounts.", "legal.")),
    "cobranca": ("Assinatura e cobranças", ("billing.", "subscription.", "payment.", "master.charge")),
    "cadastro": ("Cadastro da empresa", ("tenant.", "company.", "master.company", "master.resource", "simple_mode")),
}

EXACT = {
    "master.patient_record.viewed": "Master abriu um prontuário",
    "master.patient_records.listed": "Master consultou a lista de prontuários",
    "clinical.patient_sheets.imported": "Fichas antigas importadas para o prontuário",
    "clinic.cash.opened": "Caixa do dia aberto",
    "clinic.cash.closed": "Caixa fechado com conferência",
    "clinic.cash_entry.created": "Lançamento feito no caixa",
    "clinic.cash_entry.updated": "Lançamento do caixa alterado",
    "clinic.cash_entry.cancelled": "Lançamento do caixa cancelado",
    "clinic.cash_report.recalculated": "Conferência do caixa recalculada após correção",
    "clinic.cash_report.correction_requested": "Correção de caixa fechado solicitada",
    "clinic.cash_report.correction_approved": "Correção de caixa fechado autorizada",
    "clinic.cash_report.correction_rejected": "Correção de caixa fechado recusada",
    "master.access_release.sent": "E-mail de boas-vindas enviado (liberar acesso)",
}

WORDS = {
    "created": "criado", "updated": "alterado", "deleted": "excluído", "cancelled": "cancelado", "viewed": "consultado",
    "approved": "aprovado", "rejected": "recusado", "sent": "enviado", "opened": "aberto", "closed": "fechado",
    "archived": "arquivado", "restored": "restaurado", "imported": "importado", "paid": "pago", "released": "liberado",
    "login": "entrada", "logout": "saída", "enabled": "ativado", "disabled": "desativado", "requested": "solicitado",
}


def category(action):
    action = action or ""
    for key, (_, prefixes) in CATEGORIES.items():
        if action.startswith(prefixes):
            return key
    return "outros"


def describe(action):
    """Readable sentence; unknown codes become 'Área: palavra palavra' instead of the raw code."""
    action = action or ""
    if action in EXACT:
        return EXACT[action]
    parts = action.replace("-", "_").split(".")
    if len(parts) < 2:
        return action.replace("_", " ").capitalize() or "Alteração"
    area = " ".join(parts[:-1]).replace("_", " ")
    verb = WORDS.get(parts[-1], parts[-1].replace("_", " "))
    area = area.replace("master ", "Master · ").replace("clinic ", "clínica · ")
    return f"{area.capitalize()}: {verb}"


ROLES = {"owner": "Responsável", "tenant-admin": "Administrador", "manager": "Gestor", "reception": "Recepção",
         "professional": "Profissional", "healthcare": "Profissional de saúde", "finance": "Financeiro", "user": "Usuário",
         "master-finance": "Master financeiro", "master-support": "Master suporte", "master-commercial": "Master comercial"}


def role_label(role):
    return ROLES.get(role or "", (role or "").replace("-", " ").capitalize())
