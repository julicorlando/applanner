# Melhorias após homologação de 30/09/2026

Branch: `django-replatform`. A branch `main` não faz parte desta entrega.

## Alterações

- Expedientes, intervalos e horários de quadras usam nomes dos dias da semana. Horas são exibidas sem a data fictícia de 1900.
- Valores monetários das listas operacionais e horários públicos de Arena usam a formatação brasileira.
- Descrição e títulos da página da empresa têm rótulos em português. Categorias conhecidas do diretório recebem nomes legíveis.
- Formulários de profissionais permitem atender todos os serviços ou escolher os serviços atendidos. Formulários de serviços permitem selecionar os profissionais responsáveis.
- Seleções são limitadas à própria empresa. A seleção de um serviço preserva os vínculos dos demais serviços. Um conjunto explicitamente vazio não libera todos os serviços.
- A página pública filtra profissionais conforme o serviço escolhido. O backend continua validando o vínculo e a disponibilidade.
- Campos e colunas de veículos são apresentados somente para o segmento automotivo.
- A página de planos compara mensalidade, período de teste, módulos ativos e recursos cadastrados pelo Master. Preços e assinaturas existentes são preservados.
- A confirmação pública mostra serviço, preço, data, horário e profissional, usando elementos DOM e texto em vez de inserir respostas em HTML. Erros de comunicação recebem feedback e o envio bloqueia cliques duplicados.
- A escolha de pagamento e a explicação de Pix aparecem quando existe uma opção online configurada. Se a empresa não oferece nenhuma forma disponível, o formulário explica a configuração pendente.
- O painel da empresa oferece **Configurar minha operação** em `/app/primeiros-passos/`. O roteiro lê os cadastros existentes, mostra progresso e links para equipe/serviços/horários ou quadras/preços/horários, página pública e publicação. Não reinicia o onboarding nem altera o cadastro ao ser aberto.

## Compatibilidade de dados

A migration `scheduling.0013_professional_services_restricted` acrescenta uma indicação de seleção explícita. Profissionais legados sem vínculos continuam atendendo todos os serviços; aqueles com vínculos continuam restritos aos vínculos existentes. As alterações não importam dados de produção nem alteram cobranças externas.

## Homologação após publicação

Fazer redeploy no Coolify e confirmar a aplicação da migration. Revisar os responsáveis pelos serviços, os horários e os recursos reais dos planos. Testar novamente cadastro, confirmação, reagendamento, cancelamento e atualização automática da agenda em cada segmento. Testar separadamente credenciais reais, Pix/cartão, envio de e-mail e WhatsApp; os testes automatizados não certificam a disponibilidade desses provedores em produção.

O progresso do roteiro indica configuração cadastrada, não certificação de funcionamento. A escolha comercial entre planos semelhantes depende dos recursos cadastrados pelo Master; esta entrega não inventa diferenças ou troca preços do catálogo.
