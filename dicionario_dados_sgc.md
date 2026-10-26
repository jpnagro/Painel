# Dicionário de Dados — Tabelas do SGC (`ccb`, `installments`, `client_data`)

Este documento lista, campo a campo, as três tabelas do banco Postgres do SGC usadas como fonte de dados do Painel: `ccb` (contratos), `installments` (parcelas) e `client_data` (dados cadastrais/cadastro de risco do cliente). Para cada campo consta o tipo (via `information_schema.columns`) e uma descrição de negócio baseada no **uso real do campo no código do Painel** (`app/crud/**`) — não uma definição genérica de mercado.

**Última atualização:** 11/09/2026

> **Nota para o Agente de IA (Chat AI):** este documento complementa o `documentacao_indicadores.md`. Use-o quando o usuário perguntar sobre um campo específico do banco (via `executar_sql_select`) e precisar saber o que aquele campo significa ou se ele é de fato usado em algum indicador do Painel. Campos marcados como "não referenciado no Painel" existem no banco mas não alimentam nenhum indicador hoje — não presuma que aparecem em algum cálculo.

Convenções usadas abaixo:
- **Uso no Painel**: onde/como o campo é efetivamente consumido pelo código (arquivo, indicador). Quando marcado como "não referenciado", o campo existe na tabela mas nenhum arquivo em `app/crud/**` o utiliza hoje.
- Campos booleanos (`boolean`) costumam vir com `NULL` no banco quando o valor não foi informado; o Painel trata `NULL` como `False` (função `_bool_true`) na maioria dos casos.
- Chave estrangeira "consolidação de raiz": quando `ccb.renegotiation = TRUE`, o `operationCode` daquele registro é uma renegociação, e `ccb.externalId` aponta para o `operationCode` do contrato **raiz**. O Painel remapeia praticamente tudo para a raiz antes de calcular indicadores (ver seção 1.1 do `documentacao_indicadores.md`).

---

## 1. Tabela `ccb` (contratos)

Uma linha por contrato (CCB). Chave primária: `operationCode`.

| Campo | Tipo | Uso no Painel |
|---|---|---|
| `operationCode` | varchar | Chave de junção universal do contrato — liga com `installments.operationCode` e, via `client_data.ccbCode`, com os dados cadastrais. Base de todo remapeamento raiz↔renegociação. |
| `clientId` | varchar | Não referenciado no Painel (existe também em `customer_monitoring`, tabela separada). |
| `taxId` | varchar | CPF/CNPJ do cliente. Usado para dedup de `client_data` em contratos CPR e como dimensão do HHI de concentração por cliente. |
| `name` | varchar | Nome do cliente/contrato — só exibido como rótulo (ex.: Monitoramento de Clientes), não entra em nenhum cálculo. |
| `releaseDate` | date | Data de originação do contrato-raiz. Base de todos os filtros de período, da definição de safra (`AAAA-MM` de originação) e da idade da safra em meses. |
| `principalAmount` | numeric | Valor principal originado/concedido. Usado como "valor originado" em quase todo indicador de volume (resumo da carteira, ticket médio, volume por variável em Análise de Risco); é o fallback quando `totalLoan` está nulo. |
| `adjustedPrincipalAmount` | numeric | Não referenciado. |
| `iofCost` | numeric | Não referenciado. |
| `tedCost` | numeric | Não referenciado. |
| `analysisCost` | numeric | Não referenciado. |
| `emissionFee` | numeric | Não referenciado. |
| `grossValue` | numeric | Não referenciado. |
| `netValue` | numeric | Não referenciado. |
| `totalLoan` | numeric | Valor total contratado (principal + juros contratados). Usado como "valor total emprestado"/originado no resumo da carteira e como fallback preferencial de `principalAmount` em rentabilidade e curva de maturação; também denominador de `taxa_writeoff`. |
| `totalInterest` | numeric | Total de juros contratados. Base de "Total de Juros (Contratada)" no Painel Executivo e de indicadores de % de juros / margem financeira bruta. |
| `installments` | integer | Número de parcelas do contrato. Só é usado para "prazo médio (meses)" no resumo da carteira — métrica hoje comentada/não exibida na tela. |
| `installmentAmount` | numeric | Não referenciado. |
| `monthlyRate` | numeric | Taxa de juros mensal contratada (fração decimal, ex. 0.0635 = 6,35%). Usada no yield médio ponderado por saldo devedor (aba Rentabilidade) e na "taxa média" do Painel Executivo (ponderada por `principalAmount`). |
| `monthlyTotalRate` | numeric | Não referenciado. |
| `anualRate` | numeric | Taxa de juros anual contratada. Mesma lógica de `monthlyRate`, para o yield anual ponderado em Rentabilidade. |
| `anualTotalRate` | numeric | Não referenciado. |
| `delayFine` | numeric | Não referenciado. |
| `delayInterest` | numeric | Não referenciado. |
| `guarantors` | boolean | Não referenciado. |
| `renewal` | boolean | Usado apenas como *fallback* de `renewed` (quando esta coluna não existe no dataframe) no cálculo de "taxa de renovação". |
| `currentPortfolio` | varchar | Não referenciado (o campo de portfólio efetivamente usado no Painel é `installments.portfolio`). |
| `bank` | varchar | Não referenciado. |
| `paid` | boolean | Flag de contrato totalmente quitado. Presente na base consolidada, mas os indicadores de saldo/inadimplência de fato usam `installments.paid` (nível de parcela), não este campo. |
| `paidInstallments` | integer | Não referenciado. |
| `dueInstallments` | integer | Não referenciado. |
| `overdueInstallments` | integer | Não referenciado. |
| `currentlyOverdue` | boolean | Não referenciado. |
| `delayedInstallments` | integer | Não referenciado. |
| `default` | boolean | Flag bruta "em default", vinda do sistema de origem (não recalculada pelo Painel). Base da "% default (FPD)" e usada como filtro no Painel Executivo. **Não confundir** com o "Inadimplência 90+" do Painel, que é calculado a partir de `installments.delay`. |
| `firstPaymentDefault` | boolean | Flag bruta "1ª parcela em atraso/não paga", vinda do sistema de origem. Base do indicador "FPD (First Payment Default)" no Painel Executivo e na aba Análise da Carteira. |
| `prePaid` | boolean | Flag de contrato pré-pago. Base da "taxa de pré-pagamento". |
| `renegotiated` | boolean | Marca que este contrato **já foi** renegociado (é raiz de uma renegociação). Central na separação raiz/renegociação, na "taxa de renegociados" e no book de renegociações. |
| `renewed` | boolean | Flag de renovação de contrato. Base da "taxa de renovação". |
| `financedIof` | boolean | Não referenciado. |
| `gracePeriod` | integer | Não referenciado. |
| `downPayment` | numeric | Não referenciado. |
| `renegotiation` | boolean | Marca que **este registro** é uma renegociação (uma geração renegociada, não a raiz). Junto com `externalId`, é o campo que dispara a consolidação de toda a família de renegociações num único contrato raiz. |
| `creationDate` | date | Não referenciado. |
| `updatedDate` | date | Não referenciado. |
| `externalId` | varchar | Quando `renegotiation = TRUE`, aponta para o `operationCode` do contrato raiz. Chave usada para consolidar toda a família raiz + renegociações em um único código em praticamente todo o pipeline de dados. |
| `graceamount` | numeric | Não referenciado. |
| `tacamount` | numeric | Não referenciado. |
| `prePaidAmount` | numeric | Valor pré-pago. Somado (só para contratos com `prePaid = True`) na "taxa de pré-pagamento". |
| `originationFee` | numeric | Não referenciado. |
| `duration` | numeric | Não referenciado. |
| `anualDuration` | numeric | Não referenciado. |
| `effectiveFee` | numeric | Não referenciado. |
| `durationRevenue` | numeric | Não referenciado. |
| `totalRevenue` | numeric | Receita total do contrato. Usado na aba Rentabilidade. |
| `transferDate` | date | Não referenciado. |
| `interestAccrual` | numeric | Não referenciado. |
| `commercialRevenue` | numeric | Receita comercial do contrato. Um dos componentes de receita detalhados na aba Rentabilidade. |
| `originationRevenue` | numeric | Receita de originação do contrato. Componente de receita detalhado na aba Rentabilidade. |
| `treasuryRevenue` | numeric | Receita de tesouraria do contrato. Componente de receita detalhado na aba Rentabilidade. |

**Observação:** boa parte dos campos "não referenciados" são custos/taxas granulares de originação (`iofCost`, `tedCost`, `analysisCost`, `emissionFee`, `originationFee`, `graceamount`, `tacamount` etc.) — o Painel trabalha só com os valores já agregados (`principalAmount`, `totalLoan`, `totalInterest`, receitas por tipo), não com a composição desses custos.

---

## 2. Tabela `installments` (parcelas)

Uma linha por parcela. Chave primária: `installmentCode`; chave estrangeira `operationCode` → `ccb.operationCode`.

| Campo | Tipo | Uso no Painel |
|---|---|---|
| `operationCode` | varchar | FK para `ccb`/`cpr`. Depois do remapeamento de raiz, é a chave de agregação de saldo e atraso por contrato. |
| `installmentCode` | varchar | Não referenciado (só serve como chave primária da tabela). |
| `installmentNumber` | integer | Não referenciado. |
| `taxId` | varchar | Não referenciado nesta tabela (o CPF/CNPJ usado nos cálculos vem de `ccb`/`client_data`). |
| `name` | varchar | Não referenciado nesta tabela. |
| `releaseDate` | date | Usado (via query SQL direta) para filtrar a janela de originação na avaliação do modelo de crédito (KS/Gini/PSI, aba Monitoramento do Modelo). |
| `dueDate` | date | Data de vencimento da parcela. Base da reconstrução histórica mês a mês de saldo/atraso (comparação com a data de corte de cada "foto" mensal e com `paymentDate`). |
| `amount` | numeric | Valor cheio da parcela. Somado para o **saldo devedor** dos contratos em aberto (`saldo_atual`), para o "valor total das parcelas" e para o saldo aberto histórico mês a mês; base de `total_installment_amount`/`total_due_amount` no Painel Executivo. |
| `interestAmount` | numeric | Não referenciado. |
| `principalAmount` | numeric | Componente de principal da parcela (distinto de `amount`, que é o valor cheio). Usado nas métricas "de principal" do Painel Executivo/Análise de Risco: principal pago, saldo devedor de principal, principal vencido 90+. |
| `beginningBalance` | numeric | Não referenciado — apesar de um comentário no código (`carteira/data.py`) citar este campo como base conceitual do saldo devedor, a implementação de fato soma `amount` das parcelas em aberto, não `beginningBalance`. |
| `endingBalance` | numeric | Não referenciado. |
| `paid` | boolean | Flag central: define se uma parcela está "paga" ou "em aberto" em praticamente todo o pipeline (saldo devedor, reconstrução histórica, agregados do Painel Executivo). |
| `paymentDate` | date | Data em que a parcela foi efetivamente paga. Usada junto com `dueDate` na reconstrução histórica de atraso; preenchida em ~100% das parcelas pagas. |
| `paidAmount` | numeric | Valor pago da parcela. Somado no resumo da carteira (aberta/paga/write-off) e usado para calcular saldo residual (`amount − paidAmount`) e `total_paid_amount` no Painel Executivo. |
| `outstandingAmount` | numeric | Não referenciado — o "saldo em aberto" do Painel é sempre derivado de `amount`/`principalAmount` menos `paidAmount`, não deste campo pronto. |
| `penalties` | numeric | Não referenciado. |
| `discounts` | numeric | Não referenciado. |
| `currentlyOverdue` | boolean | Não referenciado (o atraso do Painel é sempre derivado de `delay`, não deste flag). |
| `overdued` | boolean | Não referenciado. |
| `delay` | integer | Dias de atraso da parcela. Campo central de risco: base do `max_delay` por contrato, de todos os cortes de NPL/aging/write-off (15/30/60/90/360 dias) e da variável-alvo (mau pagador) do modelo de monitoramento. |
| `default` | boolean | Não referenciado nesta tabela (o "default" usado nos indicadores é o de `ccb`, nível contrato). |
| `prePaid` | boolean | Não referenciado nesta tabela (o pré-pagamento usado nos indicadores é o de `ccb`). |
| `writeOff` | boolean | Flag bruta de baixa a prejuízo, vinda do sistema de origem. Agregada por contrato ("write-off = alguma parcela com writeOff=true") e exibida como "Write-off (contratos)" — diverge, por definição, do critério "oficial" do Painel (`max_delay ≥ 360`), que é o usado para classificar o balde write-off nos demais indicadores. Ver seção 3.4 do `documentacao_indicadores.md`. |
| `portfolio` | varchar | Fundo/veículo que detém o recebível (ex.: Ghia, Oikos, Kanastra). Base do filtro "Portfolio" do Painel — é um atributo de parcela, não de contrato, então um mesmo contrato pode ter parcelas em portfolios diferentes ao longo do tempo. |
| `key` | varchar | Não referenciado. |
| `renegotiation` | boolean | Réplica, em nível de parcela, do flag de `ccb`. Usada para excluir parcelas de gerações renegociadas em queries de avaliação de modelo e no book de renegociações. |
| `renegotiated` | boolean | Flag por parcela usada para calcular até quando aquela parcela "valeu" antes de ser substituída por uma renegociação (vigência temporal). |
| `updatedDate` | date | Não referenciado. |
| `bank_slip_key` | varchar | Não referenciado. |
| `externalId` | varchar | Não referenciado nesta tabela (o remapeamento de raiz sempre usa o `externalId` de `ccb`/`cpr`). |
| `originationFee` | numeric | Não referenciado. |
| `adjustedAmount` | numeric | Não referenciado. |
| `dailyRate` | numeric | Não referenciado. |
| `adjustedPrincipalAmount` | numeric | Não referenciado. |
| `transferDate` | date | Não referenciado. |
| `interestAccrual` | numeric | Não referenciado. |
| `AccrualAdjPrinAmount` | numeric | Não referenciado. |
| `commercialRevenue` | numeric | Não referenciado nesta tabela (a receita usada em Rentabilidade é a de `ccb`, nível contrato). |
| `originationRevenue` | numeric | Não referenciado nesta tabela (idem). |
| `treasuryRevenue` | numeric | Não referenciado nesta tabela (idem). |

---

## 3. Tabela `client_data` (dados cadastrais e de risco do cliente)

Uma linha por contrato-raiz (nem toda parcela/renegociação tem entrada própria). Chave primária: `ccbCode` → `ccb.operationCode`.

| Campo | Tipo | Uso no Painel |
|---|---|---|
| `ccbCode` | varchar | FK para `ccb.operationCode` (só contratos raiz têm entrada). Chave de junção com a base de contratos em praticamente todos os módulos. |
| `dealID` | varchar | Não referenciado. |
| `taxId` | varchar | Chave de junção alternativa (nível cliente) usada no join aproximado com contratos CPR. |
| `clientId` | varchar | Não referenciado nesta tabela. |
| `state` | varchar | UF do cliente. Dimensão de corte em "NPL 90+ por estado" (Análise da Carteira) e variável disponível em Análise de Risco ("UF"). |
| `cnae` | varchar | Não referenciado diretamente (o Painel usa a versão tratada `cnaeFiltered`). |
| `activityTime` | integer | Tempo de atividade do cliente. Segmentado em faixas para analisar inadimplência por tempo de atividade (Análise de Risco). |
| `operationType` | varchar | "App" ou "Crédito Produtor" — subfiltro de tipo de operação aplicado à base inteira de CCB; vira a coluna "categoria" usada no Painel Executivo e em Análise de Risco. |
| `averageMonthlyIncome` | numeric | Renda média mensal do cliente. Segmentada em faixas de renda para analisar inadimplência por faixa de renda (Análise de Risco). |
| `rating` | varchar | Não referenciado — é uma geração anterior de rating; todo o Painel usa `rating_v4`. |
| `score` | integer | Não referenciado — geração anterior de score; todo o Painel usa `score_v4`. |
| `gender` | varchar | Não referenciado. |
| `cnaeFiltered` | varchar | Setor de atividade (CNAE) já tratado/agrupado. Dimensão de corte em "NPL 90+ por setor" e variável "Setor (CNAE)" em Análise de Risco. |
| `name` | varchar | Não referenciado como dado de cálculo (só texto de exibição, quando usado). |
| `rating_v4` | varchar | Rating de crédito do modelo atual (v4). Dimensão central de risco: NPL por rating, variável "Rating" em Análise de Risco, e distribuição/inadimplência por rating em Monitoramento do Modelo. |
| `score_v4` | integer | Score de crédito do modelo atual (v4). Usado como critério de desempate ao deduplicar `client_data` (mantém a linha de maior `score_v4` quando há mais de uma por contrato/cliente) e como base de KS, Gini, AUC, PSI e decis de score em Monitoramento do Modelo. |
| `protestos` | numeric | Indicador de protesto em nome do cliente. Calculado no "Perfil de risco do cliente", mas hoje **comentado/não exibido** na tela de Análise da Carteira. |
| `idade` | integer | Não referenciado (idade do cliente propriamente dita — não confundir com "idade da safra em meses", que é outro cálculo, sobre `releaseDate`). |
| `restritivo_nacional` | numeric | Indicador de restrição cadastral nacional. Calculado no "Perfil de risco do cliente", hoje **comentado/não exibido** na tela. |
| `carteira_ativa` | numeric | Não referenciado no Painel (as ocorrências desse nome no repositório vêm de uma fonte diferente, o HubSpot). |
| `atraso` | numeric | Não referenciado como campo cadastral (todo "atraso" calculado pelo Painel vem de `installments.delay`, não deste campo). |
| `prejuizo` | numeric | Não referenciado. |
| `rural` | numeric | Não referenciado. |
| `mandado_prisao` | varchar | Indicador de mandado de prisão. Calculado no "Perfil de risco do cliente" (comparado com "Negativa"), hoje **comentado/não exibido** na tela. |
| `embargo_ibama` | varchar | Não referenciado. |
| `trabalho_escravo` | varchar | Indicador de trabalho análogo ao escravo. Calculado no "Perfil de risco do cliente", hoje **comentado/não exibido** na tela. |
| `pep` | boolean | Indica se o cliente é Pessoa Exposta Politicamente. Calculado no "Perfil de risco do cliente", hoje **comentado/não exibido** na tela. |

**Observação — bloco "restrições cadastrais":** `protestos`, `restritivo_nacional`, `pep`, `mandado_prisao` e `trabalho_escravo` são todos calculados por `perfil_risco_cliente` (`app/crud/carteira/indicators.py`), mas sua exibição em `app/crud/carteira/view.py` está comentada no código-fonte — ou seja, são processados mas não aparecem hoje na interface do Painel.

---

## 4. Resumo rápido dos campos mais usados

Para referência rápida, os campos que sozinhos sustentam a maior parte dos indicadores do Painel:

- **Saldo e volume**: `ccb.principalAmount`, `ccb.totalLoan`, `installments.amount`, `installments.principalAmount`, `installments.paidAmount`.
- **Risco/atraso**: `installments.delay` (e o `max_delay` derivado por contrato), `installments.writeOff`, `ccb.default`, `ccb.firstPaymentDefault`.
- **Consolidação de raiz**: `ccb.renegotiation`, `ccb.renegotiated`, `ccb.externalId`.
- **Segmentação/risco do cliente**: `client_data.rating_v4`, `client_data.score_v4`, `client_data.state`, `client_data.cnaeFiltered`, `client_data.averageMonthlyIncome`, `client_data.activityTime`.
- **Rentabilidade**: `ccb.monthlyRate`, `ccb.anualRate`, `ccb.totalRevenue`, `ccb.commercialRevenue`, `ccb.originationRevenue`, `ccb.treasuryRevenue`.
- **Carteira/portfolio**: `installments.portfolio`, `client_data.operationType`.
