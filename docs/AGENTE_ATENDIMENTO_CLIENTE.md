# Especialista em atendimento ao cliente

Perfil disponível no construtor do chatbot Master e no chatbot da empresa. Não é ativado automaticamente e não substitui fluxos publicados.

## Aplicar ao fluxo

1. Abra WhatsApp → Configurar chatbot (empresa) ou WhatsApp Master → Construtor de atendimento.
2. Para um fluxo completo, clique em **Especialista em atendimento pronto**. O botão substitui somente o rascunho, depois de confirmação; exporte o fluxo anterior se quiser preservá-lo separadamente.
3. Para manter sua estrutura, selecione um bloco **Agente IA** e habilite **Especialista em atendimento com transferência segura**. Conecte sucesso ao próximo passo e falha ao atendimento humano.
4. Configure/habilite a IA central no Master com modelo e chave OpenAI próprios. As empresas reutilizam essa configuração sem acesso à chave.
5. Teste no simulador. Ele não envia WhatsApp nem chama o provedor; simula respostas e testa transferências determinísticas.
6. Revise os blocos, salve o fluxo e habilite as respostas automáticas com o WhatsApp conectado. Faça uma conversa real controlada para homologar modelo, faturamento da API e entrega.

## Comportamento

- Boas-vindas identificam o assistente virtual; não finge ser humano.
- Respostas reais selecionam apenas textos aprovados do ApPlanner ou do catálogo público da empresa. O provedor não escreve preços ou confirmações livremente.
- Encaminha pedido de atendente, reclamação/reembolso, pagamento informado como pendente e envio explícito de credencial.
- Perguntas sem resposta aprovada e repetição da mesma pergunta/orientação são encaminhadas à equipe.
- Triagem existente coleta dados progressivamente: leads no Master; cliente/unidade/necessidade na empresa. Não concede consentimento de marketing.
- Intenção e motivo ficam no contexto criptografado da conversa; no Master também entram nas observações de um lead já identificado.
- Ao transferir, interrompe o percurso automático e cancela respostas anteriores ainda na fila. Mensagens já enviadas não podem ser retiradas.
- Não cria reservas, estornos, descontos ou confirmação de recebimento. O agendamento ocorre no link e nos serviços existentes.

## Limites e privacidade

As instruções do perfil especialista são controladas no servidor. Para outros agentes livres, desative o perfil; a empresa continua limitada à sua base pública.

O provedor recebe a mensagem atual, a política fixa e a base pública selecionada. Nome, telefone e outros campos coletados não são incluídos como contexto adicional. O texto digitado pode conter dados pessoais: não solicite documentos, cartões, senhas ou códigos pelo chatbot.

A memória de repetição permanece no contexto criptografado existente e é apagada quando a conversa/fluxo é reiniciado. Ela não constitui um histórico completo enviado à IA.

Handoff depende da equipe acompanhar a central. O bot não promete prazo, disponibilidade de atendente ou uma solução já executada. A avaliação com mocks/simulador não comprova a entrega real do WhatsApp ou a qualidade do modelo escolhido.

## Atualizar a base de conhecimento

No Master, as perguntas frequentes públicas ativas complementam a base padrão do ApPlanner (até 20 respostas, limitadas por tamanho). Respostas desativadas não são enviadas. Mantenha preços nos planos cadastrados e não publique credenciais nessa base.

Nas empresas, atualize serviços, unidades, horários, equipe, contatos, comodidades e formas de pagamento cadastradas por unidade. A IA consulta somente a empresa da conversa. Informações ausentes devem ser confirmadas pela equipe.
