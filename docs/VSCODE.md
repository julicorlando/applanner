# ApPlanner no VS Code

Guia para editar o código e consultar o banco de produção pelo VS Code, com publicação pelo Coolify.

## 1. Código

1. Abra a pasta `applanner` no VS Code (Arquivo → Abrir pasta).
2. Aceite **Instalar extensões recomendadas** (Python, Django, Ruff, PostgreSQL, Remote SSH, GitHub, Docker).
3. Atualize o código: `Terminal → Executar tarefa → ApPlanner: atualizar código (git pull)`.
   A branch de produção é **django-replatform**; o sistema Django fica em `django/`.
4. Para alterar: crie uma branch, faça commit e push e abra um pull request no GitHub
   (extensão GitHub Pull Requests). Os testes rodam sozinhos no GitHub Actions.
5. Depois do merge na `django-replatform`, o Coolify publica:
   - **automático**, se o webhook do GitHub estiver configurado (seção 4);
   - ou pelo botão **Redeploy** no Coolify.

Nunca altere arquivos direto no servidor: o próximo deploy apaga a mudança.

## 2. Banco de produção pelo túnel SSH

O Postgres fica acessível só no próprio servidor (`127.0.0.1:55432`), nunca na internet.
O VS Code chega nele por um túnel SSH.

### Uma vez só: chave SSH

No terminal do VS Code (PowerShell):

```powershell
ssh-keygen -t ed25519 -C "applanner-vscode"
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

Copie a linha mostrada e adicione no servidor (no Coolify: **Servers → server001 → Private Keys/SSH**
ou no arquivo `~/.ssh/authorized_keys` do usuário do servidor). Se o servidor usa senha, o túnel pede a senha.

### Toda vez que for usar o banco

1. `Executar tarefa → ApPlanner: abrir túnel do banco de produção` (usuário `root` e servidor
   `coolify.axionwebdigital.com.br` já vêm preenchidos; troque se o seu for outro). Deixe o terminal aberto.
2. Na barra lateral, abra a extensão **PostgreSQL** e escolha a conexão:
   - **ApPlanner produção · somente leitura** — para o dia a dia;
   - **ApPlanner produção · administrador (cuidado)** — só para emergência.
3. Digite a senha quando pedir. A senha não fica salva no projeto.

### Uma vez só: criar o usuário somente leitura

No Coolify: aplicação ApPlannerV2 → **Terminal** → container **db**. Rode, trocando a senha:

```sh
psql -U applanner -d applanner -v ON_ERROR_STOP=1 -v senha="'TROQUE-POR-UMA-SENHA-FORTE'" <<'SQL'
CREATE ROLE applanner_leitura LOGIN PASSWORD :senha;
ALTER ROLE applanner_leitura SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE applanner TO applanner_leitura;
GRANT USAGE ON SCHEMA public TO applanner_leitura;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO applanner_leitura;
ALTER DEFAULT PRIVILEGES FOR ROLE applanner IN SCHEMA public GRANT SELECT ON TABLES TO applanner_leitura;
SQL
```

A senha do usuário administrador `applanner` está nas variáveis de ambiente da aplicação no Coolify
(`APPLANNER_POSTGRES_PASSWORD`).

## 3. Cuidados com o banco

- **Backup antes de alterar qualquer coisa à mão.**
- Prontuários, evoluções, CPF e outros dados sensíveis são **criptografados pelo sistema**: no banco aparecem
  cifrados e não dá para ler nem editar direto. Use o sistema ou `python manage.py shell` no terminal do
  container **web** do Coolify.
- Tabelas de prontuário, auditoria e documentos emitidos têm travas que bloqueiam UPDATE/DELETE de propósito.
- Mudança de estrutura (tabela/coluna) só por *migration* do Django no código.
- Alterações feitas direto no banco **não entram na auditoria** do sistema.
- LGPD: esse acesso enxerga dados de pacientes de todas as empresas. Não compartilhe.

## 4. Publicação automática a cada push (opcional)

No Coolify, em **Advanced → Auto deploy**, está "Deploy on push (webhooks)". Para funcionar:

1. Coolify → aplicação → **Webhooks**: copie a URL do webhook do GitHub e defina um *secret*.
2. GitHub → repositório → **Settings → Webhooks → Add webhook**: cole a URL, tipo `application/json`,
   o mesmo *secret*, evento **Just the push event**.

Depois disso, todo push na `django-replatform` publica sozinho.

## 5. Tarefas prontas (Terminal → Executar tarefa)

| Tarefa | O que faz |
| --- | --- |
| ApPlanner: atualizar código (git pull) | Baixa as últimas mudanças |
| ApPlanner: abrir túnel do banco de produção | Liga `localhost:5433` ao banco do servidor |
| ApPlanner: terminal no servidor (SSH) | Abre um terminal no servidor |
| ApPlanner: subir ambiente local (Docker) | Sobe o sistema no seu PC em `http://localhost:8000` |
| ApPlanner: rodar testes (Docker local) | Roda os testes do Django |
| ApPlanner: verificar código (ruff) | Procura erros simples no Python |
