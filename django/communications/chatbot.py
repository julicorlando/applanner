import unicodedata

from .models import WhatsAppConversation


def _normalize(value):
    text=unicodedata.normalize("NFKD",(value or "").casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


def next_reply(flow, conversation, incoming, *, first_message=False):
    """Uma resposta curta por mensagem; transferência sempre tem prioridade."""
    text=_normalize(incoming)
    if any(term in text for term in ("atendente","humano","pessoa","falar com alguem")):
        return flow.handoff,WhatsAppConversation.Status.WAITING_HUMAN
    if conversation.status!=WhatsAppConversation.Status.BOT:
        return None,conversation.status
    for rule in flow.rules:
        if any(_normalize(keyword) in text for keyword in rule.get("keywords",[]) if keyword):
            return rule["reply"],WhatsAppConversation.Status.BOT
    if first_message:
        return flow.greeting,WhatsAppConversation.Status.BOT
    return flow.fallback,WhatsAppConversation.Status.WAITING_HUMAN
