# Ajustes de UX para lançamento — 19/10/2026

Base: django-replatform f969969. Branch: feat/launch-ux-20261019.

## Mudanças

- Master: cabeçalho com busca e menu de conta/ferramentas; quatro atalhos operacionais; indicadores em grade regular; preparação e catálogo em categorias recolhíveis nativas. Busca abre apenas os grupos com resultados, limpa/restaura os grupos e respeita links de categoria. Configuração bancária, NFS-e, saúde das empresas e demais rotas continuam acessíveis.
- Cadastro: três etapas (negócio, conta, condições), retorno sem perder dados, validação de campos antes de avançar e navegação para a etapa com erro retornado pelo servidor. Sem JavaScript, todos os campos e o envio permanecem disponíveis. O formulário Django e os parâmetros de preço, proposta, ciclo e pagamento continuam canônicos. A explicação de cobrança usa as condições reais do plano; não há cobrança neste formulário.
- Explorar: título menor, busca e segmento em destaque, localização por botão e filtros adicionais em disclosure nativo. Filtros ativos permanecem expandidos. Preserva geolocalização mediante permissão, raio máximo atual de 30 km, parâmetros da busca e dados por unidade. Resultados mostram a quantidade de unidades da busca.
- Empresa/mobile: o menu móvel agora inclui os mesmos grupos autorizados da sidebar, inclusive em tablets. Planos, perfis e permissões continuam filtrados pelo backend. Corrigidos contrastes dos diagnósticos e dos rótulos de módulos em claro/escuro.

## Verificação

- Rodadas locais de 26 e 58 testes Django direcionados aprovadas (há sobreposição entre rodadas).
- 20 testes Node aprovados; lint exigido aprovado; Django check sem problemas; makemigrations sem alterações.
- Revisão de navegador com empresa fictícia local, profissional, Master, cadastro e Explorar. Larguras: 320, 390, 768, 1024, 1440 px. Temas claro e escuro, navegação por teclado, busca por função, volta entre etapas, campos obrigatórios, menu móvel e cadastro sem JavaScript.
- Resultado final de CI e homologação visual registrado no PR; estados intermediários não representam publicação.

## Publicação e limites

Sem nova dependência, migration ou alteração de configuração financeira. Coletar estáticos pelo bootstrap existente. Não usar os dados fictícios locais no banco de produção.

Emulação de largura não certifica instalação/Push em Android ou Safari/iPhone físicos. No novo servidor ainda é necessário concluir e validar migração dos dados, backup e configuração das integrações antes de abrir a operação. Este lote não modifica banco, conexões ou cobrança de produção.
