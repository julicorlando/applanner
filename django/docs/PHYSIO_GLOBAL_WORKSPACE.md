# Fisioterapia — layout global da área interna

Empresas da categoria `fisioterapia` ou com o módulo `physiotherapy` utilizam o tema escuro e o mesmo menu em toda a área interna: Dashboard, Agenda, Pacientes, Atendimentos, Fisioterapia, Financeiro, Relatórios e Configurações. A regra aplica-se também aos cadastros existentes, sem migrações ou recadastro.

A navegação é resolvida por requisição e perfil. A recepção recebe o tema e funções administrativas sem acesso aos prontuários. O profissional recebe somente destinos compatíveis com sua área, e o Dashboard limita agendamentos e pacientes ao seu vínculo. Financeiro, relatórios e configurações mantêm as verificações do servidor. Bloqueio de assinatura deixa disponíveis somente pagamento e segurança da conta.

Configurações concentra equipe, serviços, unidades, jornadas, pacotes, ferramentas contratadas, assinatura, integrações, suporte, privacidade e saída da conta conforme autorização. Recursos não são apagados. O Dashboard de Fisioterapia substitui a tela genérica de catálogo; modo simples não reintroduz navegação de barbearia.

A mudança é restrita à empresa autenticada: Master, demais segmentos, páginas públicas de agendamento e visitantes anônimos mantêm o comportamento original. A aparência é aplicada em agenda, cadastros, atendimentos, financeiro, relatórios, prontuários, páginas da conta e assinatura. Impressão e arquivos clínicos continuam usando seus fluxos próprios.

Componentes: `healthcare/navigation.py`, parciais compartilhadas `physio_sidebar.html` e `physio_topbar.html`, e CSS `healthcare/physio-workspace.css`. O menu antigo não é duplicado no HTML das páginas internas de Fisioterapia. A política da área profissional permite somente GET/HEAD dos novos destinos administrativos próprios; não libera escrita em outras áreas.

Verificações locais: 109 testes Django de clínica/portais/modo simples/permissões, com cinco verificações específicas de PostgreSQL não executadas no SQLite; seis testes de cadastro clínico/Fisioterapia aprovados; 42 testes JavaScript aprovados. Os testes cobrem navegação nas páginas operacionais, seleção de item ativo, cadastros antigos, cadastro por módulo, recepção, Master, outros segmentos, modo simples, bloqueio de cobrança, isolamento do Dashboard profissional e estilos calculados. `check`, ausência de migrations, `collectstatic` e Ruff aprovados. O CI existente valida novamente no PostgreSQL e Redis, com restauração em banco isolado.

A igualdade visual exata e a responsividade em navegador real exigem homologação visual. O tema global não transforma testes de DOM ou CSS em prova de equivalência pixel a pixel à imagem.
