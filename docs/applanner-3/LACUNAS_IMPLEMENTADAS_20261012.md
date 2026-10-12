# Evolução operacional após o PR26

Base: django-replatform cf780c0. Branch: feat/applanner-market-gaps-20261012.

## Escopo implementado

| Lacuna | Implementação concreta | Ativação e limite |
|---|---|---|
| DRE | Plano de contas: receitas, deduções/tributos, custos diretos, despesas operacionais/financeiras, resultado e margem; natureza fixa/variável. CMV, insumos, comissões e taxas derivados de snapshots e registros reais. Descontos reconstruídos nas linhas bruta/deduções. Escopo empresa/unidade e avisos para lançamentos sem classificação/competência | Classificar categorias e registrar tributos/depreciação pela gestão; não é escrituração fiscal ou homologação contábil. Não duplicar custos automáticos em lançamentos manuais |
| Fluxo financeiro | Recebimentos de vendas/comandas, sinais online, saldo na conclusão, taxas e recebimentos de vale na emissão | Registros e conciliação são a fonte; estornos/movimentações fora do sistema exigem lançamento e conferência. Sangria/suprimento são transferências internas |
| Comissões por metas | Políticas por profissional/serviço/produto, vigência, até 20 faixas percentuais, meta mensal nos eventos comissionados, dedução de insumos e snapshot imutável do cálculo | Ativar no financeiro. Taxa alcançada aplica-se ao evento atual, sem alterar eventos anteriores. Regras fixas/percentuais antigas preservadas quando não há política aplicável. Vigências ambíguas bloqueiam fechamento |
| Vale-presente | Emissão após recebimento, código aleatório exibido uma vez e armazenado como hash; validade, saldo, uso parcial em comanda, estorno sem apagar pagamento, idempotência e auditoria | Gestor emite; recepção pode aplicar em comanda sem acesso a emissão/financeiro. Não aceita crédito fictício informado pelo cliente como pagamento genérico |
| Grupos/franquias | Convite a empresas, aprovação/revogação por cada empresa, visão financeira agregada, proposta mensal de royalties com receita/taxa congeladas e aprovação de despesa pendente pela empresa | Não concede acesso cruzado a clientes/agendas/credenciais. Não executa débito ou cobrança automática. Apuração somente de meses encerrados |
| Cartão antecipado | Card Payment Brick oficial tokeniza; preço e destino definidos no backend; nonce, trava da reserva, exclusão de cobranças simultâneas Pix/cartão, conciliação assinada e periódica, validação de valor/moeda/ambiente/recebedor/referência | Depende de cadastro bancário conectado, chave pública e ativação de cartão nas configurações de agenda. PAN/CVV não são aceitos pelo endpoint. Resposta incerta mantém pagamento pendente e bloqueia nova tentativa. Autorização sem captura não é pagamento confirmado |
| Web Push | VAPID protegido no servidor, inscrição por identidade autenticada/cliente verificado, consentimento no navegador, mensagens criptografadas, fila/deduplicação, expiração, desativação de endpoints inválidos, service worker com navegação apenas na mesma origem | Master ativa. Usuário permite no próprio dispositivo. Mensagens genéricas sem dados de clientes no bloqueio de tela. Entrega aceita pelo serviço não equivale a leitura. Dispositivo físico iOS/Android ainda precisa de homologação |
| SMS | Adapter Twilio real, token criptografado, quota mensal aprovada pelo Master, ativação pela empresa, consentimento do cliente vinculado ao telefone, confirmação/cancelamento/lembrete, consulta de status de entrega | Desligado por padrão. Exige conta e remetente aprovados, custos/regras do provedor e consentimento. Mudança de telefone invalida autorização. Resposta indeterminada não é submetida novamente de forma automática |

## Integridade

- Ordem de travas de estoque padronizada entre receitas, vendas e comandas.
- Atendimento com comanda não pode ser encerrado novamente pelo fluxo do profissional.
- Pagamentos estornados do vale continuam registrados; apenas são marcados e excluídos do saldo ativo.
- Critérios de comissão congelados no registro de origem; editar faixas não reescreve valores passados.
- Redeploy preserva variáveis, chaves de criptografia, PostgreSQL/Redis e volume media existentes.
- Migrations aditivas: finance0010, barber0002, scheduling0023, communications0015, tenants0013. Bootstrap existente aplica migrations, novas tarefas Beat, seeds e estáticos.
- Nova dependência: pywebpush (criptografia/protocolo Web Push); integridade/vulnerabilidades verificadas no CI.

## Roteiro de ativação após homologação

1. Financeiro → DRE/plano de contas: classificar categorias, conferir competência e validar comparação com registros do período.
2. Financeiro → comissões por metas: cadastrar vigência e faixas, testar serviço/produto/insumos e comparar snapshot no registro da comissão.
3. Financeiro → vale-presente: registrar recebimento real, emitir e entregar código; aplicar pelo link da comanda; conferir saldo, caixa, DRE e estorno.
4. Financeiro → grupos: criar grupo e convidar pelo identificador público. Empresa convidada aprova indicadores; conferir mês fechado e proposta de royalties antes de aprovar despesa.
5. Cadastro bancário: conectar provedor e preencher chave pública. Agenda: habilitar cartão antecipado e cobrança online. Usar contas/cartões de sandbox e confirmar webhook/consulta; nenhuma compra real é necessária para a homologação inicial.
6. Master → provedores Push/SMS: habilitar Push e contato VAPID. Profissional/gestor/cliente ativa no próprio dispositivo. Testar criação, cancelamento e mudanças de horário em dispositivo físico.
7. SMS: cadastrar conta/remetente válidos, aprovar quota da empresa; empresa ativa canal e cliente autoriza no portal. Somente após validar custos, país e status do provedor, testar envio controlado autorizado. As diretrizes oficiais Twilio para o Brasil distinguem números brasileiros P2P de remetentes globais habilitados para A2P; não presumir que qualquer número +55 pode enviar estes avisos.

## Verificações em execução

Testes locais integrados: 75 casos descobertos, 71 aprovados, 4 concorrências ignoradas no SQLite. Rodada adicional de 36 casos (incluindo recepção, integrações e permissões) aprovada. Todos os 20 testes Node aprovados. PostgreSQL completo, backup restore, auditorias de dependências/segredos e homologação visual serão registrados no PR e no relatório final.

## Limites explícitos

Nenhum SMS, cartão ou Push foi enviado/cobrado em produção nesta sessão. Testes de provedores usam respostas controladas e criptografia real. Não foram disponibilizados Coolify, credenciais de produção, impressora térmica ou dispositivos físicos. O código prepara as capacidades; ativação e homologação real dependem desses recursos.

A cobrança única de uma sequência inteira de serviços continua fora deste lote: cada serviço mantém o pagamento individual, conforme o PR26. Conta unificada entre empresas, compra/check-in de assinatura pelo cliente, certificação fiscal/DRE por contador e homologação de hardware não são declarados concluídos. A entrega não é uma declaração de superioridade integral sobre um concorrente.

## Fontes técnicas primárias

- https://www.mercadopago.com.br/developers/pt/docs/checkout-bricks/card-payment-brick/default-rendering
- https://www.mercadopago.com.br/developers/pt/docs/checkout-bricks/card-payment-brick/payment-submission
- https://github.com/web-push-libs/pywebpush
- https://developer.mozilla.org/en-US/docs/Web/API/Push_API
- https://www.twilio.com/docs/messaging/api/message-resource
- https://www.twilio.com/docs/messaging/guides/outbound-message-status-in-status-callbacks

- https://www.twilio.com/en-us/guidelines/br/sms
