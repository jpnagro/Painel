# Documentação de Indicadores e Gráficos — Painel Nagro Crédito

Este documento explica, aba por aba, o que cada indicador e gráfico do Painel mostra e **exatamente como ele é calculado**. O objetivo é dar transparência total sobre a metodologia por trás dos números — de onde vêm os dados, quais filtros afetam cada cálculo e qual fórmula está por trás de cada métrica.

**Última atualização:** 26/08/2026

---

## Sumário

1. [Conceitos comuns a várias abas](#1-conceitos-comuns-a-várias-abas)
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

Antes de entrar em cada aba, é importante entender quatro conceitos que se repetem em praticamente todo o Painel. Eles garantem que os números batam entre abas diferentes — não são regras isoladas de uma única tela.

### 1.1 Consolidação de renegociações (a "raiz" do contrato)

Quando um contrato é renegociado, o sistema não trata a renegociação como um empréstimo novo — ela é uma reestruturação do saldo de um contrato que já existe. Por isso, o Painel sempre remapeia toda renegociação (inclusive uma renegociação de outra renegociação) para o código do contrato **original** (chamado de "raiz"), usando o campo `externalId` que cada renegociação carrega apontando para o contrato de origem.

Na prática, isso significa que:

- O **valor originado/concedido** de um contrato só é contado uma vez (no contrato raiz), mesmo que ele tenha sido renegociado várias vezes.
- O **histórico de pagamento** de um cliente (raiz + todas as renegociações) fica unificado sob uma única chave, permitindo calcular corretamente saldo devedor, atraso e status atual.
- Filtros de produto, período e portfólio decidem se um contrato entra ou sai da base sempre olhando para a raiz — se a raiz atende ao filtro, a raiz e todas as suas renegociações entram juntas.

### 1.2 Definição de write-off (baixa a prejuízo)

O corte oficial de write-off usado nas abas "Análise da Carteira", "Painel Executivo", "Análise de Risco" e "Monitoramento de Clientes" é:

> **Write-off = contrato com atraso máximo (`max_delay`) igual ou superior a 360 dias em alguma parcela em aberto.**

Esse critério (apelidado de `WO = 360` no código) é usado de forma consistente para separar "Carteira em aberto" de "WriteOff" nessas quatro abas. A única exceção documentada está na aba "Análise da Carteira", no indicador "Write-off (contratos)" das Taxas-chave, que usa um flag bruto do banco (`writeOff`) em vez do corte de 360 dias — isso está detalhado na seção 3.7.

### 1.3 A fórmula canônica de "% da Carteira" (NPL 90+)

Esta é a fórmula mais reaproveitada do Painel — aparece no Painel Executivo e em toda a Análise de Risco (inclusive no Simulador), sempre com o mesmo resultado para o mesmo recorte de dados:

> **% da Carteira (NPL 90+) = (soma do valor total das parcelas em aberto dos contratos com atraso ≥ 90 dias) ÷ (soma do valor total de todas as parcelas do recorte, pagas e em aberto) × 100**

Em outras palavras: de tudo o que foi contratado (parcelas cheias, pagas ou não) dentro do filtro selecionado, que fatia pertence a contratos que já acumulam 90 dias ou mais de atraso em alguma parcela? O numerador olha só o saldo das parcelas ainda em aberto desses contratos ruins; o denominador é o total contratado de todo o grupo (bons e ruins). A mesma lógica se aplica às outras faixas de atraso (15, 30, 60 dias), trocando apenas o corte de dias.

### 1.4 Nível do NPL: contrato inteiro, não parcela isolada

Quando um contrato atinge o corte de atraso de uma faixa (por exemplo, 90 dias) em **qualquer uma** de suas parcelas em aberto, o Painel considera o **contrato inteiro** como parte daquela faixa de risco — não apenas a parcela atrasada. Essa é a metodologia padrão de mercado: uma parcela em atraso "contamina" a leitura de risco do contrato como um todo.

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
- **Carteira em aberto**: exclui tanto os contratos já 100% quitados quanto os que estão em write-off (atraso ≥ 360 dias) — é a carteira "viva" e ainda não baixada.
- **Carteira em WriteOff**: apenas os contratos com atraso ≥ 360 dias em alguma parcela.

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

Duas visões complementares da inadimplência, ambas calculadas sobre a carteira em aberto (excluindo write-off).

- **NPL por faixa de atraso**: para cada corte de atraso (15, 30, 60 e 90 dias), mostra quantos contratos e qual percentual do saldo devedor está naquela faixa ou pior. Segue a mesma lógica de "contrato inteiro entra na faixa se qualquer parcela atingir o corte" descrita na seção 1.4.
- **Distribuição de Aging**: agrupa a carteira em aberto em faixas fixas de atraso (em dia, 1–30, 31–60, 61–90, 90+ dias), mostrando quantos contratos e qual % do saldo devedor está em cada faixa — uma "foto" da distribuição de atraso da carteira hoje.

### 3.4 📈 Taxas-chave

| Indicador | Fórmula |
|---|---|
| **Taxa de default** | % de contratos marcados como em default no sistema de origem |
| **First payment default (FPD)** | % de contratos cuja primeira parcela já não foi paga em dia |
| **Write-off (contratos)** | % de contratos que tiveram alguma parcela sinalizada como baixada a prejuízo no banco de origem (flag bruto do sistema — ver nota abaixo) |
| **Write-off (% saldo originado)** | % do valor total originado que está em contratos com atraso ≥ 360 dias |
| **Taxa de renegociados** | % de contratos-raiz que já foram renegociados |

> **Nota técnica importante**: o indicador "Write-off (contratos)" usa um sinalizador bruto do sistema de origem (se alguma parcela do contrato foi marcada como baixada), enquanto "Write-off (% saldo originado)" usa o corte padrão de 360 dias de atraso definido na seção 1.2. São duas leituras conceitualmente diferentes de "write-off" que coexistem neste bloco — vale ter isso em mente ao comparar os dois percentuais.

### 3.5 📅 Curva de maturação por safra

Mostra como a inadimplência de cada "safra" (grupo de contratos originados no mesmo mês) evolui ao longo do tempo de vida do contrato — por exemplo, comparar como a safra de janeiro/2024 se comportava aos 6 meses de idade contra a safra de julho/2024 na mesma idade.

**Como é calculado**: para cada combinação de safra e "idade" (meses desde a originação), o Painel reconstrói, parcela a parcela, qual seria o atraso de cada contrato naquele momento específico do passado (usando as datas de vencimento e de pagamento reais, sem depender de um histórico salvo dia a dia). O indicador de cada célula é:

> **% NPL da safra na idade X = (saldo que ainda estava em aberto, entre os contratos com atraso ≥ 90 dias naquela idade) ÷ (valor total originado pela safra, fixo)**

O denominador é sempre o tamanho original da safra (não muda com o tempo), enquanto o numerador usa o saldo que efetivamente estava em aberto naquele momento específico do passado — isso evita superestimar a perda de contratos que já pagaram boa parte das parcelas antes de entrar em atraso.

**Visualizações**: um mapa de calor (safra x idade em meses, cor = % NPL) para visão geral, e um gráfico de linhas para comparar safras específicas lado a lado (com uma linha tracejada mostrando a média de toda a carteira em cada idade).

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

| Indicador | Fórmula |
|---|---|
| **HHI** | Soma do quadrado da participação percentual de cada cliente (por CPF/CNPJ) no saldo devedor total da carteira em aberto. Varia de perto de 0 (carteira muito pulverizada) a 10.000 (um único cliente concentra tudo) |
| **% saldo no top 10 clientes** | Soma da participação percentual dos 10 clientes com maior saldo devedor |
| **Top 15 clientes** (gráfico/tabela) | Lista dos 15 clientes com maior participação individual no saldo devedor |

### 3.9 🧑‍💼 Perfil de risco do cliente (CCB)

Mostra a taxa de inadimplência (NPL 90+, ponderada pelo saldo devedor) segmentada por três dimensões do cliente: **rating**, **estado (UF)** e **setor de atividade (CNAE)**. A base usada combina os dados de contrato com os dados cadastrais do cliente.

Fecha com um bloco de **Restrições cadastrais**, mostrando o percentual de clientes com registro de: protesto, restritivo nacional, PEP (pessoa politicamente exposta), mandado de prisão e trabalho escravo — sinalizações vindas do processo de análise cadastral.

---

## 4. Painel Executivo

Uma visão consolidada e executiva da carteira, com indicadores de negócio, risco e financeiros, filtrável por **Produto** (CCB ou CPR, um por vez), **Carteira** (Em aberto / WriteOff / Total) e **Período** (Início/Fim, pela data de originação). Sempre que o Produto é CCB, os contratos são segmentados em "App" e "Crédito Produtor"; quando é CPR, são segmentados pelos tipos de produto CPR cadastrados no sistema (essa lista se atualiza automaticamente se surgir um novo tipo).

### 4.1 Tópico 1 — Painel Executivo (KPIs principais)

| KPI | Fórmula |
|---|---|
| **Total Concedido** | Soma do valor de principal dos contratos originais do recorte (nunca conta renegociação como novo dinheiro concedido) |
| **Contratos Ativos** | Contagem de contratos que ainda não foram 100% quitados |
| **Taxa Juros Média** | Taxa de juros mensal contratada, ponderada pelo valor de principal de cada contrato |
| **Ticket Médio** | Média simples do valor de principal por contrato |
| **FPD (90d)** | Ver fórmula canônica de "% da Carteira" na seção 1.3, aplicada ao corte de primeira parcela em atraso |
| **Inadimplência 90d** | Fórmula canônica de "% da Carteira" (seção 1.3), no corte de 90 dias — é o mesmo número, calculado da mesma forma, que aparece em toda a Análise de Risco |
| **Cobertura PDD** | Ver seção 4.3 |
| **Margem Financeira Estimada** | Ver seção 4.3 |

**Gráficos deste tópico**:
- Dois gráficos de rosca (donut) comparando categorias (App x Crédito Produtor, ou os tipos de CPR): um para valor total a receber, outro para número de contratos ativos.
- Um gráfico de barras "Indicadores de Risco por Carteira (%)", mostrando o percentual da carteira em cada faixa de atraso (FPD, 15+, 30+, 60+, 90+ dias), comparando o Total com cada categoria.

### 4.2 Tópico 2 — Composição da Carteira

Uma tabela com 10 indicadores de composição (total de contratos, clientes únicos, valor emprestado, valor a receber, valor pago, taxa de juros média, ticket médio, contratos ativos, novos contratos no último mês e valor desses novos contratos), exibidos para o Total e para cada categoria (App/Crédito Produtor ou tipos de CPR), lado a lado.

### 4.3 Tópico 3 — Indicadores de Risco e Financeiros

**Indicadores de Risco**: tabela com as faixas de atraso (FPD 90d, 15+, 30+, 60+, 90+ dias), mostrando o saldo em atraso em reais e o percentual da carteira (fórmula canônica da seção 1.3) para cada faixa, no Total e por categoria.

**Indicadores Financeiros**:

| Indicador | Fórmula |
|---|---|
| **Total de Juros (Contratada)** | Soma dos juros previstos em contrato |
| **Juros Pagos** | Parte de juros efetivamente recebida dentro do que já foi pago |
| **% Juros Pagos** | Juros pagos ÷ juros contratados |
| **Saldo Devedor** | Soma do saldo de principal ainda em aberto |
| **Inadimplência 90+ Esperada** | Saldo de principal em aberto dos contratos com atraso ≥ 90 dias (diferente da "Inadimplência 90d" do risco, que usa o valor cheio das parcelas — aqui usa-se só o principal, para fins de provisionamento) |
| **PDD** (Provisão para Devedores Duvidosos) | 50% do valor de "Inadimplência 90+ Esperada" — uma provisão fixa sobre o saldo de principal em risco |
| **Margem Financeira Bruta (Estimada)** | Juros pagos menos a provisão (PDD) |

### 4.4 Tópico 4 — Análise por Safra

Para cada mês de originação, mostra: quantidade de contratos, volume concedido, saldo devedor, perda real aos 90 dias (baseada no saldo de principal efetivamente em atraso), perda esperada (saldo de principal dos contratos em atraso ≥ 90 dias) e as respectivas taxas de inadimplência real e esperada em percentual do volume da safra. Visualizado como um gráfico combinado (barras de perda em reais + linhas de inadimplência em percentual), com uma aba por categoria.

---

## 5. Análise de Risco

Esta aba foi criada para apoiar decisões de política de crédito, identificando **quais variáveis (rating, estado, setor, renda, tempo de atividade, ticket, categoria de produto) mais explicam a inadimplência** da carteira. Usa a mesma base de dados e as mesmas fórmulas do Painel Executivo — inclusive a fórmula canônica de "% da Carteira" (seção 1.3) — para garantir que os números sejam sempre consistentes entre as duas abas.

Os filtros compartilhados pelas duas sub-abas são: **Carteira** (Em aberto/WriteOff/Total), **Produto** (CCB e/ou CPR, pode ser os dois juntos), subfiltros de tipo (CCB e CPR), **Mínimo de contratos por categoria** (esconde categorias com poucos contratos, para não distorcer a leitura com grupos muito pequenos) e **Período** (Início/Fim).

As variáveis analisadas em toda a aba são: Categoria (App/Crédito Produtor ou tipo de CPR), Rating, UF, Setor (CNAE), Faixa de Renda, Tempo de Atividade e Faixa de Ticket (esta última é um corte de risco de crédito clássico por valor do contrato).

### 5.1 Sub-aba Análise de variáveis

#### 5.1.1 "Quais variáveis mais separam bom de mau pagador?" (ranking de dispersão)

Este é o indicador criativo central da aba: mede o **poder discriminante** de cada variável, ou seja, o quanto ela ajuda a distinguir contratos de baixo e alto risco.

> **Dispersão de uma variável = (maior % de NPL 90+ entre suas categorias) − (menor % de NPL 90+ entre suas categorias)**

Se uma variável separa bem bons e maus pagadores (por exemplo, um estado com NPL de 2% e outro com 40%), sua dispersão é alta — é uma boa candidata para orientar decisões de política de crédito, como restringir ou precificar diferente a pior categoria. Se todas as categorias de uma variável têm NPL parecido, a variável pouco importa para diferenciar risco nesse recorte. O ranking mostra as variáveis ordenadas da mais para a menos discriminante, junto com qual é a pior categoria de cada uma e seu percentual de NPL.

#### 5.1.2 "Inadimplência por variável" (exploração individual)

Ao escolher uma variável (por exemplo, "UF"), o Painel mostra, para cada categoria dessa variável:

- **% de NPL 90+** (fórmula canônica da seção 1.3, calculada dentro daquele grupo).
- **Número de contratos**, **volume concedido** e **saldo devedor** do grupo.

Duas visualizações complementares:

- **Gráfico de barras**: ranking das categorias por % de NPL, do maior para o menor risco.
- **Gráfico de bolhas "Risco x Exposição"**: cada bolha é uma categoria, com a posição horizontal mostrando o % de NPL, a posição vertical mostrando o saldo devedor (exposição em R$) e o tamanho da bolha mostrando o número de contratos. Duas linhas de referência (a média ponderada de NPL e a mediana de saldo devedor) dividem o gráfico em quadrantes — o quadrante superior direito (NPL alto e saldo devedor alto) concentra as categorias mais urgentes, pois já carregam risco absoluto relevante na carteira, não só percentual.

#### 5.1.3 Cruzamento de duas variáveis

Permite escolher duas variáveis (por exemplo, UF e Setor) e ver, em um mapa de calor, o % de NPL 90+ de cada combinação das duas — útil para identificar interações específicas (por exemplo, um setor que só é problemático em determinado estado).

### 5.2 Sub-aba Simulador

O Simulador responde à pergunta: **"o que aconteceria com a carteira se decidíssemos excluir um determinado perfil de cliente?"** — por exemplo, simular a retirada de todos os contratos de um estado com um setor (CNAE) específico.

**Como funciona**: o usuário escolhe um ou dois critérios de exclusão (cada um é uma variável + os valores a excluir, por exemplo "UF = RN"), e opcionalmente combina os dois critérios com lógica "E" (só exclui quem bate as duas condições ao mesmo tempo) ou "OU" (exclui quem bate qualquer uma das duas). Isso divide a carteira filtrada em dois grupos: o **segmento excluído** e a **carteira simulada** (tudo, exceto o segmento).

Os indicadores comparativos usam exatamente as mesmas fórmulas do Painel Executivo (seções 4.1 a 4.3), calculadas três vezes — uma para a carteira **Atual** (com o segmento), uma para a carteira **Simulada** (sem o segmento) e uma só para o **Segmento** excluído:

- Total Concedido, Contratos Ativos, Ticket Médio, Taxa Juros Média
- FPD (90d), Inadimplência 90d, Cobertura PDD, Margem Financeira Estimada

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
| **Write-off (WO = 360)** | Contrato com atraso de 360 dias ou mais em alguma parcela — considerado baixado a prejuízo na maior parte dos cálculos do Painel. |
| **NPL (Non-Performing Loan)** | Contrato em atraso além de um determinado corte de dias (15, 30, 60 ou 90). No Painel, um contrato inteiro entra no NPL de uma faixa se qualquer parcela em aberto atingir aquele atraso. |
| **% da Carteira / NPL 90+** | Fórmula canônica: saldo das parcelas em aberto de contratos com atraso ≥ 90 dias, dividido pelo total contratado (pago + em aberto) do recorte. Ver seção 1.3. |
| **PDD** | Provisão para Devedores Duvidosos — no Painel Executivo, calculada como 50% do saldo de principal em contratos com atraso ≥ 90 dias. |
| **Safra** | Grupo de contratos originados no mesmo mês, usado para acompanhar a maturação da inadimplência ao longo do tempo de vida do contrato. |
| **HHI** | Índice Herfindahl-Hirschman — mede a concentração da carteira em poucos clientes grandes. |
| **PSI (Population Stability Index)** | Mede o quanto uma distribuição (de score ou de rating) se deslocou em relação a uma base de referência. Existem duas versões no Painel — ver seção 2 para a diferença entre elas. |
| **KS (Kolmogorov-Smirnov)** | Na sub-aba Relatório, mede a capacidade do modelo de separar bons e maus pagadores. Na sub-aba Estabilidade Rating (onde é chamado de KS1), mede o deslocamento máximo entre a distribuição acumulada de ratings de um mês e a da safra de referência. |
| **Categoria** | Segunda camada de segmentação usada no Painel Executivo e na Análise de Risco: "App"/"Crédito Produtor" para CCB, ou o tipo de produto CPR (dinâmico, conforme cadastro). |
