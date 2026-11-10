import unicodedata

from .models import SupportTicket


def classify_priority(category, subject, description):
    """Triagem inicial por regras; a equipe pode reclassificar após análise."""
    text=unicodedata.normalize("NFKD", f"{category} {subject} {description}".lower())
    text="".join(c for c in text if not unicodedata.combining(c))
    if any(term in text for term in ("vazamento de dados", "dados expostos", "acesso indevido", "sistema fora do ar", "sistema indisponivel", "nao consigo acessar nenhum", "cobranca duplicada")):
        return SupportTicket.Priority.URGENT
    if any(term in text for term in ("pagamento nao recebido", "pagamento nao aprovado", "agendamento nao funciona", "erro 500", "nao consigo entrar", "nao consigo agendar", "cobranca", "faturamento")):
        return SupportTicket.Priority.HIGH
    if any(term in text for term in ("duvida", "sugestao", "melhoria", "como faco")):
        return SupportTicket.Priority.LOW
    return SupportTicket.Priority.NORMAL
