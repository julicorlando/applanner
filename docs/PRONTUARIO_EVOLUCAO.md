# Prontuário odontológico: plano de tratamento, evolução clínica e retificação

Referências: LGPD (Lei 13.709/2018) e Lei 13.787/2018 (prontuário eletrônico). O objetivo é lançar rápido no
consultório sem perder a integridade jurídica: o que foi finalizado não se apaga nem se sobrescreve; corrige-se
com retificação rastreável.

## 1. Tabelas

Os nomes pedidos na especificação mapeiam para as tabelas Django abaixo (código em
`django/healthcare/evolution_models.py`). O texto clínico é sempre criptografado (Fernet, `*_encrypted`).

### `planos_tratamento` → `healthcare_dentalplanitem`

| Campo | Tipo | Observação |
|---|---|---|
| id | bigint PK | |
| tenant_id, customer_id | FK | clínica e paciente; imutáveis |
| professional_id | FK nulo | dentista responsável |
| tooth | varchar(20) | dente (FDI) |
| procedure_encrypted | text | procedimento |
| price | numeric(10,2) | valor |
| position | smallint | ordem na tabela |
| status | `planned` / `quoted` / `executed` | PLANEJADO / EM_ORCAMENTO / EXECUTADO |
| created_by_id, created_at, updated_at | | |
| executed_at, executed_by_id | | preenchidos só quando executado (CHECK) |

### `evolucoes_clinicas` → `healthcare_dentalevolution`

| Campo | Tipo | Observação |
|---|---|---|
| id | bigint PK | |
| tenant_id, customer_id, created_by_id, created_at | | imutáveis |
| professional_id | FK nulo | dentista responsável |
| plan_item_id | FK nulo | item do plano que originou o lançamento |
| previous_id | FK nulo | **referencia_registro_anterior_id** (o registro que este corrige) |
| tooth, clinical_date | | |
| procedure_encrypted, orthodontic_encrypted, notes_encrypted | text | conteúdo clínico |
| status | `draft` / `finalized` / `rectified` | RASCUNHO / FINALIZADO / RETIFICADO |
| author_name | varchar | nome de quem lançou, congelado |
| finalized_at, finalized_by_id, finalized_automatically | | |
| content_sha256 | char(64) | hash do conteúdo canônico na finalização |
| rectified_at | timestamptz | **data_retificacao** |
| rectified_by_id | FK usuário | **retificado_por_id** |
| rectification_reason_encrypted | text | **motivo_retificacao** |

CHECK `dental_evolution_lifecycle`: rascunho não tem finalização/retificação; finalizado tem `finalized_at` e
hash; retificado tem também data, autor e motivo.

`healthcare_patientnoterectification` retifica as evoluções antigas (`PatientNote`, anteriores a este fluxo), que
continuam intactas: liga a nota original ao registro novo, com motivo, autor e data.

### `audit_logs` → `core_auditlog` (já existente)

Reaproveitado de propósito em vez de criar outra tabela: já tem `user_id`, `created_at`, `ip_address`,
`user_agent`, `before`/`after` em JSON e **cadeia de hash** (`previous_hash`/`entry_hash`, verificável com
`verify_audit_chain`). O estado gravado leva metadados e `content_sha256`, nunca o texto clínico, para não
expor em claro o que é criptografado no prontuário.

Ações gravadas: `clinical.dental.evolution.created`, `.draft_updated`, `.draft_deleted`, `.finalized`,
`.auto_finalized`, `.rectified`, `clinical.dental.patient_note.rectified`, `clinical.dental.plan_item.created`,
`.updated`, `.deleted`, `.executed`, `.reopened`, `clinical.dental.patient_record.viewed` e `.audit_viewed`.

## 2. Regras e transições (`django/healthcare/evolution_services.py`)

```
Plano:     PLANEJADO <-> EM_ORCAMENTO --Executar--> EXECUTADO (cria evolução RASCUNHO)
           EXECUTADO --> PLANEJADO só se o rascunho gerado for excluído
Evolução:  RASCUNHO --"Salvar e finalizar atendimento" ou N horas--> FINALIZADO
           FINALIZADO --"Retificar lançamento" (motivo obrigatório)--> RETIFICADO + novo registro FINALIZADO
```

- Plano em PLANEJADO/EM_ORCAMENTO: edita e apaga livremente; não aparece no histórico clínico.
- Rascunho: só o autor edita ou exclui. Não aparece no histórico; fica no quadro "Evolução clínica".
- Finalização automática: `DENTAL_EVOLUTION_DRAFT_HOURS` (padrão 12). Roda a cada 15 min no Celery beat
  (`healthcare.tasks.finalize_expired_dental_evolutions`) e também ao abrir o prontuário do paciente.
- Retificação: autor do lançamento ou gestão (owner, tenant-admin, manager). Em uma transação: marca o original
  RETIFICADO (intacto) e cria o registro corrigido, já finalizado, ligado por `previous_id`.

As regras valem em três camadas:

1. **Serviço**: valida a transição e a autoria e grava a auditoria.
2. **Modelo**: `save()`/`delete()` recusam mudança em finalizado/retificado; `QuerySet.update/delete` em
   massa é bloqueado.
3. **Banco (PostgreSQL)**: triggers da migration `0025_dental_evolution_guards` recusam `DELETE` fora de
   rascunho, qualquer `UPDATE` em retificado e, em finalizado, tudo que não seja a passagem para retificado.

## 3. Tela (prontuário do paciente)

- **Evolução clínica**: lançamento rápido (dente, data, dentista, procedimento, observação, ortodôntico).
  "Adicionar ao atendimento" cria rascunho; "Salvar e finalizar atendimento" fecha tudo. Rascunhos aparecem
  com selo e com Editar/Excluir.
- **Plano de tratamento**: tabela com situação (Planejado/Em orçamento), botão Executar e ×. Os executados
  ficam listados à parte, só para leitura.
- **Emitir documento**: receituário, atestado, declaração, laudo, encaminhamento, solicitação de exames e
  orçamento. Abre o editor já com os dados do paciente. A recepção pode emitir em nome do dentista escolhido
  (identificação e assinatura cadastradas dele), se o gestor liberar ("documentos" nas permissões da recepção).
  O registro e o log guardam quem emitiu.
- **Histórico**: só os registros finalizados. "Retificar lançamento" abre um modal com motivo (atalhos:
  erro de digitação, dente incorreto…) e os campos já preenchidos. O controle "Exibir registros retificados
  (Auditoria)" mostra os originais riscados, com motivo, autor e data; essa consulta também fica no log.
