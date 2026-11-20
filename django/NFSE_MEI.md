# NFS-e MEI das mensalidades do ApPlanner

Integração direta com SEFIN Nacional. A funcionalidade atende às mensalidades cobradas pela plataforma, usando seu único CNPJ emissor. Não emite notas dos serviços prestados pelos estabelecimentos nem notas fiscais de mercadorias.

## Ativação

1. Faça redeploy da branch `django-replatform`. O fluxo de inicialização aplica as migrações e sincroniza o agendamento Celery.
2. Master → NFS-e MEI → Configuração fiscal: informe CNPJ numérico do MEI, razão social, código IBGE, código nacional de serviço, série exclusiva da aplicação e certificado A1 (.pfx/.p12) com senha.
3. Confirme com a contabilidade a possibilidade de enquadramento MEI da atividade efetivamente faturada, código do serviço e competência. Não selecione MEI para uma atividade incompatível. Este adaptador define a data de competência como a data local do pagamento; os planos comerciais (mensal/trimestral/anual) não dividem a nota em parcelas mensais.
4. Habilite o CNPJ no emissor nacional e configure inicialmente homologação. A1 sem validade, outro CNPJ ou senha incorreta é recusado. A ICP-Brasil e autorização fiscal são verificadas pelo serviço governamental.
5. A empresa deve preencher Pagamentos → Dados fiscais (CPF/CNPJ, nome, e-mail, endereço e código IBGE).
6. Faça uma emissão real de homologação com seus dados, consulte a chave, confira valores, competência e destinatário. Só depois selecione Produção e confirme a ativação.

Nenhuma credencial real ou emissão no governo foi usada nos testes automatizados. Os certificados desses testes são sintéticos e as respostas governamentais simuladas. A aplicação inicia com a emissão desligada.

## Processamento

- Apenas Payment pago, produção, assinatura, valor positivo, data de aprovação definida e empresa não demo/arquivada/excluída.
- O pagamento continua válido se faltar cadastro fiscal, certificado ou conexão.
- Só pagamentos a partir do marco configurado entram automaticamente; pedidos anteriores exigem ação explícita do Master.
- Uma FiscalDocumentRequest por pagamento e uma DPS estável. A fila consulta essa DPS antes de transmitir, inclusive após timeout.
- XMLDSig RSA-SHA256 e certificado A1 com autenticação mútua TLS. A DPS é validada pelo XSD oficial 1.01 antes da transmissão.
- Documento autorizado só é publicado após conferir DPS, CNPJ emissor, ambiente, valor, tomador, competência e código do serviço na resposta.
- Em homologação, arquivos são exclusivos do Master, com indicação de ausência de validade jurídica. A conversão para produção exige ação explícita.
- Após rejeição definitiva, o Master pode corrigir os dados e repetir a mesma DPS; respostas incertas preservam integralmente o XML transmitido.
- Até seis tentativas automáticas com espera progressiva. O Master pode reprocessar. A fila é reconciliada a cada cinco minutos e recupera indisponibilidade do broker.
- XML disponível na conta contratante e aviso único por e-mail. PDF auxiliar gerado localmente a partir do XML autorizado, com QR Code oficial. Este PDF é uma representação para leitura, com fontes portáveis; não é uma certificação de conformidade gráfica do DANFSe v2.0. O XML autorizado é o documento fiscal original. A API governamental antiga de PDF foi suspensa em julho de 2026 (NT 008/2026).
- Falha do PDF mantém a nota autorizada e o XML disponível; repetir a geração do PDF não emite nova nota.
- Estorno não cancela automaticamente uma nota. O Master deve conferir o pagamento e solicitar o procedimento fiscal cabível no emissor nacional, com sua contabilidade.

## Segurança e operação

Certificado, chave privada e senha criptografados pelo `DJANGO_FIELD_ENCRYPTION_KEY`, sem download, registro em auditoria ou exibição de valores. Arquivos PEM de transporte temporários têm permissão 0600 e são removidos ao encerrar a conexão. Preserve a chave de criptografia em restaurações. Somente Master configura/processa; somente gestão da própria empresa e Master baixam documentos. Não há callback fiscal público nem endpoint configurável que receba certificados. Hosts HTTPS oficiais são fixos, com verificação TLS e sem redirecionamentos.

As telas exibem código da rejeição e histórico sanitizado, sem corpos completos de erro ou credenciais. Worker e beat precisam estar ativos. A emissão real depende do credenciamento, certificado e homologação do seu CNPJ.

## Fontes técnicas

- https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/documentacao-atual
- https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-emissor-publico-api-sistema-nacional-nfs-e-v1-2-out2025.pdf
- https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao
- https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/rtc/nt-008-se-cgnfse-danfse-20260505.pdf
