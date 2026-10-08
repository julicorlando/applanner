# Nota final ApPlanner

## Cálculo ponderado provisório

| Categoria | Peso | Nota | Parcela |
|---|---:|---:|---:|
| Estabilidade e confiabilidade | 20% | 9,2 | 1,84 |
| Agendamento e regras de negócio | 15% | 9,4 | 1,41 |
| Segurança e LGPD | 15% | 9,1 | 1,37 |
| UX/UI e experiência mobile | 15% | 9,0 | 1,35 |
| Financeiro e pagamentos | 10% | 8,4 | 0,84 |
| Gestão multiempresa/unidades | 10% | 9,2 | 0,92 |
| Integrações/comunicação | 5% | 7,0 | 0,35 |
| Performance/escalabilidade | 5% | 7,2 | 0,36 |
| Testes/documentação | 5% | 9,0 | 0,45 |
| **Total** | **100%** |  | **8,89/10** |

A nota de código/CI é **8,89/10**. Ela não é 9,5 porque ainda faltam provas operacionais de WhatsApp, SMTP, provedor de pagamento, carga e restauração off-site. O sistema pode iniciar piloto controlado após redeploy e homologação dessas integrações; a nota 9,5 exige completar esse release gate.
