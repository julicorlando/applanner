# SAST Report

Busca recursiva executada em todos os PHP por `eval`, `unserialize`, execução de shell, includes dinâmicos e superglobais.

- Nenhum `eval`, `unserialize`, `shell_exec`, `system`, `passthru`, `proc_open` ou `popen` encontrado.
- Entradas POST relevantes possuem whitelist, cast ou validação antes da persistência.
- SQL usa PDO prepared statements; identificadores dinâmicos do backup vêm exclusivamente de `SHOW TABLES` e passam por whitelist alfanumérica.
- Segredos persistidos usam `Encryption`; jobs apagam payload cifrado após sucesso.
- Pendência: análise dinâmica com MySQL e servidor Apache real.
# SAST incremental — 07/08/2026

- Scan de fontes/sinks externos: concluído por `rg` em todos os PHP.
- `eval`, `unserialize`, `phpinfo` e execução de comandos em runtime web: nenhum achado. Os usos de `exec/passthru` limitam-se ao runner CLI de testes.
- Credenciais literais: nenhum achado fora dos templates de configuração.
- PDO: `ATTR_EMULATE_PREPARES=false` confirmado.
- Achado corrigido: falta de filtro de profissional na agenda.
- Limitação: DAST e banco real não executados por ausência de instalação local válida.
