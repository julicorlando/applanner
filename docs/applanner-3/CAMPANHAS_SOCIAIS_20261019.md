# Campanhas sociais no Comercial

## Comportamento

Acesse Comercial → Campanhas sociais ou o atalho no Master. O usuário cria um rascunho com nome, rede, objetivo, título da página e legenda. Cada campanha recebe um identificador permanente e links próprios de Instagram, Facebook e cadastro, com UTMs.

O upload aceita até 10 criativos por campanha: JPG/PNG/WebP até 10 MB (20 megapixels), convertidos para JPEG sem metadados, e MP4 até 40 MB, com validação de assinatura do contêiner. Codec, duração, proporção e elegibilidade de publicação são validados pela Meta quando o usuário publica. Os arquivos usam nomes aleatórios e armazenamento privado. Rotas autorizadas permitem prévia e download; a mídia pública só é servida enquanto a página está ativa.

A ativação disponibiliza uma página de captação. Não publica nas redes nem contrata anúncios. O operador baixa o criativo e copia a legenda/link para publicar no Meta Business Suite. Publicação direta, OAuth de contas sociais, formulário instantâneo da Meta, sincronização de anúncios, alcance e investimento não fazem parte desta entrega e não são apresentados como conectados.

O formulário público exige consentimento para o contato solicitado. O consentimento para medição na Meta é separado e opcional; usa a fila existente de eventos de aquisição, condicionada à configuração real. O formulário não dispara mensagens. Contatos repetidos na mesma campanha são identificados por hash de e-mail, com serialização da campanha no PostgreSQL e restrição única. Leads existentes não têm preferências, responsável ou bloqueio de contato sobrescritos. Dados de leads atribuídos a outro vendedor não aparecem na campanha de um vendedor sem acesso.

São medidos registros reais: sessões na página, formulários distintos recebidos e empresas cadastradas com a origem da campanha. Não são métricas oficiais de alcance/anúncios da Meta. A anonimização do lead remove o vínculo e o hash de identificação da campanha. Captação inclui CSRF, limite de tentativas por IP e campo antispam.

## Acesso

Master acessa todas as campanhas; Comercial ativo sem empresa acessa somente as próprias. Uma empresa, mesmo com perfil comercial vinculado, não acessa esta central de aquisição da plataforma. As rotas públicas não expõem campanhas em rascunho ou pausadas. Upload, edição e ativação requerem autorização no backend.

## Implantação e reversão

Migration `commercial.0004` cria somente três tabelas, sem alterar registros ou colunas existentes. Não há nova dependência. Antes do deploy, criar/verificar backup e aguardar CI. Em reversão de código, manter as tabelas novas e a mídia; não executar unapply de migrations com dados de campanhas existentes.

A chave `DJANGO_FIELD_ENCRYPTION_KEY` do servidor tem um problema separado, confirmado pelo diagnóstico do provedor de pagamento. Este módulo não troca essa chave nem depende dela para guardar campanhas. A correção operacional exige preservar/restaurar a chave válida dos dados existentes.

## Verificação

Testes cobrem permissões entre perfis/vendedores, upload inválido, direitos da mídia, limite de arquivos, acesso privado/público, rascunho/pausa, CSRF, formulário inválido, consentimentos separados, deduplicação, preferência de não contatar, retenção/anonimização e atribuição de cadastros. Revisão local Chromium: lista, campanha, formulário e página pública, temas claro/escuro, larguras 320/390/768/1440, axe WCAG A/AA. Dados e criativo usados nas capturas são de homologação local.
