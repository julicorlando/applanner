# Avaliação fisioterapêutica — preparação da publicação

Destino de integração: `django-replatform`. A `main` não participa desta entrega.

Acesso: `/app/clinica/fisioterapia/`; nova avaliação: `/app/clinica/fisioterapia/avaliacao/nova/`.
Disponibilidade: categoria `fisioterapia` ou módulo `physiotherapy`, mais permissão clínica e módulo de prontuário existentes. Recepção, Master e responsáveis administrativos sem vínculo clínico não recebem acesso.

Inclui formulário escuro responsivo, dados vinculados ao paciente/profissional/atendimento, campos clínicos estruturados, mapa anterior/posterior com lateralidade do paciente, documentos privados, desenho opcional da assinatura e confirmação autenticada de autoria. O desenho não constitui certificado ICP-Brasil.

Rascunhos têm controle de versão otimista, revisões cifradas e trilha administrativa. Finalização transacional produz um registro clínico imutável, identidade profissional com CREFITO, data e hash do conteúdo. Uma chave única protege o reenvio da finalização. Evoluções futuras podem se vincular à avaliação inicial. Compartilhamento clínico explícito concede somente leitura de registros finalizados; não compartilha rascunhos.

Migrações aditivas:
- `healthcare.0010_clinicalregistration_professional_name_and_more`: avaliações, versões, documentos, identificação da pessoa responsável e vínculo de evoluções.
- `healthcare.0011_assessment_ledger_guards`: gatilhos PostgreSQL para preservar registros finalizados e versões; impedem reatribuição de vínculos.

Validação local: `manage.py check`, `makemigrations --check --dry-run`, migrações em banco SQLite descartável, `collectstatic`, 73 testes clínicos (68 aprovados e 5 específicos de PostgreSQL não executados localmente), 36 testes JavaScript aprovados e Ruff F401/F821/F822/F823. O CI existente executa PostgreSQL, Redis, testes completos e verificações de segurança.

A publicação depende do resultado do CI, da identificação do destino Coolify e da validação de backup/rollback no ambiente escolhido. Não remover as novas tabelas para reverter a versão da aplicação; preservar o histórico cifrado e a chave de criptografia. As migrações adicionam campos compatíveis com a versão anterior.

Pendente nesta entrega: validação visual em navegador real e homologação no Coolify. A verificação anterior do Coolify foi interrompida por bloqueio automático do navegador por limite de uso. Não há declaração de conformidade legal nem validação criptográfica de certificados digitais.
