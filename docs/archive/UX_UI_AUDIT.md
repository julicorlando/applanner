# Auditoria UX/UI

## Telas revisadas

Layout autenticado, autenticação, dashboard, agenda, clientes, serviços, campanhas, financeiro, integrações, onboarding, Master, página pública, segurança, privacidade e páginas de erro.

## Problemas encontrados e corrigidos

- Navbar horizontal sem escala → sidebar contextual, header e navegação móvel.
- Bootstrap sem identidade → tokens, superfícies, sombras, tipografia e estados próprios.
- Ausência de dark mode → temas claro, escuro e automático persistidos localmente.
- Dashboard sem prioridade → operação do dia, receita e inteligência de retorno em destaque.
- Página pública parecendo formulário → hero, cards de serviços/profissionais e reserva orientada.
- Agenda com status técnicos → rótulos naturais, cores consistentes e empty state.
- Clique duplo → estado de envio visual preservando idempotência do backend.
- Falta de atalhos → busca Ctrl+K e ação global “Novo”.
- Mobile espremido → sidebar móvel, bottom navigation e CTA público fixo.
- JavaScript inline incompatível com CSP → removido da tela 419.

## Componentes

Brand, sidebar, header, mobile navigation, metric card, status badge, empty state, command palette, service choice, professional card, booking card, toast region e loading button.

## Acessibilidade

Foco visível, labels, `aria-current`, regiões de navegação, `aria-live`, conteúdo visualmente oculto para ações, alvos de 42 px e redução de movimento. Auditoria automática Lighthouse permanece pendente por ausência do navegador integrado e de instalação local com banco.

## Pendências honestas

- Bootstrap continua em CDN; deve ser hospedado localmente antes de produção restrita.
- Busca Ctrl+K é navegação rápida, não pesquisa global no banco.
- Agenda diária/semanal em grade e drawer detalhado exigem endpoints adicionais.
- Upload de logo/recorte e QR Code ainda não possuem backend.
- QA visual real em 360/390/430 px depende de aplicação instalada e navegador disponível.
