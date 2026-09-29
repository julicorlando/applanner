"""Validated, Master-editable copy for essential platform e-mails."""

from html import escape
from string import Formatter

TEMPLATES={
    "account_created":{
        "label":"Conta criada",
        "subject":"Bem-vindo ao ApPlanner, {nome}",
        "body":"Olá, {nome}!\n\nSua conta para {empresa} foi criada. Complete o cadastro e confirme seu e-mail para publicar a página da empresa.\n\nAcesse: {url_inicio}\n\nEquipe ApPlanner",
        "variables":{"nome","empresa","url_inicio"},"required":{"url_inicio"},"action":"url_inicio",
    },
    "email_verification":{
        "label":"Confirmar e-mail da conta",
        "subject":"Confirme seu e-mail no ApPlanner",
        "body":"Olá, {nome}!\n\nConfirme seu e-mail usando o link abaixo em até 24 horas:\n{url_confirmacao}\n\nSe você não criou esta conta, ignore a mensagem.",
        "variables":{"nome","empresa","url_confirmacao"},"required":{"url_confirmacao"},"action":"url_confirmacao",
    },
    "account_confirmed":{
        "label":"Conta confirmada",
        "subject":"Seu e-mail foi confirmado no ApPlanner",
        "body":"Olá, {nome}!\n\nSeu e-mail foi confirmado. Você já pode continuar a configuração de {empresa}.\n\nAcesse: {url_inicio}",
        "variables":{"nome","empresa","url_inicio"},"required":{"url_inicio"},"action":"url_inicio",
    },
    "password_reset":{
        "label":"Esqueceu a senha",
        "subject":"Redefina sua senha no ApPlanner",
        "body":"Olá, {nome}!\n\nUse o link abaixo em até 1 hora para redefinir sua senha:\n{url_redefinicao}\n\nSe não foi você, ignore a mensagem.",
        "variables":{"nome","empresa","url_redefinicao"},"required":{"url_redefinicao"},"action":"url_redefinicao",
    },
    "booking_confirmation":{
        "label":"Agendamento confirmado",
        "subject":"Agendamento confirmado em {empresa}",
        "body":"Olá, {nome}!\n\nSeu agendamento em {empresa} foi confirmado.\nServiço: {servico}\nProfissional: {profissional}\nData e horário: {data_hora}\n\nAté breve!",
        "variables":{"nome","empresa","servico","profissional","data_hora"},"required":{"data_hora","servico"},"action":None,
    },
}


def validate_copy(key,subject,body):
    spec=TEMPLATES[key]
    if not subject.strip() or not body.strip():
        raise ValueError("Assunto e mensagem são obrigatórios.")
    body_fields=set()
    for index,source in enumerate((subject,body)):
        try:
            chunks=list(Formatter().parse(source))
        except ValueError as exc:
            raise ValueError("Chaves inválidas. Para escrever { ou } no texto, duplique as chaves.") from exc
        for _,field,fmt,conversion in chunks:
            if field is None:
                continue
            if field not in spec["variables"] or fmt or conversion:
                raise ValueError(f"Variável não permitida: {field}. Use apenas as opções exibidas.")
            if index==1:
                body_fields.add(field)
    for field in spec["required"]:
        if field not in body_fields:
            raise ValueError(f"A mensagem precisa conter {{{field}}}.")
    if "\r" in subject or "\n" in subject:
        raise ValueError("O assunto deve ocupar apenas uma linha.")


def render_email(key,values):
    from operations.models import PlatformEmailTemplate
    spec=TEMPLATES[key]
    row=PlatformEmailTemplate.objects.filter(pk=key).first()
    subject=row.subject if row else spec["subject"]
    body=row.body if row else spec["body"]
    validate_copy(key,subject,body)
    safe_values={name:str(values.get(name) or "") for name in spec["variables"]}
    subject=subject.format_map(safe_values).replace("\r"," ").replace("\n"," ")
    text=body.format_map(safe_values)
    html_text=escape(text).replace("\n","<br>")
    action=spec["action"]
    if action and safe_values[action].startswith(("https://","http://")):
        url=escape(safe_values[action],quote=True)
        html_text=html_text.replace(escape(safe_values[action]),f'<a href="{url}">{url}</a>')
    html=f'<div style="font:16px/1.6 Arial,sans-serif;color:#26334b;max-width:600px;margin:auto;padding:28px"><strong style="color:#3948ba;font-size:22px">ApPlanner</strong><p>{html_text}</p></div>'
    return subject,text,html


def queue_email(tenant,recipient,key,values,*,customer=None):
    """Persist a transactional message so SMTP failures never break signup or booking."""
    if not recipient:
        return None
    from communications.models import Notification
    subject,text,html=render_email(key,values)
    return Notification.objects.create(tenant=tenant,customer=customer,
        channel=Notification.Channel.EMAIL,destination=recipient,template_key=key,
        payload={"subject":subject,"text":text,"html":html})


def account_values(user,*,base_url):
    return {"nome":user.first_name or user.email.split("@")[0],
        "empresa":user.tenant.name if user.tenant_id else "ApPlanner",
        "url_inicio":base_url.rstrip("/")+"/inicio/"}
