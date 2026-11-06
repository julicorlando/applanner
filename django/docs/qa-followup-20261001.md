# Correções da homologação de 01/10/2026

## Agenda e experiência

- Painel: próximos atendimentos exibem apenas pendentes/confirmados futuros, incluindo próximos dias. Cancelados e concluídos ficam fora dessa seção.
- Agenda e reservas: filtros separados para próximos, cancelados e histórico. Datas futuras mostram dia/mês junto ao horário.
- Comparação de planos: Arena usa quadras e reservas por mês; profissionais não se aplicam. Não são inventados limites: valores ainda não cadastrados aparecem como Consultar. Este ajuste não cria nem passa a cobrar limites inexistentes de quadras/reservas.
- Cadastro comercial sem instruções de contas de teste. Singular/plural das funções corrigido na operação e no Master.
- Confirmação pública destaca serviço/quadra, data, horário, profissional quando aplicável, valor e ação para gerenciar o agendamento. Layout fluido para telas menores.

## Identidade do cliente e inteligência de retorno

- Nome e telefone brasileiro com DDD obrigatórios; e-mail opcional. Pagamento antecipado continua exigindo e-mail quando o provedor o requer.
- Telefones com DDD, com 55 e com formatação são comparados como o mesmo número. Novos clientes são gravados com 55.
- Matching por telefone e/ou e-mail, sempre restrito à empresa. E-mail sem distinção de maiúsculas/minúsculas.
- Um contato existente mantém o mesmo Customer e, assim, histórico, pacotes, fidelidade e inteligência de retorno. Nenhum dado pessoal existente é sobrescrito por uma reserva anônima.
- Nome informado em cada reserva de serviços permanece no snapshot para auditoria. Nome operacional em painel, agenda, área profissional e edição interna vem do cadastro do cliente. Alterações feitas pelo gestor se refletem nessas telas.
- Telefone e e-mail que apontem para pessoas diferentes, ou duplicatas do legado, exigem revisão pela empresa; não há fusão automática ou exclusão de dados.
- Cadastros novos pela gestão exigem telefone e impedem duplicatas. ETL não chama full_clean: dados históricos incompletos permanecem preservados.
- Reservas públicas da Arena passam a vincular Customer, também preservando o histórico do cliente.
- Comprovante público mostra apenas o nome informado na própria reserva, para não revelar o nome de cadastros existentes a quem conhece um telefone.
- Mensagem pública explica preservação de cadastro; não há endpoint público para descobrir nomes ou dados pessoais pelo telefone.

## Homologação

Cobertura automatizada de identidade, conflitos, isolação entre empresas, agendamento anônimo sem e-mail, telefone obrigatório, vínculo de veículo no Automotivo, reserva da Arena, filtros e catálogo. Verificar check e ausência de migrations pendentes; CI usa PostgreSQL.

Após redeploy: repetir a jornada anônima em produção, Arena e Automotivo no navegador, e validar em Android/iOS físicos. Testes de backend não equivalem a homologação em celular real. Pagamentos reais e entregas de e-mail/WhatsApp não foram executados nesta correção.
