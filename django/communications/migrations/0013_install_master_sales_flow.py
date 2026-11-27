from django.db import migrations
from django.utils import timezone

GRAPH = {'version': 2, 'start': 'start', 'nodes': [{'id': 'start', 'type': 'start', 'label': 'Boas-vindas', 'x': 600, 'y': 40, 'config': {'text': 'Olá! Que bom ter você por aqui 😊 Sou o assistente virtual do ApPlanner. Posso ajudar a conhecer o sistema e escolher uma solução para seu negócio.'}, 'outputs': {'next': 'menu'}}, {'id': 'menu', 'type': 'menu', 'label': 'Como podemos ajudar?', 'x': 600, 'y': 260, 'config': {'text': 'O que você gostaria de fazer agora?', 'options': [{'id': 'planos', 'label': 'Conhecer planos e valores', 'keywords': ['planos', 'preço', 'precos', 'valores']}, {'id': 'duvidas', 'label': 'Tirar uma dúvida sobre o sistema', 'keywords': ['dúvida', 'duvida', 'sistema']}, {'id': 'equipe', 'label': 'Receber orientação da equipe', 'keywords': ['contratar', 'proposta', 'ajuda']}]}, 'outputs': {'planos': 'planos', 'duvidas': 'pergunta', 'equipe': 'cadastro', 'invalid': 'resposta_livre'}}, {'id': 'planos', 'type': 'message', 'label': 'Planos atuais', 'x': 150, 'y': 550, 'config': {'text': 'Estas são as opções cadastradas hoje:\n{{public_plans}}'}, 'outputs': {'next': 'cadastro'}}, {'id': 'pergunta', 'type': 'input', 'label': 'Sua dúvida', 'x': 600, 'y': 550, 'config': {'text': 'Pode me contar sua dúvida com suas palavras.', 'variable': 'pergunta', 'validation': 'text'}, 'outputs': {'next': 'resposta'}}, {'id': 'resposta', 'type': 'knowledge', 'label': 'Orientação sobre o sistema', 'x': 600, 'y': 800, 'config': {'variable': 'pergunta'}, 'outputs': {'next': 'seguir'}}, {'id': 'resposta_livre', 'type': 'knowledge', 'label': 'Dúvida livre', 'x': 1050, 'y': 550, 'config': {'variable': '_message'}, 'outputs': {'next': 'seguir'}}, {'id': 'seguir', 'type': 'menu', 'label': 'Próximo passo', 'x': 1050, 'y': 850, 'config': {'text': 'Como você prefere continuar?', 'options': [{'id': 'mais', 'label': 'Tenho outra dúvida', 'keywords': ['dúvida', 'outra', 'mais']}, {'id': 'dados', 'label': 'Quero uma orientação ou proposta', 'keywords': ['proposta', 'contratar', 'equipe']}, {'id': 'fim', 'label': 'Por enquanto é só, obrigado', 'keywords': ['obrigado', 'sair']}]}, 'outputs': {'mais': 'pergunta', 'dados': 'cadastro', 'fim': 'fim', 'invalid': 'resposta_livre'}}, {'id': 'cadastro', 'type': 'commercial', 'label': 'Cadastro automático do lead', 'x': 150, 'y': 1050, 'config': {}, 'outputs': {'next': 'humano'}}, {'id': 'humano', 'type': 'handoff', 'label': 'Equipe ApPlanner', 'x': 150, 'y': 1350, 'config': {'text': 'Nossa equipe recebeu sua solicitação e continuará por aqui assim que estiver disponível. Enquanto isso, pode deixar uma observação nesta conversa.'}, 'outputs': {}}, {'id': 'fim', 'type': 'finish', 'label': 'Até logo', 'x': 1050, 'y': 1200, 'config': {'text': 'Foi um prazer ajudar! Quando precisar, pode chamar por aqui 😊'}, 'outputs': {}}]}


def install(apps,schema_editor):
    Flow=apps.get_model('communications','MasterWhatsAppFlow')
    flow=Flow.objects.using(schema_editor.connection.alias).filter(pk=1).first()
    if not flow:return
    # Keep the operator's enabled flag and encrypted integration credentials.
    flow.graph=GRAPH
    flow.updated_at=timezone.now()
    flow.save(using=schema_editor.connection.alias,update_fields=['graph','updated_at'])


class Migration(migrations.Migration):
    dependencies=[('communications','0012_masterwhatsappconversation_sales_lead')]
    operations=[migrations.RunPython(install,migrations.RunPython.noop)]
