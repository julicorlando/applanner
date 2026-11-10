# Implantação — transcrição de prontuários anteriores (Odontologia)

O responsável da clínica (owner ou tenant-admin) ativa a fase de implantação em
Configurações → "Implantação: transcrever prontuários anteriores"
(`/app/odontologia/implantacao/`). A janela começa no dia da ativação, dura até
180 dias e pode ser encerrada antes. Há apenas uma janela ativa por clínica, e
abertura e encerramento ficam na auditoria.

Com a janela ativa, o editor de prontuário odontológico mostra a opção
"Prontuário anterior transcrito na implantação". Marcada:

- a "Data" do formulário passa a ser a data do atendimento original (hoje ou anterior);
- o vínculo com um agendamento deixa de ser obrigatório na finalização;
- o registro recebe `clinical_date` e `transcribed_in_period`, e o título indica "transcrito";
- `created_at` continua sendo a data e a hora reais da digitação e não pode ser alterado;
- o orçamento informado fica no histórico, mas não gera plano proposto nem lançamento financeiro.

Históricos e linhas do tempo são ordenados pela data clínica e depois pela digitação.
As telas mostram "dd/mm/aaaa (transcrito na implantação em dd/mm/aaaa hh:mm)".

Fora da janela, `create_record` recusa qualquer `clinical_date`. A migration
`healthcare.0020` é aditiva: as colunas novas são nulas e nenhum prontuário existente é alterado.
