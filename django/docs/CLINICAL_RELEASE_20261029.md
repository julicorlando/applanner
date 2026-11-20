# Evidências de pré-publicação clínica — 29/10/2026

Este registro substitui a lista de pendências da auditoria inicial de 28/10. Não certifica conformidade jurídica nem registra publicação em produção: o resultado final do deploy deve constar no PR e no histórico do Coolify.

## Implementação

- Odontologia: anamnese e evolução com campos específicos, CRO/UF e snapshot, arcadas SVG permanente/decídua FDI, faces, condições, notas, histórico e impressão; periodontograma de seis sítios; orçamento por dente, aprovação atestada e tratamento por sessões.
- Fisioterapia: avaliação, diagnóstico, anamnese, dor e achados por região, técnicas/exercícios/parâmetros, evolução, alta e comparação entre mapas históricos; integração com créditos dos pacotes existentes.
- Pacientes: cronologia, retificações ligadas ao original, acompanhamento, anexos privados cifrados, documentos e consentimentos enviados, exportação JSON/PDF auditada. PDFs assinados são preservados sem afirmar verificação criptográfica da assinatura.
- Segurança: profissional ativo da mesma clínica e autoria ou concessão clínica explícita; recepção e Master sem acesso clínico automático; proteção contra IDOR; auditoria; bloqueio de alteração/exclusão clínica no PostgreSQL. Identificação profissional inserida não equivale a consulta oficial ao conselho.
- Financeiro: adicional odontológico com quantidade, cotação congelada, proporcionalidade, revisão Master, aceite, Pix no faturamento existente, webhook/conciliação, atualização recorrente idempotente, isenção justificada, estorno integral e tratamento de estorno parcial pendente de revisão financeira. A edição dos profissionais legados permanece permitida.
- Compatibilidade: defaults no banco para novos campos obrigatórios permitem inserts da versão anterior. Registros sem snapshot só são lidos pelo autor imutável que ainda corresponde ao profissional atual, ou mediante concessão desse autor. Migrações são aditivas; rollback não deve apagar prontuários novos.

## Evidências realizadas antes da integração

- CI #949, commit 341c8c3: 958 testes Django/PostgreSQL/Redis, aprovados com três testes reservados ao ensaio específico ignorados; 32 testes JavaScript aprovados; três ensaios PostgreSQL de restauração/lock aprovados. Alterações posteriores exigem CI do HEAD.
- Testes locais posteriores: renovação de cobrança expirada usa outra chave por cotação e reutiliza a chave nas tentativas da mesma cotação; 14 testes de checkout aprovados. Autorização/compatibilidade clínica: 16 testes aprovados. Catálogo e dados fictícios: testes aprovados com a barreira real de assinatura habilitada e dois agendamentos HTTP criados.
- Coolify: homologação isolada no projeto ApPlannerV2, aplicação ojjbu89ci9h3nrwpsckmztxa. Primeiro build validado: 5030136, web Gunicorn, PostgreSQL 16 e Redis disponíveis em /healthz/ por HTTPS. Endereço: https://web-ojjbu89ci9h3nrwpsckmztxa.177.39.102.242.sslip.io/.
- Smoke executado no container: telas de paciente/registro e exportação PDF para as duas especialidades; recepção bloqueada, acesso cruzado bloqueado, IDOR bloqueado. Requisições com middleware real: profissionais 200 para painel/paciente; recepção 403. Isso não substitui inspeção visual autenticada do odontograma e do mapa corporal no navegador.
- Navegador: agendamento odontológico fictício confirmado para 29/10 às 14h e fisioterapêutico às 12h, nos respectivos profissionais e unidades. Nenhuma cobrança real ou mensagem externa foi enviada.
- O catálogo legado criava Prontuários desativado. O padrão de instalações novas foi corrigido; configurações existentes do Master continuam preservadas. O comando de homologação ativa apenas o catálogo do ambiente de testes e usa períodos de avaliação, sem fabricar pagamentos.

## Recuperação e destino

- Produção identificada: aplicação 8omu5fasbdtdycjfs8bmzvlw, branch django-replatform, /django/docker-compose.yml, https://applanner.com.br/.
- Último deploy de produção observado antes desta entrega: e26b7d771baca26f973a275c560210b1774a29d6, deployment tnlgwionwdvg4qcjgbrwtqob.
- Backup de produção #10, 2.078.860 bytes, checksum validado e restaurado integralmente em applanner_restore_verify_20261029; cópia com 186 migrations e duas clínicas. O cliente antigo gerava SET transaction_timeout incompatível com PostgreSQL 16; na recuperação dessa cópia foi removido somente esse comando do preâmbulo, antes dos dados. O Dockerfile agora utiliza pg_dump/pg_restore/psql 16.
- Backup de homologação #1, 1.434.390 bytes, restaurado pelo comando normal em applanner_homolog_restore_20261029: aprovado com as ferramentas corrigidas.
- Antes de novo deploy de produção: repetir backup se houver novas escritas relevantes; preservar volumes, chaves e credenciais; conferir branch/commit e CI. Em falha, retornar ao commit anterior sem reversão destrutiva de migrations. Se a restauração de dados for indispensável, usar cópia isolada validada e confirmar o corte, preservando as escritas posteriores ao backup.

## Limites da validação

O funcionamento real do Mercado Pago em sandbox exige credenciais e uma transação de teste do provedor; os testes automatizados exercitam respostas controladas. A inspeção visual autenticada de prontuários e a experiência em dispositivos móveis ainda precisam ser registradas. Não se declara certificação LGPD/CFO/COFFITO, assinatura ICP-Brasil ou backup externo recuperável por estas evidências.
