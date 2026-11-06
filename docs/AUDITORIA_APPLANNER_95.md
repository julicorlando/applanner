# Auditoria ApPlanner — 08/10/2026

## Escopo e evidência
Revisão da branch `django-replatform` e das branches remotas; correções foram preparadas em `feat/applanner-quality-95`. A avaliação combina inspeção de código, testes Django/Node, CI PostgreSQL 16 + Redis 7 e verificação pública da página de agendamento. Não houve alteração em produção, pagamento real, WhatsApp real, SMTP real, restauração de backup de produção ou teste físico em dispositivo.

## Classificação

| Área | Estado | Evidência |
|---|---|---|
| Página pública, serviço, unidade e data | Implementado e testado | página pública verificada; nomes, unidade e data no fuso aparecem; testes de regressão |
| Concorrência de agenda/estoque/cupom | Implementado e testado no CI | locks, idempotência e conflitos cobertos em PostgreSQL |
| Multiempresa e unidades | Implementado e testado | querysets escopados, seleção por unidade e testes negativos |
| Master e `/admin/` | Implementado e testado | visitante recebe 404; sessão Master válida acessa; CI verde |
| Financeiro e webhooks | Implementado e testado em código/testes | validação transacional e idempotência; provedor externo ainda requer sandbox |
| PWA | Implementado e testado | manifest, ícones, instalação iOS/Android, Service Worker restrito a assets |
| WhatsApp, SMTP e cobrança externa | Parcialmente verificável | código e testes com mocks; falta teste com credenciais/provedor real |
| Escala e restauração operacional | Parcialmente verificável | smoke de restore descartável no CI; falta restore off-site e teste de carga |
