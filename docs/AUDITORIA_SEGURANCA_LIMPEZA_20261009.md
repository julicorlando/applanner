# Auditoria de segurança e limpeza — 09/10/2026

Base: `django-replatform`, commit `d3876a1`. Branch: `feat/security-cleanup-20261009`.

## Escopo e evidências

Inventário inicial: 1.820 arquivos versionados, 495 arquivos Python, 111 arquivos de testes, 146 arquivos Python em migrations e 138 templates. Foram inspecionados configuração, Docker, CI, integrações, autenticação, RBAC, API por tenant, geração de logs, consultas com locks e duplicações de funções. Uma consulta `objects.all()` não foi classificada isoladamente como falha: a API pessoal aplica tenant/perfil antes da leitura dos registros.

Gitleaks 8.30.0 foi executado com saída redigida sobre árvore e histórico local disponível. Também foi adicionada regra para credenciais PHP de baixa entropia, que o detector padrão não reconhecia. Nove alertas iniciais do detector padrão foram triados: uma chave legada e oito fixtures/nomes de campos/exemplos. A regra PHP identificou também a senha real do banco legado. Não se tentou validar essas credenciais nos provedores.

O histórico remoto de forks, clones privados e branches não presentes localmente não é coberto. Nenhum histórico foi reescrito. Dados de produção não foram acessados nem alterados. A homologação externa anterior foi informada pelo usuário; não foi reproduzida nesta rodada. Requisições de leitura aos dois domínios receberam HTTP 403 deste ambiente, impedindo validar a aplicação publicada e a infraestrutura Coolify.

## Achados e ações

Linhas referem-se à base auditada; arquivos desversionados continuam identificados neste relatório sem seus valores.

| Gravidade | Arquivo / linha | Risco | Correção / pendência |
|---|---|---|---|
| Crítica | `config/app.php:10` | Chave legada de criptografia disponível em código e histórico | Desversionada; exemplo usa `LEGACY_APP_KEY`. Recriptografar dados e backups, validar recuperação e rotacionar manualmente antes de encerrar a ocorrência |
| Alta | `config/database.php:7` | Senha real de MySQL disponível em código e histórico | Desversionada; exemplo usa `LEGACY_MYSQL_PASSWORD`. Revogar/rotacionar credencial, revisar acessos e clones |
| Alta | `django/requirements.txt:11` | Restrição de `cryptography` a versões com advisories conhecidos | Atualizada para `>=50.0.0,<51`; resolver e pip-audit passaram localmente; CI valida Fernet, AES-GCM legado e certificados/assinaturas XML |
| Alta | `django/engagement/portal.py:78` | Segunda função `_tenant` substituía a verificação de módulos contratados | Eliminada a sobrescrita, preservada a validação original e adicionados testes de bloqueio/escopo/seleção Master |
| Alta | `django/Dockerfile:16` | `COPY .` podia incluir `.env`, dumps, mídia, certificados e caches locais | `.dockerignore` no app e no gateway; arquivos runtime não participam do build |
| Alta | `django/billing/mercadopago.py:87`, `django/communications/whatsapp.py:36`, gateways QR | Erros do provedor podiam ecoar tokens no UI/diagnóstico | Redação de valores conhecidos, Authorization, userinfo e parâmetros sensíveis; validação de resposta não objeto |
| Média | `django/entrypoint.sh:12` | Access log padrão contém URLs, queries e tokens públicos de gestão | Log HTTP registra request-id, método, status e duração; monitoramento existente mantém nome da rota |
| Média | `django/master-whatsapp/server.js:28`, `tenant-server.js:13` | Serialização de exceções podia expor headers/chaves da sessão | Serializadores conservadores de erros e redação de campos sensíveis; teste Node verifica saída real do Pino |
| Média | `django/operations/services.py:49`, `tasks.py:28`, `backup.py:73` | Diagnósticos persistidos podiam carregar credenciais | Redação antes de persistir erros de banco, cache e backup |
| Média | `django/master-whatsapp/Dockerfile:5` | Instalação sem lock permitia variação transitiva do gateway | `package-lock.json` + `npm ci`; auditoria npm e teste de log na CI |
| Média | `.github/workflows/django-ci.yml:1` | CI não auditava segredos/dependências/lint | Novo workflow bloqueante em falhas, políticas de artefatos, Gitleaks completo da árvore + commits novos, pip-audit, npm audit, lint e formatação do tooling |
| Média | Política GitHub da branch | Branch auditada não tem proteção de branch configurada | Administrador deve exigir checks `test` e `security`; não foi alterada a administração do repositório |
| Baixa | 63 imports em arquivos Django | Imports não utilizados dificultam manutenção | Remoção por análise estática; exports intencionais das rotas Master foram preservados |
| Baixa | 192 artefatos versionados | Código misturado com logs, estado, snapshots e backups | Desversionados, com cópias locais mantidas e manifesto individual; aproximadamente 371,6 MB deixam a árvore atual, sem redução do histórico |

Fontes para a atualização de criptografia: advisory oficial `https://github.com/pyca/cryptography/security/advisories/GHSA-537c-gmf6-5ccf` e changelog `https://cryptography.io/en/50.0.0/changelog/`. A versão 50 também contém correções de PKCS7; não significa que todas as aplicações afetadas usam esse recurso.

## Preservação funcional e limpeza

Nenhum módulo foi removido. Nenhuma migration, fixture necessária, ferramenta de importação PHP, script de rollback ou documentação operacional foi removido. Médico/Clínica não foi ativado. Preços e planos não foram alterados: a checagem restaurada apenas aplica o contrato existente.

O manifesto `LIMPEZA_20261009.json` identifica os 192 caminhos e motivos. A operação foi `git rm --cached`, conservando os arquivos no checkout isolado. Os arquivos também permanecem no checkout original e no histórico. **Isso não transforma esses backups em armazenamento seguro e durável.** Antes de atualizar um checkout antigo ou sanear o histórico, copiar os backups/configurações necessários para armazenamento privado, verificar hashes e validar restauração.

Templates potencialmente referenciados dinamicamente, payloads `patches/`, scripts de importação e código PHP ativo foram mantidos. Não se usou ausência de referência textual como prova suficiente para excluir funções. Relatórios existentes da auditoria de 08/10 foram mantidos como evidência histórica, não como certificado desta rodada.

## Verificações

- Python local: 3.12; CI: 3.13 (runtime suportado pelo Docker).
- `manage.py check --deploy`: passou com configuração segura temporária.
- `makemigrations --check --dry-run`: sem mudanças.
- Lint `F401,F821,F822,F823`: passou após limpeza; exports Master intencionais mantidos.
- Node público: 20 testes passaram.
- Novos testes: mensagens/redação dos provedores, gateway malformado, módulos contratados e tenant; resultado final na CI do PR.
- Teste Pino: passou localmente, verificando ausência de credencial em log serializado.
- `pip check`: passou. `pip-audit`: zero vulnerabilidades conhecidas na resolução local após atualização. `npm audit`: zero vulnerabilidades conhecidas no lock gerado.
- Gitleaks do histórico: dois segredos reais legados exigem ação manual; fixtures de teste têm allowlists de valor e caminho exatos. Não existe exclusão genérica de testes.
- CI integral: deve passar antes de qualquer merge; inclui PostgreSQL/Redis, migrations, seeds, Docker gateway, agendamento/financeiro/permissões e restore em banco descartável.

Não executados nesta rodada: login e jornada autenticada no site publicado; Android/iPhone físicos; pagamentos reais, SMTP, WhatsApp real, dump real de importação PHP, testes de carga com perfil de produção e restauração off-site do backup da produção. Os testes automatizados usam mocks ou bancos descartáveis conforme o caso. Não foi executado `migrate` em produção.

## Implantação e rollback

Esta entrega abre PR para `django-replatform`; não publica nem faz merge automático. Depois de revisão, CI aprovada e autorização para publicação:

1. Conferir variáveis no Coolify, sem imprimir seu conteúdo. Manter `DJANGO_FIELD_ENCRYPTION_KEY`; esta entrega não rotaciona essa chave.
2. Criar backup do banco, mídia e volumes de sessão do WhatsApp; verificar integridade e restauração em destino separado. Arquivos privados não devem ficar no repositório.
3. Preservar fora do checkout os artefatos legados de recuperação antes de atualizar uma instalação antiga. Clone PHP limpo requer criar `config/app.php` e `config/database.php` a partir dos exemplos e configurar variáveis legadas.
4. Registrar commit anterior e novo commit aprovados. Fazer redeploy pelo Coolify após autorização. Não há migrations novas nesta entrega; o bootstrap existente serializa migrations/seeds/static antes de HTTP, e worker/beat aguardam web saudável.
5. Conferir `/healthz/`, logs sem credenciais, containers web/db/redis/worker/beat, QR/sessões e armazenamento de mídia. Validar login Master, `/admin` anônimo=404, módulos contratados, agendar/remarcar/cancelar, pagamentos e fila de mensagens.
6. Se falhar, restaurar a imagem/commit anterior e redeploy sem reverter esquema: não há alteração estrutural nova. Credenciais revogadas não podem ser recuperadas via rollback de código. Nunca substituir o banco em operação sem plano separado e autorização.

Downtime, rotação e saneamento de histórico são ações separadas, ainda não autorizadas nem executadas aqui.

## Avaliação provisória

| Critério | Nota | Base / limite |
|---|---:|---|
| Segurança | 8,0 | Controles de código aprimorados; exposição histórica depende de rotação manual |
| Arquitetura | 9,0 | Multiempresa, serviços, RBAC, filas e init serializado; legado preservado |
| Performance | 8,0 | Sem benchmark reproduzido nesta rodada; usuário informou carga aprovada |
| Código e manutenção | 9,0 | Limpeza conservadora, lock Node, lint e prevenção de sobrescrita |
| Funcionalidades | 9,3 | Suíte de regressão abrangente e correção da contratação de módulos |
| UX/UI | 9,0 | Melhorias públicas/PWA anteriores; sem validação física de dispositivos nesta rodada |
| Integrações | 9,0 | Homologação real informada pelo usuário; mocks/regressão no código |
| Testes e CI | 9,5 | Suíte PostgreSQL/Redis + segurança/dependências/restore; confirmar resultado do PR |
| Produção | 8,0 | Acesso publicado bloqueado nesta rodada e rotação/deploy pendentes |
| **Nota geral (média)** | **8,9** | **Provisória, baseada em evidências desta auditoria** |

A avaliação anterior de 9,5 era condicionada à homologação informada pelo usuário. Esta rodada encontrou uma pendência adicional concreta: segredos legados no histórico. A nota não deve subir para 10 até sua remediação e comprovação de operação monitorada. Não é necessário criar mais módulos para fechar essa lacuna.
