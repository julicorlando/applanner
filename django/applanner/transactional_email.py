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
    "referral_pix_request":{
        "label":"Indicação qualificada · solicitar Pix",
        "subject":"Sua indicação no ApPlanner foi qualificada",
        "body":"Olá, {nome}!\n\nA empresa indicada {empresa_indicada} concluiu os pagamentos necessários e sua recompensa de R$ {valor} foi liberada.\n\nCadastre sua chave Pix com segurança no ApPlanner:\n{url_pix}\n\nEquipe ApPlanner",
        "variables":{"nome","empresa_indicada","valor","url_pix"},"required":{"url_pix","valor"},"action":"url_pix",
    },
    "access_release":{
        "label":"Liberar acesso · boas-vindas",
        "subject":"Bem-vindo ao ApPlanner, {nome}",
        "body":"Olá, {nome}!\n\nÉ uma alegria ter você com a gente. O acesso de {empresa} ao ApPlanner foi liberado e sua conta já está pronta.\n\nPara começar, crie sua senha pessoal no botão abaixo. O link vale por {validade} e pode ser usado uma única vez.\n\n{url_senha}\n\nDepois é só entrar com o e-mail {email} e a senha que você criou. Pelo ApPlanner você acompanha a agenda, os clientes, a equipe e o financeiro em um só lugar.\n\nSe precisar de ajuda, é só responder este e-mail.\n\nSeja muito bem-vindo!\nEquipe ApPlanner",
        "variables":{"nome","empresa","email","url_senha","validade"},"required":{"url_senha"},"action":"url_senha",
        "layout":"welcome","button":"Clique aqui para gerar sua senha",
    },
    "account_deletion_approved":{
        "label":"Exclusão de conta aprovada",
        "subject":"Exclusão da conta de {empresa} concluída",
        "body":"Olá, {nome}!\n\nSua solicitação de exclusão da conta de {empresa} foi aprovada e concluída pelo ApPlanner. O acesso da empresa e dos usuários vinculados foi encerrado e a página pública foi desativada.\n\nRegistros que precisem ser preservados por obrigação legal, segurança ou auditoria poderão permanecer retidos pelo prazo aplicável, sem acesso operacional pela conta excluída.\n\nEquipe ApPlanner",
        "variables":{"nome","empresa"},"required":set(),"action":None,
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
    if spec.get("layout")=="welcome":
        return subject,text,_welcome_html(text,safe_values[action],spec["button"],values.get("_assets") or {})
    html=f'<div style="font:16px/1.6 Arial,sans-serif;color:#26334b;max-width:600px;margin:auto;padding:28px"><strong style="color:#3948ba;font-size:22px">ApPlanner</strong><p>{html_text}</p></div>'
    return subject,text,html


def _welcome_html(text,url,button,assets):
    """Branded welcome layout; the action URL becomes a button and stays as a fallback link."""
    safe_url=escape(url,quote=True)
    blocks=[]
    cta=('<table role="presentation" cellpadding="0" cellspacing="0" style="margin:26px auto"><tr>'
                '<td style="border-radius:12px;background:#0866e8">'
                f'<a href="{safe_url}" style="display:inline-block;padding:15px 30px;font:bold 16px Arial,sans-serif;'
                f'color:#ffffff;text-decoration:none;border-radius:12px">{escape(button)}</a></td></tr></table>')
    for block in text.split("\n\n"):
        if block.strip()==url:
            blocks.append(cta)
        elif block.strip():
            blocks.append('<p style="margin:0 0 16px">'+escape(block).replace("\n","<br>")+'</p>')
    if cta not in blocks:
        blocks.append(cta)
    logo=assets.get("logo")
    card=assets.get("card")
    head=(f'<img src="{escape(logo,quote=True)}" width="112" alt="ApPlanner" style="display:block;margin:0 auto;border:0;width:112px;height:auto">'
        if logo else '<strong style="font:bold 26px Arial,sans-serif;color:#102d40">ApPlanner</strong>')
    picture=(f'<tr><td style="padding:0 32px 8px"><img src="{escape(card,quote=True)}" width="536" alt="Painel do ApPlanner com agenda, clientes, equipe e financeiro" '
        'style="display:block;width:100%;max-width:536px;height:auto;border:1px solid #dfe6f0;border-radius:14px"></td></tr>') if card else ""
    return ('<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#eef3f9">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef3f9"><tr><td align="center" style="padding:28px 12px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border-radius:18px;overflow:hidden">'
        f'<tr><td align="center" style="padding:30px 32px 18px">{head}</td></tr>'
        '<tr><td align="center" style="padding:0 32px 22px;font:bold 24px/1.3 Arial,sans-serif;color:#102d40">Seu acesso ao ApPlanner foi liberado</td></tr>'
        f'{picture}'
        '<tr><td style="padding:22px 32px 8px;font:16px/1.6 Arial,sans-serif;color:#26334b">'+"".join(blocks)+'</td></tr>'
        '<tr><td style="padding:0 32px 28px;font:13px/1.5 Arial,sans-serif;color:#66748a">Se o botão não abrir, copie e cole este endereço no navegador:<br>'
        f'<a href="{safe_url}" style="color:#0866e8;word-break:break-all">{safe_url}</a></td></tr>'
        '</table>'
        '<p style="margin:16px 0 0;font:12px Arial,sans-serif;color:#8a96a8">ApPlanner · Você recebeu este e-mail porque sua empresa foi cadastrada na plataforma.</p>'
        '</td></tr></table></body></html>')


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
