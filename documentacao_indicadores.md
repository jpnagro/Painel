# Documentação de Indicadores e Gráficos — Painel Nagro Crédito

Este documento explica, aba por aba, o que cada indicador e gráfico do Painel mostra e **exatamente como ele é calculado**. O objetivo é dar transparência total sobre a metodologia por trás dos números — de onde vêm os dados, quais filtros afetam cada cálculo e qual fórmula está por trás de cada métrica.

**Última atualização:** 22/10/2026

> **Nota para o Agente de IA (Chat AI):** este documento é a fonte primária de metodologia usada pelo
> agente para responder perguntas sobre o Painel. Sempre que uma pergunta envolver "inadimplência" ou
> "NPL", verifique a seção 1.5 antes de responder — são DUAS fórmulas diferentes (denominadores
> diferentes), e usar a errada produz um número que não bate com o que o usuário vê na tela.

---

## Sumário

1. [Conceitos comuns a várias abas](#1-conceitos-comuns-a-várias-abas) (destaque: 1.5 — NPL x Inadimplência)
2. [Monitoramento do Modelo](#2-monitoramento-do-modelo)
   - 2.1 [Sub-aba Relatório](#21-sub-aba-relatório)
   - 2.2 [Sub-aba Estabilidade Rating](#22-sub-aba-estabilidade-rating)
3. [Análise da Carteira](#3-análise-da-carteira)
4. [Painel Executivo](#4-painel-executivo)
5. [Análise de Risco](#5-análise-de-risco)
   - 5.1 [Sub-aba Análise de variáveis](#51-sub-aba-análise-de-variáveis)
   - 5.2 [Sub-aba Simulador](#52-sub-aba-simulador)
6. [Monitoramento de Clientes](#6-monitoramento-de-clientes)
7. [Glossário rápido](#7-glossário-rápido)

---

## 1. Conceitos comuns a várias abas

Antes de entrar em cada aba, é importante entender cinco conceitos que se repetem em praticamente todo o Painel. Eles garantem que os números batam entre abas diferentes — não são regras isoladas de uma única tela.

### 1.1 Consolidação de renegociações (a "raiz" do contrato)

Quando um contrato é renegociado, o sistema não trata a renegociação como um empréstimo novo — ela é uma reestruturação do saldo de um contrato que já existe. Por isso, o Painel sempre remapeia toda renegociação (inclusive uma renegociação de outra renegociação) para o código do contrato **original** (chamado de "raiz"), usando o campo `externalId` que cada renegociação carrega apontando para o contrato de origem.

Na prática, isso significa que:

- O **valor originado/concedido** de um contrato só é contado uma vez (no contrato raiz), mesmo que ele tenha sido renegociado várias vezes.
- O **histórico de pagamento** de um cliente (raiz + todas as renegociações) fica unificado sob uma única chave, permitindo calcular corretamente saldo devedor, atraso e status atual.
- Filtros de produto, período e portfólio decidem se um contrato entra ou sai da base sempre olhando para a raiz — se a raiz atende ao filtro, a raiz e todas as suas renegociações entram juntas.

### 1.2 Definição de write-off (baixa a prejuízo)

O corte oficial de write-off usado nas abas "Análise da Carteira", "Painel Executivo", "Análise de Risco" e "Monitoramento de Clientes" é:

> **Write-off = contrato com atraso máximo (`max_delay`) MAIOR que 360 dias em alguma parcela em aberto (`max_delay > 360`).** Um contrato com exatamente 360 dias de atraso ainda NÃO é write-off — fica na carteira em aberto e entra no NPL.

Esse critério (apelidado de `WO = 360` no código; write-off é `max_delay > WO`, carteira "viva" é `max_delay <= WO`) é usado de forma consistente para separar "Carteira em aberto" de "WriteOff" nessas quatro abas. A única exceção documentada está na aba "Análise da Carteira", no indicador "Write-off (contratos)" das Taxas-chave (seção 3.4), que usa um flag bruto do banco (`writeOff`) em vez do corte de 360 dias.

### 1.3 A fórmula canônica de "% da Carteira" (Inadimplência 90+ — denominador = saldo TOTAL)

Esta é a fórmula mais reaproveitada do Painel — aparece no **Painel Executivo** e em toda a **Análise de Risco** (ranking de dispersão, inadimplência por variável, cruzamento e Simulador), sempre com o mesmo resultado para o mesmo recorte de dados. Nessas abas o Painel chama esse indicador de **"Inadimplência"**, nunca de "NPL" — ver a distinção completa na seção 1.5.

> **% da Carteira (Inadimplência 90+) = (soma do valor total das parcelas em aberto dos contratos com atraso ≥ 90 dias) ÷ (soma do valor total de TODAS as parcelas do recorte, pagas e em aberto) × 100**

Em outras palavras: de tudo o que foi contratado (parcelas cheias, pagas ou não) dentro do filtro selecionado, que fatia pertence a contratos que já acumulam 90 dias ou mais de atraso em alguma parcela? O numerador olha só o saldo das parcelas ainda em aberto desses contratos ruins (campo `total_due_amount` das parcelas não pagas); o denominador é o **saldo total contratado** de todo o grupo, bons e ruins, pago e em aberto (campo `total_installment_amount`) — não é o saldo devedor remanescente. A mesma lógica se aplica às outras faixas de atraso (15, 30, 60 dias, e ao corte de "1ª parcela em atraso" usado no FPD), trocando apenas o corte de dias/condição.

### 1.4 Nível do NPL/Inadimplência: contrato inteiro, não parcela isolada

Quando um contrato atinge o corte de atraso de uma faixa (por exemplo, 90 dias) em **qualquer uma** de suas parcelas em aberto, o Painel considera o **contrato inteiro** como parte daquela faixa de risco — não apenas a parcela atrasada. Essa é a metodologia padrão de mercado: uma parcela em atraso "contamina" a leitura de risco do contrato como um todo. Essa regra vale tanto para o NPL (seção 1.5) quanto para a Inadimplência (seção 1.3).

### 1.5 NPL (saldo devedor) x Inadimplência / "% da Carteira" (saldo total) — não confundir

O Painel usa **dois termos diferentes de propósito**, com **denominadores diferentes**, para a mesma ideia geral de "contratos em atraso". Confundir os dois produz números que parecem incoerentes entre abas, mas na verdade estão corretos — são só perguntas diferentes:

| | **NPL** | **Inadimplência / "% da Carteira"** |
|---|---|---|
| Onde aparece | Aba "Análise da Carteira": "NPL por faixa de atraso & Aging" (3.3) e "Perfil de risco do cliente" (3.9); e, no Painel Executivo, os KPIs "NPL 90" / "NPL 90 + WO" (4.1) e a seção "Inadimplência — NPL 90 e NPL 30" e a evolução do NPL 90 (4.3, itens 4 e 5) | Painel Executivo: gráfico e tabela "Indicadores de Risco" (4.3, itens 1 e 2); e toda a Análise de Risco (5.1, 5.2) |
| Denominador | **Saldo devedor** do grupo — só o que ainda falta pagar hoje (`saldo_atual`) | **Saldo total contratado** do grupo — soma de TODAS as parcelas, pagas e em aberto (`total_installment_amount`) |
| Numerador | Saldo devedor dos contratos ruins (mesmo campo do denominador, `saldo_atual`) | Saldo em aberto (parcelas não pagas) dos contratos ruins (`total_due_amount`) |
| Efeito prático | Cresce à medida que o contrato bom vai sendo pago (o saldo devedor total encolhe, então a mesma dívida ruim pesa proporcionalmente mais) | Não varia só por causa de pagamentos em dia de outros contratos, porque o denominador é o total contratado, fixo desde a originação |
| População | "NPL" / "NPL 30/90" (sem WO) sempre exclui write-off (só entra `max_delay <= 360`); as variantes "c/ WO" / "+ WO" do Painel Executivo incluem o write-off no numerador e no denominador | Depende do filtro "Carteira" da aba (pode incluir write-off se "Carteira total" ou "WriteOff" estiver selecionado) |

**Regra prática para responder perguntas do usuário**: se a pergunta cita "NPL" ou vem no contexto da aba "Análise da Carteira" (por rating/UF/CNAE/faixa de atraso), use a ferramenta/dado de NPL (saldo devedor). Se a pergunta cita "inadimplência" de forma genérica, ou vem no contexto de Painel Executivo/Análise de Risco/Simulador, use a fórmula canônica "% da Carteira" (saldo total). Se não estiver claro qual o usuário quer, prefira responder com a "Inadimplência" canônica (é a mais usada no Painel) e deixe explícito na resposta qual fórmula foi usada e por quê.

### 1.6 Produto CPR excluído de todo o Painel: "Antecipação Recebiveis"

O tipo de produto CPR **"Antecipação Recebiveis"** (`cpr.productType`) é usado no sistema de origem como produto de "estacionamento" — contrato que não deve contar em indicador nenhum. Por isso ele é **excluído de todo o Painel** (Análise da Carteira, Painel Executivo, Análise de Risco e os filtros de tipo de produto CPR do Monitoramento de Clientes): os contratos desse tipo e as parcelas deles saem da base antes de qualquer cálculo (saldo, atraso, NPL, PDD, faixas de atraso, concedido, etc.), e ele não aparece mais como opção de categoria/filtro. A consolidação das renegociações é resolvida sobre todos os contratos antes da exclusão, então as demais cadeias não são afetadas. Os outros tipos de CPR (AgCred, Giro Agro, Farm Equity...) continuam normalmente.

---

## 2. Monitoramento do Modelo

Esta aba tem duas sub-abas — **Relatório** e **Estabilidade Rating** — que, apesar de usarem termos parecidos (PSI, KS), medem coisas **completamente diferentes**. É importante não confundir os dois:

| | Relatório | Estabilidade Rating |
|---|---|---|
| O que mede | Se o **modelo de score** (a fórmula matemática que estima o risco de cada cliente) continua funcionando bem e se sua distribuição de notas mudou desde o treinamento | Se a **distribuição de ratings da carteira comercial** (quantos clientes em cada nota A, B, C...) está se deslocando ao longo dos meses em relação a um mês de referência |
| Base de comparação | Base de treino/teste do modelo (arquivo interno) | Uma safra fixa de junho/2025, extraída do CRM |
| Fonte dos dados "atuais" | Banco de dados de operações (Postgres) | Arquivo exportado do HubSpot/CRM |
| Granularidade | Score numérico (0 a 1000) | Categoria de rating (AA, A, B, ..., H) |

Ou seja: "Relatório" responde **"o modelo ainda separa bem quem paga de quem não paga?"**; "Estabilidade Rating" responde **"o perfil de risco da carteira comercial está mudando mês a mês?"**.

### 2.1 Sub-aba Relatório

#### 2.1.1 De onde vêm os dados

- **Base de Referência**: a base de treino/teste usada quando o modelo de score v4 foi desenvolvido (arquivo `ccb_test.xlsx`). É fixa — não muda com os filtros da tela.
- **Base de Produção**: consulta ao banco de dados (`installments` + `client_data`), restrita à janela de datas de originação (`releaseDate`) escolhida nos filtros "Início (produção)" / "Fim (produção)". Contratos que são renegociação ou que já foram renegociados são excluídos dessa consulta, para não distorcer a leitura.
- **Alvo (`target`)**: um contrato é marcado como "mau pagador" (`target = 1`) se tiver qualquer parcela com mais de 90 dias de atraso e ainda não paga; caso contrário, é "bom pagador" (`target = 0`).

#### 2.1.2 Indicadores de Desempenho

| Indicador | O que mede | Como é calculado |
|---|---|---|
| **KS — Referência / KS — Produção** | Capacidade do score de separar bons e maus pagadores (quanto maior, melhor) | Estatística de Kolmogorov-Smirnov entre a distribuição de score dos bons pagadores e dos maus pagadores, dentro de cada base (referência ou produção) |
| **Gini — Referência / Gini — Produção** | Poder discriminante do modelo, em escala equivalente à usada no mercado de crédito | `Gini = 2 × AUC − 1`, onde AUC é a área sob a curva ROC calculada a partir da probabilidade de inadimplência prevista pelo modelo |
| **PSI** | Se a distribuição de score da carteira em produção se afastou da distribuição vista no treinamento do modelo | Compara os decis de score entre as 3.000 operações mais recentes da base de referência e a base de produção filtrada; ver fórmula detalhada abaixo |
| **Inadimplência (>90d)** | Taxa observada de mau pagador na janela de produção filtrada | Percentual de contratos com `target = 1` na base de produção |

**Faixas de leitura** (mesmos limites usados no `st.metric` da tela):

| Métrica | 🟢 Bom | 🟡 Atenção | 🔴 Crítico |
|---|---|---|---|
| KS | ≥ 0,20 | 0,10 – 0,20 | < 0,10 |
| Gini | ≥ 0,30 | 0,20 – 0,30 | < 0,20 |
| PSI | < 0,10 | 0,10 – 0,25 | ≥ 0,25 |

**Fórmula do PSI (Population Stability Index) desta sub-aba:**

1. Divide-se a distribuição de score da base de Referência em 10 decis.
2. Calcula-se a proporção de operações da Referência e da Produção que caem em cada decil.
3. Para cada decil: `(proporção produção − proporção referência) × log(proporção produção ÷ proporção referência)`.
4. O PSI total é a soma dessas 10 parcelas.

Um PSI baixo significa que a carteira em produção tem uma distribuição de score parecida com a que o modelo "aprendeu" no treinamento; um PSI alto indica que o perfil de score da carteira mudou (para melhor ou para pior) desde então.

#### 2.1.3 Gráficos

| Gráfico | O que mostra | Como é calculado |
|---|---|---|
| **Distribuição de Ratings** | Frequência de cada rating (AA a H) na base de Referência vs. Produção | Percentual de operações em cada rating, ordenado da melhor para a pior nota |
| **Tabela Resumo (por rating, produção)** | Total de contratos, inadimplentes e score médio por rating | Contagem e média de score agrupados por rating, com taxa de inadimplência (`inadimplentes ÷ total`) |
| **Inadimplência por Rating** (Referência e Produção) | Taxa de inadimplência observada em cada faixa de rating | `soma de target ÷ contagem de contratos`, por rating |
| **Curva ROC & Estabilidade** | Capacidade do modelo de ranquear risco (comparando Referência e Produção) | Curva ROC clássica (sensibilidade vs. 1-especificidade), com AUC e Gini de cada base na legenda |
| **PSI por Decil** | Quais decis de score mais contribuem para o PSI total | Contribuição individual de cada um dos 10 decis para o cálculo do PSI, com linha de referência marcando o limite recomendado por decil |
| **Curva KS** (Referência e Produção) | Ponto onde a separação entre bons e maus pagadores é máxima | Proporção acumulada de bons e maus pagadores ao longo dos valores de score; o ponto de maior distância entre as duas curvas é o valor de KS |

**Filtros que afetam esta sub-aba**: apenas "Início (produção)" / "Fim (produção)" — eles restringem a base de Produção pela data de originação do contrato. A base de Referência é sempre fixa (não tem filtro). O botão "🔄 Recarregar dados" força uma nova consulta ao banco e ao arquivo de referência.

### 2.2 Sub-aba Estabilidade Rating

#### 2.2.1 De onde vêm os dados

Diferente do "Relatório", esta sub-aba **não consulta o banco de operações** — ela lê um arquivo CSV exportado do CRM (HubSpot), com uma linha por consulta/negociação e o rating atribuído naquele momento (`Rating Nagro 4.0`) e a data da consulta (`Data consulta`). Cada linha é classificada em uma "safra" mensal, de acordo com o mês da consulta. Se o arquivo não estiver disponível localmente, o Painel busca os dados automaticamente do CRM antes de exibir a tela.

#### 2.2.2 A safra de referência fixa (junho/2025)

Todas as comparações desta sub-aba usam como base fixa a distribuição de ratings observada em **junho de 2025**. Para cada categoria de rating (AA, A, B, C, D, E, F, G, H), calcula-se:

- **Quantidade** de deals com aquele rating na safra de referência.
- **% de participação** (quantidade da categoria ÷ total da safra).
- **% acumulado**, somando as participações na ordem do melhor rating (AA) para o pior (H).

#### 2.2.3 PSI e KS1 por safra mensal

Para cada mês a partir de julho/2025, o Painel compara a distribuição de rating daquele mês contra a safra de referência (junho/2025), rating a rating:

> **PSI (por rating) = (% participação referência − % participação do mês) × log(% participação referência ÷ % participação do mês)**

O PSI total do mês é a soma dessa conta em todas as categorias de rating. Quanto maior, mais a "forma" da distribuição de ratings mudou em relação à referência.

> **KS1 = maior diferença absoluta entre a % acumulada da referência e a % acumulada do mês, olhando rating por rating**

Isso é a definição clássica de estatística KS (maior distância entre duas curvas acumuladas), só que aplicada à sequência ordenada de ratings (AA → H) em vez de a um score contínuo. Um KS1 alto indica que, em algum ponto da escala de rating, o mês avaliado se afastou muito da composição de referência.

**Status de alerta**: se o PSI total ou o KS1 total do mês for igual ou maior que 10% (0,10), a tela sinaliza "Atenção — Acima 10%"; abaixo disso, o status é "Ok".

#### 2.2.4 O que aparece na tela

| Elemento | Conteúdo |
|---|---|
| Safra de referência — Jun/25 (expansível) | Tabela com quantidade, % de participação e % acumulado por rating na safra de referência |
| Resumo por safra | Uma linha por mês (a partir de jul/2025) com quantidade de deals, PSI, KS1 e status de cada um |
| Tabelas detalhadas por safra (uma por mês, expansíveis) | Comparação rating a rating entre o mês e a referência, com PSI e KS1 individuais |
| Botão "🔄 Atualizar dados do CRM" | Busca deals novos diretamente do HubSpot e atualiza o arquivo local |

**Filtros que afetam esta sub-aba**: nenhum filtro de carteira/produto/data — a comparação é sempre contra a safra fixa de junho/2025, para todos os meses disponíveis no arquivo.

---

## 3. Análise da Carteira

Esta é a aba com a visão mais granular da carteira de crédito, cobrindo composição, inadimplência, maturação, rentabilidade e concentração. Todos os indicadores desta aba partem da mesma base de dados (contratos CCB e CPR consolidados pela raiz, conforme a seção 1.1) e são recalculados de acordo com quatro filtros: **Portfolio**, **Produto** (CCB/CPR e seus subfiltros), e **Período** (Início/Fim, pela data de originação da raiz).

### 3.1 Os três recortes da carteira: Total, Em aberto e WriteOff

Os três primeiros blocos da tela mostram o mesmo conjunto de 6 indicadores (Nº de contratos, Valor originado, Valor total das parcelas, Valor pago, Saldo devedor e Saldo em NPL 90+), mas aplicados a três recortes diferentes da carteira:

- **Carteira total**: todos os contratos-raiz do filtro selecionado, sem excluir nada (inclui contratos já quitados e contratos em write-off).
- **Carteira em aberto**: exclui tanto os contratos já 100% quitados quanto os que estão em write-off (atraso > 360 dias) — é a carteira "viva" e ainda não baixada.
- **Carteira em WriteOff**: apenas os contratos com atraso > 360 dias em alguma parcela.

> **Atenção**: "Carteira total" **não** é igual à soma de "Em aberto" + "WriteOff", porque "Total" também inclui os contratos já quitados, que não entram em nenhum dos outros dois recortes.

#### 📊 Resumo da carteira total / em aberto / em WriteOff — fórmulas dos 6 indicadores

| Indicador | Fórmula |
|---|---|
| **Nº contratos** | Contagem de contratos-raiz que pertencem ao recorte (total, em aberto ou write-off) |
| **Valor originado** | Soma do valor de principal (`principalAmount`) concedido nos contratos do recorte — sempre olhando o valor original do contrato, nunca duplicado por renegociação |
| **Valor total das parcelas** | Soma do valor cheio de todas as parcelas (pagas e em aberto) dos contratos do recorte |
| **Valor pago** | Soma dos valores já pagos nas parcelas dos contratos do recorte |
| **Saldo devedor** | Soma do saldo em aberto (valor de face das parcelas ainda não pagas) dos contratos do recorte |
| **Saldo NPL 90+** | Soma do saldo devedor apenas dos contratos do recorte que estão com atraso ≥ 90 dias (na carteira em WriteOff, esse valor é igual ao saldo devedor total, já que todo write-off já está muito além de 90 dias) |

### 3.2 🔁 Book de renegociações

Mostra o comportamento específico dos contratos que passaram por renegociação, sempre analisado separadamente — nunca somado aos indicadores principais das seções anteriores.

| Indicador | Fórmula |
|---|---|
| **Contratos renegociados** | Contagem de contratos-raiz que já foram renegociados ao menos uma vez |
| **Taxa de renegociação** | Contratos renegociados ÷ total de contratos-raiz do recorte |
| **Valor total renegociado** | Saldo que os contratos tinham no momento em que foram substituídos pela renegociação |
| **Valor total das renegociações** | Soma do valor cheio das parcelas que resultaram das renegociações (a "nova" dívida reestruturada) |
| **Valor pago** | Soma do que já foi pago dessas parcelas renegociadas |
| **Saldo devedor** | Soma do que ainda está em aberto dessas parcelas renegociadas |

### 3.3 ⚠️ NPL por faixa de atraso & Aging

Duas visões complementares do risco, ambas calculadas sobre a carteira em aberto (excluindo write-off) e **sobre o saldo devedor** — é aqui, e só aqui (mais a seção 3.9), que o Painel usa o termo "NPL"; ver a distinção completa com "Inadimplência" na seção 1.5.

- **NPL por faixa de atraso**: para cada corte de atraso (15, 30, 60 e 90 dias):
  > **% NPL da faixa X = (saldo devedor dos contratos com atraso ≥ X dias) ÷ (saldo devedor de toda a carteira em aberto) × 100**
  Segue a mesma lógica de "contrato inteiro entra na faixa se qualquer parcela em aberto atingir o corte" descrita na seção 1.4. A tabela também mostra o número (e % do total de contratos) que caiu em cada faixa.
- **Distribuição de Aging**: agrupa a carteira em aberto em faixas fixas e mutuamente exclusivas de atraso (em dia, 1–30, 31–60, 61–90, 90+ dias — diferente das faixas acumulativas do "NPL por faixa"), mostrando quantos contratos e qual % do saldo devedor está em cada uma — uma "foto" da distribuição de atraso da carteira hoje.

### 3.4 📈 Taxas-chave

| Indicador | Fórmula |
|---|---|
| **Taxa de default** | % de contratos com a flag bruta `default = true` no sistema de origem — vem pronta do banco, não é recalculada pelo Painel |
| **First payment default (FPD)** | % de contratos com a flag bruta `firstPaymentDefault = true` (1ª parcela em atraso) no sistema de origem — também vem pronta do banco, não é recalculada aqui |
| **Write-off (contratos)** | % de contratos com alguma parcela sinalizada pelo flag bruto `writeOff` do sistema de origem (ver nota abaixo) |
| **Write-off (% saldo originado)** | (soma do saldo a receber dos contratos com atraso > 360 dias) ÷ (valor total originado do recorte) — usa o corte padrão `WO=360` da seção 1.2 |
| **Taxa de renegociados** | % de contratos-raiz que já foram renegociados |

> **Nota técnica importante**: "Write-off (contratos)" e "Write-off (% saldo originado)" usam **populações calculadas de forma independente** — a primeira depende só do flag bruto `writeOff` marcado pelo sistema de origem; a segunda depende só do atraso (`max_delay > 360`). Um contrato pode estar em uma população e não na outra (ex.: marcado `writeOff=true` manualmente mas com atraso ainda de 360 dias ou menos, ou vice-versa) — os dois percentuais **podem não bater** e isso não é um erro, são critérios diferentes de "write-off" coexistindo neste bloco.

### 3.5 📅 Curva de maturação por safra

Mostra como a inadimplência de cada "safra" (grupo de contratos originados no mesmo mês) evolui ao longo do tempo de vida do contrato — por exemplo, comparar como a safra de janeiro/2024 se comportava aos 6 meses de idade contra a safra de julho/2024 na mesma idade.

**Como é calculado**: para cada combinação de safra e "idade" (meses desde a originação), o Painel reconstrói, parcela a parcela, qual seria o atraso de cada contrato naquele momento específico do passado (usando as datas de vencimento e de pagamento reais, sem depender de um histórico salvo dia a dia). O indicador de cada célula é:

> **% Inadimplência da safra na idade X = (saldo que ainda estava em aberto, entre os contratos com atraso ≥ 90 dias naquela idade) ÷ (valor total originado pela safra, fixo)**

Repare que este é um **terceiro tipo de denominador**, diferente tanto do NPL (saldo devedor, seção 1.5) quanto da Inadimplência canônica (saldo total contratado — pago + em aberto, seção 1.3): aqui o denominador é o **valor originado da safra**, fixo desde o desembolso e que nunca muda com o tempo, enquanto o numerador usa o saldo que efetivamente estava em aberto naquele momento específico do passado — isso evita superestimar a perda de contratos que já pagaram boa parte das parcelas antes de entrar em atraso. Ao responder perguntas sobre esta curva, não misture esse percentual com o NPL ou a Inadimplência canônica de outras seções — são bases de cálculo diferentes.

**Visualizações**: um mapa de calor (safra x idade em meses, cor = % Inadimplência) para visão geral, e um gráfico de linhas para comparar safras específicas lado a lado (com uma linha tracejada mostrando a média de toda a carteira em cada idade). A escala de cor do mapa de calor é fixa (não se ajusta ao filtro): verde até 20%, amarelo a partir de 20%, vermelho a partir de 40%, escurecendo progressivamente até vermelho bem escuro perto de 100%.

### 3.6 🔀 Matriz de rolagem (roll-rate)

Mostra a probabilidade de um contrato migrar de uma faixa de atraso para outra de um mês para o seguinte — por exemplo, qual a chance de um contrato que está com 1 a 30 dias de atraso piorar para 31 a 60 dias no mês seguinte.

**Como é calculado**: reconstruindo o histórico mês a mês (mesma técnica da curva de maturação), o Painel identifica em qual faixa de atraso cada contrato estava em cada mês e observa a faixa em que ele estava no mês seguinte. Todas essas transições, de todo o histórico disponível, são agrupadas: para cada faixa de origem, calcula-se o percentual de contratos que foi para cada faixa de destino.

**Visualização**: mapa de calor com a faixa de origem nas linhas e a faixa de destino nas colunas — a diagonal mostra quem ficou estável, e as células acima/abaixo mostram piora/melhora.

### 3.7 💰 Rentabilidade

| Indicador | Fórmula |
|---|---|
| **Yield médio mensal** | Taxa de juros mensal contratada, ponderada pelo saldo devedor atual de cada contrato (contratos com mais saldo em aberto pesam mais na média) |
| **Yield médio anual** | Mesma lógica, usando a taxa anual contratada |
| **Receita total** | Soma da receita total apurada nos contratos do recorte |
| **Receita originação** | Soma da parcela de receita atribuída à originação do crédito |
| **Receita tesouraria** | Soma da parcela de receita atribuída à tesouraria |

### 3.8 🎯 Concentração de carteira (cliente)

Mede o quanto a carteira depende de poucos clientes grandes, usando o Índice Herfindahl-Hirschman (HHI), uma métrica clássica de concentração.

> **Atenção de população**: a base usada aqui é "contratos com saldo devedor em aberto" (`saldo_atual > 0`), o que **inclui contratos em write-off** (eles continuam com parcelas não pagas, logo `saldo_atual > 0`). Não é o mesmo recorte de "Carteira em aberto" usado na seção 3.1 e no resto do Painel, que exclui write-off explicitamente.

| Indicador | Fórmula |
|---|---|
| **HHI** | Soma do quadrado da participação percentual de cada cliente (agrupado por CPF/CNPJ, campo `taxId`) no saldo devedor total da base acima (inclui write-off). Varia de perto de 0 (carteira muito pulverizada) a 10.000 (um único cliente concentra tudo) |
| **% saldo no top 10 clientes** | Soma da participação percentual dos 10 clientes com maior saldo devedor, sobre a mesma base |
| **Top 15 clientes** (gráfico/tabela) | Lista dos 15 clientes com maior participação individual no saldo devedor |

### 3.9 🧑‍💼 Perfil de risco do cliente (CCB)

Mostra o **NPL 90+** (sobre o saldo devedor — mesma metodologia da seção 3.3, não confundir com a "Inadimplência" de saldo total da seção 1.5) segmentado por três dimensões do cliente: **rating**, **estado (UF)** e **setor de atividade (CNAE)**. Só cobre contratos CCB (que têm chave exata com os dados cadastrais); a base combina os contratos com `client_data` e **exclui write-off** (só entra `max_delay <= 360`), para ficar comparável ao "NPL por faixa de atraso" da seção 3.3.

> **% NPL90+ por categoria = (saldo devedor dos contratos daquela categoria com atraso ≥ 90 dias) ÷ (saldo devedor total da categoria, sem write-off) × 100**

Campos usados: `rating_v4`, `state` e `cnaeFiltered` (de `client_data`) para as três dimensões; `max_delay` e `saldo_atual` (de `installments`) para o cálculo do NPL.

Fecha com um bloco de **Restrições cadastrais**, mostrando o percentual de clientes com registro de: protesto, restritivo nacional, PEP (pessoa politicamente exposta), mandado de prisão e trabalho escravo — sinalizações vindas do processo de análise cadastral.

---

## 4. Painel Executivo

Uma visão consolidada e executiva da carteira, com indicadores de negócio, risco e financeiros, filtrável por **Produto** (seleção múltipla: CCB, CPR ou os dois juntos), **Carteira** (Em aberto / WriteOff / Total) e **Período** (Início/Fim, pela data de originação). A segmentação "por categoria" (as linhas/colunas abaixo do Total em todos os indicadores, tabelas e gráficos) depende do Produto escolhido: com **só CCB**, os contratos são segmentados em "App" e "Crédito Produtor" (linhas de crédito); com **só CPR**, pelos tipos de produto CPR cadastrados no sistema (essa lista se atualiza automaticamente se surgir um novo tipo); com **CCB e CPR juntos**, a segmentação passa a ser **por produto** ("CCB" e "CPR"), não por linha de crédito — por exemplo, abaixo do "Total Concedido" aparecem os valores de CCB e de CPR. Sempre que este documento fala em "categoria" na seção 4, leia: App/Crédito Produtor (só CCB), tipos de CPR (só CPR) ou CCB/CPR (os dois).

**Estrutura atual da aba** (reformulada): `1. Visão Geral da Carteira` → `2. Distribuição por Produto` → `3. Indicadores de Risco`. A antiga seção "Análise por Safra" e a tabela "Indicadores Financeiros" **foram removidas da tela** (os indicadores financeiros, como a PDD de 50%, continuam existindo apenas no Simulador da Análise de Risco — seção 5.2).

**Quais filtros afetam o quê**: o filtro **Produto** e o **Período** valem para a aba inteira. O filtro **Carteira** (Em aberto / WriteOff / Total) afeta só os indicadores de volume das seções 1 e 2 e a tabela/gráfico de "Indicadores de Risco" (inadimplência canônica); **NPL 90, NPL 90 + WO e toda a parte nova da seção 3 (faixas de atraso, NPL 90/30, evolução do NPL 90, PDD) ignoram o filtro Carteira** e sempre usam a carteira completa do Produto escolhido (em aberto + write-off), porque precisam do write-off dentro da base.

**Download em PDF**: o botão "📄 Download", logo abaixo dos filtros, gera um relatório em PDF sob demanda (só quando clicado, com uma barra de progresso, com a % concluída, abaixo do botão, que permanece na tela). Ao terminar, aparece o botão "⬇️ Baixar PDF", que baixa o arquivo com um clique; ele some se algum filtro ou seleção mudar, pois o arquivo ficaria desatualizado. (O navegador só inicia um download a partir de um clique do usuário, por isso são dois botões.) (A4 paisagem, em português e formato numérico brasileiro) com os resultados **atuais** do painel, para diretoria e investidores: capa com os parâmetros (Produto, Carteira, Período e as seleções de linha de crédito/tipo de NPL da evolução e de fundo do PDD), seções 1 a 3 completas (cards, gráficos e tabelas, inclusive o detalhe por faixa de cada régua da PDD) e uma página de Notas Metodológicas. Os números são os mesmos da tela; só mudam o formato (1.234,56) e o fato de os gráficos serem desenhados com matplotlib. Código em `app/crud/painel_executivo/pdf_report.py`; depende de `reportlab` e `matplotlib` (no `requirements.txt`).

### 4.1 Tópico 1 — Visão Geral da Carteira (10 KPIs)

Cada KPI mostra o valor Total em destaque e, logo abaixo, o valor de cada categoria (App/Crédito Produtor no CCB; tipos de produto no CPR).

| KPI | Fórmula | Campos |
|---|---|---|
| **Total Concedido** | Soma do valor de principal dos contratos originais do recorte (nunca conta renegociação como novo dinheiro concedido) | `principalAmount` |
| **Qtd Contratos Ativos** | Contagem de contratos-raiz que ainda não foram 100% quitados (têm ao menos uma parcela em aberto) | `installments.paid` |
| **Qtd Contratos Total** | Nº de contratos-raiz do recorte, ativos e quitados (renegociações ficam dentro do contrato-raiz) | `operationCode` |
| **Taxa Juros Média** | Taxa de juros mensal contratada, ponderada pelo valor de principal de cada contrato | `monthlyRate`, `principalAmount` |
| **Ticket Médio** | Total Concedido ÷ nº de contratos (média simples do principal por contrato) | `principalAmount` |
| **Total Concedido da Carteira Ativa** | Soma do principal (`principalAmount` da parcela) só das parcelas ainda **em aberto** dos contratos ativos — a parte de principal do que falta receber, sem juros. É o mesmo conjunto de parcelas do "Saldo da Carteira Ativa", contando só o principal; **Saldo − Total Concedido da Carteira Ativa = juros a receber**. (Não é o valor originalmente concedido dos contratos ativos: a parte já amortizada fica de fora.) | `installments.principalAmount`, `installments.paid` |
| **Saldo da Carteira Ativa** | Soma do valor cheio (`amount`: principal + juros) das parcelas ainda em aberto dos contratos ativos — o que falta receber, vencido e a vencer. É o "saldo devedor" usado como base do NPL | `installments.amount`, `installments.paid` |
| **Total Recebido** | Soma do valor efetivamente pago das parcelas já pagas dos contratos do recorte (principal + juros recebidos até hoje) | `installments.paidAmount`, `installments.paid` |
| **NPL 90** | **Saldo devedor** dos contratos com atraso de 90 a 360 dias ÷ saldo devedor total da carteira **sem** write-off (atraso ≤ 360). Nível de contrato: se o maior atraso do contrato é ≥ 90 dias, o saldo em aberto inteiro dele entra no numerador. Mesma fórmula do "NPL por faixa de atraso" da aba Análise da Carteira (seção 3.3); **ignora o filtro Carteira** | `installments.amount`, `installments.delay`, `installments.paid` |
| **NPL 90 + WO** | Igual ao NPL 90, mas o saldo em write-off (atraso > 360) entra no numerador **e** no denominador: (saldo com atraso de 90 a 360 dias + saldo em write-off) ÷ saldo devedor total incluindo write-off; **ignora o filtro Carteira** | `installments.amount`, `installments.delay` |

> **Atenção (NPL x Inadimplência)**: o NPL 90 e o NPL 90 + WO deste painel seguem a regra de NPL da seção 1.5 (denominador = **saldo devedor**). Já a "Inadimplência / % da Carteira" (denominador = saldo TOTAL contratado, seção 1.3) continua existindo na seção 3, no gráfico e na tabela "Indicadores de Risco". As duas coexistem na mesma aba — não são o mesmo número.

**Gráficos deste tópico**: quatro gráficos de rosca (donut) lado a lado, comparando categorias (linhas de crédito, ou CCB x CPR quando os dois produtos estão selecionados): **Total Recebido** (mesmo valor do card, por categoria); **Divisão de Contratos Ativos**; **Saldo da Carteira Ativa** (idem); e **Total Concedido da Carteira Ativa** (idem). Todos obedecem ao filtro Carteira.

### 4.2 Tópico 2 — Distribuição por Produto

Uma tabela com **os mesmos 10 indicadores da seção 4.1** (mesmas fórmulas), exibidos lado a lado para o Total e para cada categoria de produto (App/Crédito Produtor no CCB; tipos de produto no CPR). Contratos sem categoria (ex.: CCB sem cadastro em `client_data`) entram só no Total.

Com **CCB e CPR selecionados juntos**, a tabela mantém as colunas **Total**, **Valor CCB** e **Valor CPR** (divisão por produto) e **acrescenta uma coluna para cada linha de crédito** (App, Crédito Produtor e os tipos de CPR) — ou seja, as mesmas colunas que apareceriam se o usuário escolhesse "CCB" e "CPR" separadamente, lado a lado.

### 4.3 Tópico 3 — Indicadores de Risco

Respeita Produto e Período; ignora Carteira (exceto no gráfico e na tabela "Indicadores de Risco" logo abaixo, que seguem o filtro). Composto, na ordem da tela, por:

1. **Gráfico "Indicadores de Risco por Carteira (%)"**: barras com o % da carteira em cada faixa de atraso (FPD, 15+, 30+, 60+, 90+ dias), comparando o Total com cada categoria. Fórmula canônica da seção 1.3 (saldo em aberto ÷ saldo TOTAL contratado) — é "Inadimplência", não "NPL". *(Segue o filtro Carteira.)*

2. **Tabela "Indicadores de Risco"**: as mesmas faixas (FPD 90d, 15+, 30+, 60+, 90+), com o saldo em atraso em R$ e o % da carteira (fórmula canônica da 1.3), no Total e por categoria. *(Segue o filtro Carteira.)*

3. **Faixas de atraso** (gráfico + tabela): toda a carteira com saldo em aberto (inclui write-off) distribuída pela faixa do **maior atraso do contrato** — se o contrato tem parcelas com atrasos diferentes, o contrato inteiro cai na faixa da pior. Faixas: `00 - A vencer` (atraso 0), `01 - 1 a 7 dias`, `02 - 8 a 15`, `03 - 16 a 30`, `04 - 31 a 60`, `05 - 61 a 90`, `06 - 91 a 180`, `07 - 181 a 360`, `08 - 361 a 720`, `09 - Acima de 720 dias` (as faixas 08 e 09 são write-off, atraso > 360 — igual ao resto do Painel; a faixa 07, até 360 dias inclusive, ainda é carteira viva). Colunas da tabela: **Principal** (soma do `principalAmount` das parcelas em aberto), **Amount** (soma do `amount` — valor cheio — das parcelas em aberto), **Princ. de cada produto** (Principal separado por categoria: App, Crédito Produtor, ou tipos de CPR; "Sem categoria" se houver), **Qtde** (nº de contratos) e **%** (Principal da faixa ÷ Principal total). O gráfico é de barras empilhadas por faixa, com o Amount dividido por produto. Campos: `installments.amount`, `principalAmount`, `paid`, `delay`.

4. **Inadimplência — NPL 90 e NPL 30**: quatro cards (NPL 90, NPL 30, NPL 90 c/ WO, NPL 30 c/ WO) e uma tabela por linha de crédito. **É NPL na definição da seção 1.5 (denominador = saldo devedor).** Fórmulas, em nível de contrato: `NPL N` (sem WO) = saldo com atraso de N a 360 dias ÷ saldo devedor sem write-off (atraso ≤ 360); `NPL N c/ WO` = (saldo com atraso de N a 360 dias + saldo em write-off) ÷ saldo devedor total incluindo write-off. A tabela tem uma linha para **cada linha de crédito dos produtos selecionados** (App, Crédito Produtor, tipos de CPR; "Sem categoria" se houver), os subtotais **Total CCB** e **Total CPR** (quando os dois produtos estão selecionados) e o **Total** geral. Colunas: **Saldo (amount)** (inclui write-off), **Atraso 30-360d**, **Atraso 90-360d**, **WO > 360d** (saldos em R$), **NPL 30**, **NPL 90**, **NPL 30 c/ WO**, **NPL 90 c/ WO** (%). A linha Total do NPL 90 é o mesmo número do KPI "NPL 90" da seção 4.1.

5. **Evolução do NPL 90 — desde Jan/25**: gráfico de linhas com o NPL 90 **sem WO** e **c/ WO** no fim de cada mês desde janeiro/2025 (mesma fórmula do item 4, aplicada ao saldo em aberto e ao atraso máximo de cada contrato naquela data). O histórico é reconstruído de `installments.dueDate`, `paymentDate` e `paid`, considerando a vigência das renegociações (mesma reconstrução usada na curva de maturação da Análise da Carteira); o último ponto é o dia de hoje e usa os valores atuais — bate exatamente com o KPI "NPL 90" e com o card do item 4. Dois filtros multiselect definem as linhas do gráfico: **Linha de crédito** ("Total" = o recorte inteiro dos produtos selecionados, mais as linhas de crédito dos produtos selecionados; default "Total") e **Tipo de NPL** ("NPL 90 s/ WO" e/ou "NPL 90 c/ WO"; default os dois). Cada combinação linha de crédito × tipo vira uma linha do gráfico — por exemplo, App + Crédito Produtor × os dois tipos = 4 linhas. Com várias linhas, a cor identifica a linha de crédito e o traço (cheio = s/ WO, tracejado = c/ WO) identifica o tipo; os rótulos de valor só aparecem com até 2 linhas (use o hover nas demais).

6. **PDD (por fundo)**: provisão calculada com a **régua de cada fundo**, conforme a aba "Regras PDD" da planilha "PDD por Rating" (22/10/2026). O fundo de um contrato é o `portfolio` da sua última parcela (seção do filtro Fundo, abaixo) e define a régua e a **unidade em que o maior atraso é medido**. Em todas, o % da faixa vale para **todo o saldo em aberto** (`amount` das parcelas não pagas, inclusive vincendas) da unidade, e Provisão = Saldo × % PDD. Contrato sem `taxId` conta como devedor próprio.

   | Régua | Fundos | Unidade do maior atraso | Faixas (maior atraso em dias → % PDD) |
   |---|---|---|---|
   | **Ghia** | Ghia | Devedor (`taxId`), considerando só os contratos dele **na Ghia** | 0 → 1,15% · 1–15 → 1,15% · 16–30 → 1,15% · 31–60 → 1,15% · 61–90 → 54,10% · 91–120 → 59,25% · 121–150 → 69,71% · 151–180 → 86,16% · 181–210 → 92,81% · 211–240 → 97,58% · 241–270 → 97,72% · 271–300 → 97,72% · 301–330 → 98,84% · >330 → 100% |
   | **Kanastra** | Kanastra | Cliente (`taxId`), considerando **toda a CCB, de todos os fundos** (e não só o Kanastra) | até 14 → 0% · 15–30 → 15% · 31–45 → 22,5% · 46–60 → 30% · 61–75 → 60% · >75 → 100% |
   | **Oikos** | Oikos e Oikos Warehouse | Contrato | até 60 → 0% · 61–90 → 15% · 91–120 → 25,83% · 121–150 → 50,83% · 151–180 → 75,83% · ≥181 → 100% |
   | **Res. CMN 2.682** | Todos os demais (Liqi, Tesouraria, Nagro, Leaf, Rivool, CRA etc., e "Sem fundo") | Contrato | AA 0 → 0% · A 1–30 → 0,5% · B 31–60 → 1% · C 61–90 → 3% · D 91–120 → 10% · E 121–180 → 30% · F 181–240 → 50% · G 241–360 → 70% · H >360 → 100% |

   A PDD de cada contrato é calculada sobre a **base completa** (todos os produtos e fundos, no período escolhido) — por isso o atraso do devedor na Ghia e o do cliente na CCB (Kanastra) não dependem dos filtros de Produto e Fundo da tela; esses filtros apenas escolhem quais contratos entram na soma. (Para um contrato CPR do Kanastra, vale o maior entre o atraso do próprio contrato e o do cliente na CCB.)

   **Apresentação**: uma tabela **por fundo** (Régua, Contratos, Saldo, % PDD, Provisão, mais a linha Total), o card "PDD total" com o % do saldo em aberto, e abas com o **detalhe por faixa** de cada régua presente na seleção (Contratos, Devedores, Saldo, % PDD, Provisão).

   **Filtro Fundo** (multiselect, só nesta PDD; default = todos): escolhe quais fundos entram; os valores são **somados** (Oikos + Ghia = uma tabela só). O **fundo** de um contrato é o `portfolio` da sua **última parcela** (a de maior vencimento; empate → maior `installmentNumber`; a parcela sintética nº 25 do CCB é ignorada), sem agrupar nomes no filtro (Oikos e Oikos Warehouse aparecem separados, mas usam a mesma régua); contrato sem portfolio vira "Sem fundo". Como `portfolio` é atributo da parcela e cerca de 8% dos contratos têm parcelas em mais de um portfolio, essa regra dá um único fundo a cada contrato, de modo que a soma dos fundos fecha o total. Campo: `installments.portfolio`.

   **Conferência com a planilha**: as quatro réguas, com os limites de faixa acima, reproduzem exatamente o "% PDD" e a PDD total (R$ 101,46 mi) de todos os 4.176 contratos da aba "Detalhe contratos". Diferenças esperadas em relação aos números da planilha: o Painel exclui o produto CPR "Antecipação Recebiveis" (a planilha tem 1 contrato dele) e atribui um único fundo por contrato (a planilha, na aba "Resumo", conta contratos com parcelas em mais de um fundo nos dois).

> **Observação sobre a PDD**: a PDD do Painel Executivo usa as réguas por fundo acima (Ghia, Kanastra, Oikos e Res. CMN 2.682). A regra antiga de "50% do saldo de principal dos contratos com atraso ≥ 90 dias" **não aparece mais no Painel Executivo**; ela só é usada nos indicadores financeiros do Simulador da Análise de Risco (seção 5.2).

---

## 5. Análise de Risco

Esta aba foi criada para apoiar decisões de política de crédito, identificando **quais variáveis (rating, estado, setor, renda, tempo de atividade, ticket, categoria de produto) mais explicam a inadimplência** da carteira. Usa a mesma base de dados e as mesmas fórmulas do Painel Executivo — inclusive a fórmula canônica de "% da Carteira" (seção 1.3, denominador = saldo TOTAL contratado) — para garantir que os números sejam sempre consistentes entre as duas abas. Em toda esta aba o Painel chama esse percentual de **"Inadimplência"**, nunca de "NPL" (ver seção 1.5) — se o usuário perguntar sobre "NPL por variável", explique que o equivalente correto aqui é a "Inadimplência por variável", calculada sobre o saldo total, não sobre o saldo devedor.

Os filtros compartilhados pelas duas sub-abas são: **Carteira** (Em aberto/WriteOff/Total), **Produto** (CCB e/ou CPR, pode ser os dois juntos), subfiltros de tipo (CCB e CPR), **Mínimo de contratos por categoria** (esconde categorias/combinações com poucos contratos, para não distorcer a leitura com grupos muito pequenos — o valor padrão do filtro é 1, ou seja, por padrão nada é escondido) e **Período** (Início/Fim).

As variáveis analisadas em toda a aba são: Categoria (App/Crédito Produtor ou tipo de CPR), Rating, UF, Setor (CNAE), Faixa de Renda, Tempo de Atividade e Faixa de Ticket (esta última é um corte de risco de crédito clássico por valor do contrato).

### 5.1 Sub-aba Análise de variáveis

#### 5.1.1 "Quais variáveis mais separam bom de mau pagador?" (ranking de dispersão)

Este é o indicador criativo central da aba: mede o **poder discriminante** de cada variável, ou seja, o quanto ela ajuda a distinguir contratos de baixo e alto risco.

> **Dispersão de uma variável = (maior % de Inadimplência 90+ entre suas categorias) − (menor % de Inadimplência 90+ entre suas categorias)**

"% de Inadimplência 90+" aqui é sempre a fórmula canônica da seção 1.3 (saldo em aberto ÷ saldo TOTAL contratado do grupo), calculada por categoria, **depois** de descartar categorias com menos contratos que o "Mínimo de contratos por categoria". Se uma variável separa bem bons e maus pagadores (por exemplo, um estado com inadimplência de 2% e outro com 40%), sua dispersão é alta — é uma boa candidata para orientar decisões de política de crédito, como restringir ou precificar diferente a pior categoria. Se todas as categorias de uma variável têm inadimplência parecida, a variável pouco importa para diferenciar risco nesse recorte. O ranking mostra as variáveis ordenadas da mais para a menos discriminante, junto com qual é a pior categoria de cada uma e seu percentual de inadimplência.

#### 5.1.2 "Inadimplência por variável" (exploração individual)

Ao escolher uma variável (por exemplo, "UF"), o Painel mostra, para cada categoria dessa variável:

- **% de Inadimplência 90+** (fórmula canônica da seção 1.3 — saldo em aberto ÷ saldo TOTAL contratado, calculada dentro daquele grupo).
- **Número de contratos**, **volume concedido** e **saldo devedor** do grupo.

Duas visualizações complementares:

- **Gráfico de barras**: ranking das categorias por % de Inadimplência, do maior para o menor risco.
- **Gráfico de bolhas "Risco x Exposição"**: cada bolha é uma categoria, com a posição horizontal mostrando o % de Inadimplência, a posição vertical mostrando o saldo devedor (exposição em R$) e o tamanho da bolha mostrando o número de contratos. Duas linhas de referência (a média ponderada de inadimplência e a mediana de saldo devedor) dividem o gráfico em quadrantes — o quadrante superior direito (inadimplência alta e saldo devedor alto) concentra as categorias mais urgentes, pois já carregam risco absoluto relevante na carteira, não só percentual.

#### 5.1.3 Cruzamento de duas variáveis

Permite escolher duas variáveis (por exemplo, UF e Setor) e ver, em um mapa de calor, o % de Inadimplência 90+ (fórmula canônica, saldo em aberto ÷ saldo TOTAL contratado da combinação) de cada combinação das duas — útil para identificar interações específicas (por exemplo, um setor que só é problemático em determinado estado). Passar o mouse sobre uma célula mostra as duas categorias, o % de inadimplência e o **número de contratos** daquela combinação específica.

> **Atenção — "Mínimo de contratos por categoria" aqui é aplicado por CÉLULA, não pela variável inteira.** No ranking (5.1.1) e na exploração individual (5.1.2), o filtro descarta uma categoria só se o TOTAL de contratos dela (somando todas as outras variáveis) for menor que o mínimo. Já no cruzamento, o filtro é aplicado a cada combinação das duas variáveis separadamente — então uma categoria com bastante volume pode "sumir" quase inteira do mapa de calor se esse volume estiver espalhado entre muitas combinações pequenas, sobrando só a(s) combinação(ões) que individualmente atingem o mínimo. Isso significa que o mapa de cruzamento pode mostrar um número bem diferente (e uma amostra bem menor) do que o número agregado da mesma categoria no ranking ou na exploração individual — **não é uma inconsistência, é a granularidade do filtro mudando**. Ao responder perguntas comparando um valor do cruzamento com um valor do ranking/exploração individual para a mesma categoria, sempre explique essa diferença de filtro.

A escala de cor do mapa de calor é fixa (não se ajusta ao filtro/cruzamento selecionado): verde abaixo de 25%, amarelo a partir de 25%, laranja a partir de 50%, vermelho pleno em 100%.

### 5.2 Sub-aba Simulador

O Simulador responde à pergunta: **"o que aconteceria com a carteira se decidíssemos excluir um determinado perfil de cliente?"** — por exemplo, simular a retirada de todos os contratos de um estado com um setor (CNAE) específico.

**Como funciona**: o usuário escolhe um ou dois critérios de exclusão (cada um é uma variável + os valores a excluir, por exemplo "UF = RN"), e opcionalmente combina os dois critérios com lógica "E" (só exclui quem bate as duas condições ao mesmo tempo) ou "OU" (exclui quem bate qualquer uma das duas). Isso divide a carteira filtrada em dois grupos: o **segmento excluído** e a **carteira simulada** (tudo, exceto o segmento).

Os indicadores comparativos usam as fórmulas de inadimplência canônica e os indicadores financeiros do Simulador (incluindo a PDD de 50% do saldo de principal com atraso ≥ 90 dias, que não existe mais no Painel Executivo — veja a observação da seção 4.3), calculadas três vezes — uma para a carteira **Atual** (com o segmento), uma para a carteira **Simulada** (sem o segmento) e uma só para o **Segmento** excluído:

- Total Concedido, Contratos Ativos, Ticket Médio, Taxa Juros Média
- FPD (90d), Inadimplência 90d, Cobertura PDD, Margem Financeira Estimada

Como em todo o Painel Executivo e Análise de Risco, "FPD (90d)" e "Inadimplência 90d" aqui usam a fórmula canônica de "% da Carteira" — saldo em aberto ÷ saldo TOTAL contratado do grupo (Atual, Simulada ou Segmento) — não o NPL sobre saldo devedor da aba "Análise da Carteira" (seção 1.5).

Cada KPI mostra o valor simulado em destaque e a variação em relação ao valor atual, permitindo avaliar rapidamente se excluir aquele perfil reduziria a inadimplência e o quanto isso custaria em volume/margem. Um bloco final resume o que há dentro do segmento excluído (número de contratos, % da carteira, volume concedido e inadimplência do segmento).

---

## 6. Monitoramento de Clientes

Esta aba acompanha a evolução do perfil de risco de cada cliente ao longo do tempo, com base em consultas periódicas feitas pela Nagro (rating, score, dívidas e protestos externos via Boa Vista, exposição de crédito no mercado). O objetivo é sinalizar antecipadamente contratos com risco crescente de inadimplência, antes que o atraso efetivamente aconteça.

### 6.1 Como funciona o pareamento "atual x anterior"

Cada contrato pode ter várias consultas ao longo do tempo (uma nova linha a cada reconsulta). Para cada cliente/contrato, o Painel compara sempre a **consulta mais recente** com a **consulta imediatamente anterior**, classificando cada indicador de risco em: **Piorou**, **Melhorou** ou **Estável** (variações muito pequenas, abaixo de 1%, são tratadas como estáveis).

Os indicadores usados nessa comparação são: dívida em atraso (overdue), prejuízo (loss), dívidas via Boa Vista, protestos via Boa Vista, protestos gerais e o rating do cliente. A exposição de crédito no mercado (`credit_portfolio`) é tratada separadamente, como um sinal neutro de contexto (aumentou/diminuiu), não como algo necessariamente "ruim".

**Número de indicadores piorando**: quantos desses 6 indicadores de risco pioraram entre a consulta mais recente e a anterior — é a base do critério de priorização (watchlist) e dos alertas da tela.

### 6.2 Definição de "Status da carteira" (filtro)

- **Carteira Inadimplente**: contrato em aberto (não quitado, e ainda não em write-off) **e** com algum atraso registrado.
- **Carteira Adimplente**: todo o restante — contratos já quitados, em write-off, ou em aberto mas sem atraso no momento.

### 6.3 KPIs de cobertura e alertas

| Indicador | Fórmula |
|---|---|
| **Monitorados** | Número de contratos com ao menos uma consulta dentro do período de análise (filtro 1) |
| **Com histórico (2+)** | Quantos desses já têm 2 ou mais consultas registradas (permitindo comparação "atual x anterior") |
| **1ª consulta** | Contratos monitorados que ainda têm só uma consulta (sem histórico para comparar) |
| **Em atenção** | Contratos com pelo menos 1 dos 6 indicadores de risco piorando desde a última consulta |
| **Crítico (3+)** | Contratos com 3 ou mais indicadores piorando ao mesmo tempo |
| **Óbito reportado** | Contratos com registro de óbito do titular na última consulta |

Cada um desses indicadores é exibido junto com o valor de referência do **filtro 2** (período de referência), permitindo visualizar a variação percentual entre os dois períodos (ver seção 6.6).

### 6.4 Migração de rating e Exposição de crédito

- **Migração de rating**: quantos contratos melhoraram, pioraram ou mantiveram o rating entre a consulta mais recente e a anterior, com um mapa de calor mostrando a matriz completa de transição (de qual rating para qual rating).
- **Exposição de crédito no mercado**: quantos contratos tiveram aumento, diminuição ou estabilidade no total de crédito que o cliente possui no mercado (não só com a Nagro) — um sinal de contexto sobre o endividamento geral do cliente.

### 6.5 Contratos em atenção (watchlist)

Lista de priorização para acompanhamento comercial/cobrança, com os seguintes critérios:

- Só entram contratos com histórico comparável (2 ou mais consultas).
- Só entram contratos monitorados dentro do período de análise (filtro 1).
- Critério de entrada: pelo menos 1 dos 6 indicadores de risco piorando desde a última consulta.
- **Ordenação**: primeiro pelos contratos com mais indicadores piorando ao mesmo tempo (maior severidade primeiro); em caso de empate, pelo maior valor originado (maior exposição primeiro).

A tabela final mostra nome do cliente, contrato, produto, valor originado, se já está em default interno, quantos e quais indicadores pioraram, além dos valores de rating, atraso e exposição na consulta atual e na anterior. Pode ser baixada em CSV.

### 6.6 Períodos de comparação (Filtro 1 x Filtro 2)

Todos os indicadores de "cobertura", "migração de rating" e "exposição de crédito" são calculados duas vezes, para dois períodos escolhidos pelo usuário:

- **Filtro 1 (análise)**: define o valor "atual" exibido em destaque.
- **Filtro 2 (referência)**: define o valor de comparação, mostrado como referência abaixo de cada métrica (e usado para calcular a variação percentual).

Por padrão, o filtro 1 cobre os últimos 7 dias disponíveis, e o filtro 2 cobre os 7 dias imediatamente anteriores a esse período — uma comparação "esta semana x semana passada". Em cada período, entram os contratos com pelo menos uma consulta dentro do intervalo escolhido; o valor usado para cada contrato é o histórico acumulado até o fim daquele período (mesmo que a consulta mais recente registrada tenha sido feita antes do início do período). Os alertas (Em atenção/Crítico/Óbito), o mapa de migração de rating, o gráfico de exposição e a watchlist usam sempre o **filtro 1** — o filtro 2 serve apenas como referência de comparação para as contagens.

### 6.7 Consulta individual — trajetória do cliente

Permite selecionar um cliente/contrato específico e visualizar toda a sua trajetória de consultas ao longo do tempo (até o fim do período de análise escolhido): evolução do score e rating em um gráfico, e evolução das métricas de dívida/atraso/exposição em outro, além da tabela completa do histórico de consultas.

---

## 7. Glossário rápido

| Termo | Significado |
|---|---|
| **Raiz / contrato raiz** | O contrato original de onde partiu a relação de crédito, antes de qualquer renegociação. Renegociações são sempre remapeadas para a raiz nos cálculos. |
| **Write-off (WO = 360)** | Contrato com atraso MAIOR que 360 dias em alguma parcela (`max_delay > 360`) — considerado baixado a prejuízo na maior parte dos cálculos do Painel. Atenção: o indicador "Write-off (contratos)" da Análise da Carteira usa um flag bruto (`writeOff`) independente desse corte de 360 dias — ver seção 3.4. |
| **NPL (Non-Performing Loan)** | Termo usado SÓ na aba "Análise da Carteira" (seções 3.3 e 3.9): contrato em atraso além de um corte de dias (15, 30, 60 ou 90), calculado sobre o **saldo devedor** (não sobre o saldo total contratado). Um contrato inteiro entra no NPL de uma faixa se qualquer parcela em aberto atingir aquele atraso. Ver a distinção completa com "Inadimplência" na seção 1.5 — **não é sinônimo de "% da Carteira"**. |
| **Inadimplência / "% da Carteira"** | Termo usado no Painel Executivo e em toda a Análise de Risco: saldo das parcelas em aberto de contratos com atraso ≥ 90 dias (ou outro corte), dividido pelo **saldo TOTAL contratado** (pago + em aberto) do recorte — denominador diferente do NPL. Ver seção 1.3 (fórmula) e 1.5 (comparação lado a lado com o NPL). |
| **PDD** | Provisão para Devedores Duvidosos. No Painel Executivo: régua de cada fundo (Ghia, Kanastra, Oikos; Res. CMN 2.682 nos demais) aplicada sobre todo o saldo em aberto (seção 4.3, item 6). No Simulador da Análise de Risco: 50% do saldo de PRINCIPAL (não o valor cheio da parcela) em contratos com atraso ≥ 90 dias (seção 5.2). |
| **Safra** | Grupo de contratos originados no mesmo mês, usado para acompanhar a maturação da inadimplência ao longo do tempo de vida do contrato. Na "Curva de maturação por safra" (3.5), o percentual de cada célula usa como denominador o valor originado da safra (fixo) — um terceiro tipo de base, diferente do NPL e da Inadimplência canônica. |
| **HHI** | Índice Herfindahl-Hirschman — mede a concentração da carteira em poucos clientes grandes, agrupando por CPF/CNPJ (`taxId`). Na Análise da Carteira (3.8), a base inclui contratos em write-off (usa `saldo_atual > 0`, não o recorte "Carteira em aberto"). |
| **PSI (Population Stability Index)** | Mede o quanto uma distribuição (de score ou de rating) se deslocou em relação a uma base de referência. Existem duas versões no Painel — ver seção 2 para a diferença entre elas. |
| **KS (Kolmogorov-Smirnov)** | Na sub-aba Relatório, mede a capacidade do modelo de separar bons e maus pagadores. Na sub-aba Estabilidade Rating (onde é chamado de KS1), mede o deslocamento máximo entre a distribuição acumulada de ratings de um mês e a da safra de referência. |
| **Categoria** | Segunda camada de segmentação usada no Painel Executivo e na Análise de Risco: "App"/"Crédito Produtor" para CCB, ou o tipo de produto CPR (dinâmico, conforme cadastro). |
| **Mínimo de contratos por categoria** | Filtro da Análise de Risco que descarta categorias (ou, no cruzamento de duas variáveis, combinações de categorias) com poucos contratos. Aplicado por variável inteira no ranking/exploração individual, mas por CÉLULA no cruzamento — ver o alerta na seção 5.1.3. Padrão: 1 (não esconde nada). |
