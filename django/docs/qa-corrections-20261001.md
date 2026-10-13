# Correções e homologação complementar — 01/10/2026

## Alterações

- Comprovante público explica por que cancelamento/remarcação estão indisponíveis: situação da reserva, política da empresa, prazo mínimo ou atendimento iniciado. Exibe os contatos públicos da empresa.
- Arena explica indisponibilidade do cancelamento em reservas encerradas, iniciadas e com pagamento antecipado. A regra existente de tratar pagamentos com a empresa foi preservada.
- Pix explica falta de conexão, falta de e-mail ou situação incompatível; não oferece gerar cobrança que já será recusada por esses motivos.
- Remarcação pública com “qualquer profissional disponível” usa consulta bloqueada de profissionais elegíveis, evitando erro ao tentar bloquear uma lista em memória.
- Pesquisa de agendamentos inclui serviço/profissional e mantém cliente/telefone/e-mail, filtros, atualização automática e isolamento por empresa. Arena inclui quadra/modalidade.
- Configuração distingue passo dos horários de pausa entre atendimentos e explica a antecedência para cancelar ou reagendar.

## Catálogo Arena

O plano padrão `segment-arena` recebe `courts: 0` e `reservations: 0`: quadras ativas sem limite e reservas sem limite mensal. Isso explicita o funcionamento anterior, sem impor quotas arbitrárias a contratos existentes.

`seed_sales_plans` preenche chaves ausentes nesse plano padrão apenas na primeira atualização do catálogo. Uma marca de configuração impede que redeploys revertam escolhas posteriores do Master, inclusive limites deixados em branco. Preserva valores existentes, preços, assinaturas, módulos e demais ajustes. Outros planos não recebem limites automaticamente.

O Master pode editar limites no formulário de planos. Zero significa sem limite; vazio significa não definido. A comparação pública apresenta zero como **Sem limite**, nunca como 0 quadras/reservas.

Quotas positivas são validadas na criação/ativação de quadras e no serviço central de reservas, tanto públicas quanto internas e recorrentes. As reservas são contadas pela data do atendimento e mês civil no fuso da empresa; pendentes de pagamento, confirmadas e concluídas contam. Canceladas e faltas não contam. Reservas existentes e edição de quadras já ativas são preservadas.

O Master pode liberar limites específicos por empresa, inclusive zero para retirar a quota. A criação pelos portais e o serviço de reservas usam transação e bloqueio da empresa para serializar a verificação de capacidade.

Não há mudança de schema; os limites usam os campos JSON já existentes.

## Homologação automatizada

- `core.test_qa_followup`: motivos, políticas, acesso público sem login, busca por serviço/profissional, requisição de atualização automática, isolamento entre empresas, rótulos, seed idempotente e formulário do Master.
- `arena.test_catalog_limits`: página pública, reserva anônima, consulta pelo gestor, quota mensal, cancelamento/liberação da quota, limites de quadras, liberações do Master, meses e isolamento.
- `auto.test_anonymous_journey`: página pública, agendamento anônimo sem e-mail com veículo, consulta do gestor, cadastro da OS pelo portal, comanda, serviço/produto, pagamento local simulado, entrega, estoque, comissão e financeiro.
- Testes existentes continuam cobrindo preços, conflitos, Pix simulado, recorrência e permissões.

Esses são testes integrados de rotas/backend com clientes HTTP separados, sem cookies de autenticação no cliente público. Não equivalem à homologação de um navegador anônimo em produção, entrega de mensagens ou movimentação financeira real.

## Roteiro pendente após redeploy

1. Abrir janela anônima no navegador; verificar vitrine, cadastro obrigatório e página pública sem sessão administrativa. Não aceitar termos nem gerar cobrança real sem uma decisão do responsável.
2. Em Android/Chrome e iPhone/Safari físicos, testar largura, foco do teclado, rolagem, seleção dos horários, confirmação, copiar Pix e retorno do link WhatsApp. Registrar modelo, sistema, navegador e evidência. Emulação de largura não substitui aparelho físico.
3. Arena de homologação: cadastrar quadra, expediente e preço; reservar publicamente sem pré-pagamento, conferir gestor, testar conflito, cancelar e confirmar liberação do horário. Testar sinal apenas com credenciais de homologação e autorização do responsável.
4. Automotivo de homologação: cadastrar técnico/serviço, agendar veículo, abrir OS/comanda, adicionar produto, finalizar e conferir estoque/comissão/receita. Validar entrega real de WhatsApp/e-mail separadamente.
5. Buscar por serviço/profissional na agenda e aguardar atualização automática; verificar preservação de filtros.
6. Criar reserva dentro do prazo de cancelamento e conferir explicação; repetir fora do prazo e testar as ações.

Nenhuma validação em aparelho físico foi realizada neste ambiente. Não declarar homologação integral nem aprovação de integrações externas a partir da suíte automatizada.


## Complemento após a homologação de 01/10/2026

O formulário de profissionais mostra o uso e as vagas do plano antes do envio, incluindo liberações do Master. Perfis inativos não consomem vagas e profissionais ativos já existentes continuam editáveis.

As telas internas de agenda, edição, painel inicial e área do profissional identificam o nome informado na reserva e o nome do cadastro quando diferem. O cadastro e o telefone permanecem vinculados ao histórico, sem sobrescrita automática. A página pública continua mostrando apenas os dados informados pelo cliente.

O Master pode abrir **Planos → Excluir plano**. A remoção exige o nome exato do plano e é bloqueada quando existem assinaturas (inclusive canceladas), checkouts, propostas ou histórico de trocas. Os vínculos de módulos de um plano sem uso são removidos com ele; os módulos do catálogo são preservados. Planos usados podem ser desativados e ocultados por **Editar e desativar**.

O responsável informou nesta conversa que os testes em sessão anônima, celular real, Arena, Automotivo, Pix, cartão, e-mails e WhatsApp funcionaram, incluindo confirmação de recebimento. Essa validação foi relatada pelo usuário; modelos de aparelho, comprovantes e detalhes das transações não foram fornecidos e não são apresentados como testes executados pelo agente.
