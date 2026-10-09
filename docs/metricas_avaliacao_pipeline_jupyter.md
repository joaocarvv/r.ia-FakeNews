## Métricas de avaliação do pipeline

O ArtFact não executa uma única classificação. O produto possui várias etapas: primeiro recupera trechos científicos, depois estima a relação entre cada trecho e a alegação e, por fim, utiliza uma LLM para organizar uma resposta fundamentada nas evidências. Por isso, não existe uma única métrica capaz de avaliar todo o sistema. Cada grupo de métricas verifica uma parte específica do pipeline.

```text
Alegação
   ↓
BM25 + embeddings + ranking híbrido
   ↓ métricas de recuperação
Trechos selecionados
   ↓
NLI
   ↓ métricas de classificação
Relações: apoio, contradição, neutralidade ou incerteza
   ↓
LLM
   ↓ métricas estruturais e de fundamentação
Resposta final com citações e proveniência
```

### Métricas de recuperação

As métricas de recuperação avaliam se BM25, busca semântica e ranking híbrido colocam os trechos científicos relevantes entre os primeiros resultados. Essa etapa é essencial porque NLI e LLM só conseguem analisar as evidências que foram recuperadas. Se um documento importante não chega às etapas seguintes, os modelos posteriores não conseguem corrigir essa ausência.

**Precision@k** mede a proporção de resultados relevantes entre as `k` primeiras posições do ranking:

$$
Precision@k =
\frac{\text{documentos relevantes recuperados até } k}{k}
$$

Usamos Precision porque o produto possui espaço e capacidade de processamento limitados. Enviar muitos trechos irrelevantes para NLI e Gemini aumenta a latência, o consumo de recursos e o risco de a resposta final utilizar uma evidência inadequada. Uma Precision alta significa que uma parte maior dos trechos apresentados às etapas seguintes é realmente relacionada à alegação.

Por exemplo, se o sistema retorna cinco trechos e três são relevantes:

$$
Precision@5 = \frac{3}{5} = 0{,}60
$$

No pipeline, Precision é calculada depois que BM25, recuperação semântica e ranking híbrido produzem suas listas. Ela permite comparar qual método concentra mais evidências úteis nas primeiras posições.

**Recall@k** mede quanto do conjunto de documentos relevantes conhecidos foi encontrado até a posição `k`:

$$
Recall@k =
\frac{\text{documentos relevantes recuperados até } k}
{\text{total de documentos relevantes anotados}}
$$

Usamos Recall porque omitir uma evidência importante também representa um risco. Um ranking pode ter Precision alta por retornar apenas um resultado correto, mas ainda deixar de recuperar outros estudos relevantes, inclusive estudos que contradizem a alegação. O Recall verifica se o pipeline oferece uma cobertura adequada antes de produzir a síntese.

Se existem quatro documentos relevantes e três aparecem nas cinco primeiras posições:

$$
Recall@5 = \frac{3}{4} = 0{,}75
$$

No produto, Recall ajuda a definir o valor de `top_k`. Um `k` muito pequeno pode deixar evidências importantes de fora. Um `k` muito grande aumenta a cobertura, mas pode introduzir muitos documentos irrelevantes. Por isso, Precision e Recall devem ser interpretadas em conjunto.

Consultas sem documentos relevantes anotados não recebem um valor de Recall, porque o denominador seria zero. Esses casos são avaliados separadamente pelas métricas de abstinência.

**MRR — Mean Reciprocal Rank** avalia quão cedo aparece o primeiro resultado relevante. Para cada consulta, calculamos o inverso da posição do primeiro relevante:

$$
RR = \frac{1}{\text{posição do primeiro relevante}}
$$

Depois calculamos a média entre as consultas:

$$
MRR = \frac{1}{N}\sum RR
$$

Se o primeiro relevante aparece na posição 1, a pontuação é `1,0`. Na posição 2, é `0,5`. Na posição 5, é `0,2`. Se nenhum relevante for recuperado, a pontuação é zero.

Usamos MRR porque o primeiro resultado recebe atenção especial no produto e normalmente é o primeiro candidato enviado para análise. Mesmo quando dois métodos apresentam o mesmo Recall, é preferível aquele que posiciona uma evidência relevante mais cedo.

O MRR responde:

> O sistema encontra rapidamente pelo menos uma evidência relevante?

Ele não mede quantos documentos relevantes foram recuperados. Por isso, deve ser acompanhado de Recall e nDCG.

**nDCG@k — Normalized Discounted Cumulative Gain** avalia a qualidade da ordenação de todos os resultados relevantes até `k`. A métrica aplica um desconto progressivo: resultados relevantes nas primeiras posições recebem mais valor do que resultados relevantes encontrados no final da lista.

Primeiro calculamos o ganho descontado:

$$
DCG@k =
\sum_{i=1}^{k}
\frac{rel_i}{\log_2(i+1)}
$$

Em seguida, comparamos esse valor com o melhor ranking possível:

$$
nDCG@k =
\frac{DCG@k}{IDCG@k}
$$

O resultado varia de 0 a 1. Um valor próximo de 1 significa que os documentos relevantes estão concentrados nas melhores posições.

Usamos nDCG porque MRR observa apenas o primeiro relevante. O produto pode trabalhar com vários trechos e estudos, então também precisamos verificar se os demais relevantes estão bem posicionados. Isso é especialmente importante no ranking híbrido, que combina BM25 e embeddings e pode alterar a ordem dos candidatos.

Na avaliação atual, a relevância é binária:

```text
1 = documento relevante
0 = documento não relevante
```

Portanto, o nDCG avalia a ordem dos relevantes anotados, sem inventar diferentes níveis de qualidade científica.

### Por que utilizar várias métricas de recuperação?

As quatro métricas respondem a perguntas diferentes:

| Métrica | Pergunta respondida |
|---|---|
| Precision@k | Quanto do que o sistema recuperou é relevante? |
| Recall@k | Quanto da evidência relevante disponível foi encontrado? |
| MRR | Em que posição aparece a primeira evidência relevante? |
| nDCG@k | Os documentos relevantes estão bem ordenados ao longo do ranking? |

Essas métricas são adequadas para o ArtFact porque o produto realiza recuperação e ordenação de evidências. Entretanto, elas não avaliam se a conclusão de um artigo está cientificamente correta. Elas medem a capacidade do sistema de localizar os documentos anotados como relevantes.

### Métricas do NLI

Depois da recuperação, o NLI compara cada trecho selecionado com a alegação. O modelo estima três relações textuais:

- `SUPPORTS`: o trecho oferece suporte à alegação;
- `CONTRADICTS`: o trecho contradiz a alegação;
- `NEUTRAL`: o trecho não permite concluir apoio ou contradição.

O pipeline também pode produzir `UNCERTAIN` quando a maior probabilidade ou a diferença entre as duas maiores probabilidades não atinge os limites configurados. `UNCERTAIN` é uma regra de segurança aplicada sobre a saída do modelo, não uma classe originalmente aprendida pelo NLI.

**Accuracy** mede a proporção total de pares alegação–evidência classificados corretamente:

$$
Accuracy =
\frac{\text{classificações corretas}}
{\text{total de pares avaliados}}
$$

Usamos Accuracy porque ela oferece uma medida direta da concordância entre o NLI e as anotações de engenharia.

Por exemplo, se o NLI acerta 8 dos 10 pares:

$$
Accuracy = \frac{8}{10} = 0{,}80
$$

Entretanto, Accuracy pode ser enganosa quando existe desequilíbrio entre as classes. Se a maior parte dos exemplos for `NEUTRAL`, um modelo que quase sempre responda `NEUTRAL` pode apresentar Accuracy aparentemente alta, mesmo tendo desempenho ruim em `SUPPORTS` e `CONTRADICTS`.

Por isso, utilizamos também o **macro-F1**.

Para cada classe, o F1 combina Precision e Recall:

$$
F1 =
2 \times
\frac{Precision \times Recall}
{Precision + Recall}
$$

Depois calculamos a média simples entre as classes:

$$
Macro\text{-}F1 =
\frac{F1_{SUPPORTS} + F1_{CONTRADICTS} + F1_{NEUTRAL}}{3}
$$

Usamos macro-F1 porque cada relação recebe o mesmo peso, independentemente da quantidade de exemplos. Isso é relevante para o produto porque errar uma contradição pode ser tão importante quanto errar um apoio, mesmo que existam menos exemplos de contradição no conjunto.

No pipeline, Accuracy e macro-F1 são calculadas depois que o NLI processa os pares formados pelos trechos recuperados. A matriz de confusão complementa essas métricas, mostrando quais relações são confundidas, por exemplo:

```text
CONTRADICTS classificado como NEUTRAL
SUPPORTS classificado como NEUTRAL
NEUTRAL classificado como SUPPORTS
```

A taxa de `UNCERTAIN` é analisada separadamente. Uma taxa elevada reduz a cobertura, mas pode evitar classificações arriscadas. Também podemos calcular a Accuracy apenas entre as classificações não incertas, sempre informando quantos casos foram excluídos. Isso permite analisar o compromisso entre cobertura e segurança.

As anotações usadas como referência são de engenharia. Portanto, Accuracy e macro-F1 medem concordância com essas anotações, não validade clínica ou consenso científico.

### Métricas da LLM

A LLM recebe a alegação e somente as evidências selecionadas pelo pipeline. Sua função é organizar uma avaliação estruturada e citar os trechos utilizados. Como respostas generativas podem parecer convincentes mesmo quando não estão fundamentadas, avaliamos primeiro propriedades verificáveis.

**Validade do JSON** mede a proporção de respostas que seguem o formato exigido pelo produto:

$$
\text{Validade do JSON} =
\frac{\text{respostas com JSON válido e schema correto}}
{\text{total de respostas}}
$$

Usamos essa métrica porque o produto precisa converter a resposta da LLM em campos como relação, explicação, citações e limitações. Uma resposta textual que não respeita o schema pode ser impossível de processar, mesmo que pareça adequada para uma pessoa.

**Validade das referências** verifica se os PMIDs, documentos e `passage_id` citados pela LLM existem no conjunto enviado ao modelo:

$$
\text{Validade das referências} =
\frac{\text{referências reconhecidas}}
{\text{total de referências retornadas}}
$$

Essa métrica é relevante porque impede que a LLM utilize ou invente fontes que não passaram pela recuperação científica.

**Validade das citações literais** verifica se o texto apresentado como citação realmente aparece na passagem indicada:

$$
\text{Validade das citações} =
\frac{\text{citações encontradas literalmente nas passagens}}
{\text{total de citações}}
$$

No produto, essa verificação acontece depois da resposta da LLM. Normalizamos espaços e comparamos cada `quote` com o texto do `passage_id` correspondente. Uma citação pode apontar para um ID existente e ainda assim conter palavras que não aparecem no trecho; por isso, validade da referência e validade da citação são medidas separadas.

**Cobertura de `passage_id`** mede quantas das evidências disponíveis foram efetivamente utilizadas pela resposta:

$$
\text{Cobertura de passagens} =
\frac{\text{passagens distintas citadas}}
{\text{passagens fornecidas à LLM}}
$$

Essa métrica ajuda a identificar respostas baseadas em uma única passagem quando várias evidências relevantes foram fornecidas. Entretanto, cobertura alta não é sempre melhor: a LLM não deve citar uma passagem apenas para aumentar a métrica. A cobertura é usada como informação diagnóstica, não como objetivo isolado.

**Groundedness estrutural** mede a proporção de respostas não abstidas que apresentam pelo menos uma citação e cujas citações são estruturalmente válidas:

$$
\text{Groundedness estrutural} =
\frac{\text{respostas com todas as citações válidas}}
{\text{respostas que emitiram uma avaliação}}
$$

Usamos essa métrica porque a resposta final do ArtFact deve ser rastreável. Se a LLM afirma apoio ou contradição, o usuário precisa conseguir localizar a passagem científica usada.

O termo “estrutural” é importante: essa métrica verifica se a resposta está ligada às fontes fornecidas, mas não determina se a interpretação da fonte está cientificamente correta.

**Concordância de relação** compara a relação final retornada pela LLM com a anotação esperada:

```text
SUPPORTS
CONTRADICTS
NEUTRAL
UNCERTAIN
```

Ela pode ser expressa como Accuracy e macro-F1, mas deve permanecer separada das métricas do NLI, porque são componentes diferentes. O NLI classifica diretamente um par de textos; a LLM recebe várias evidências e produz uma explicação mais ampla.

Essa concordância ajuda a verificar se a síntese final preserva a direção das evidências. Entretanto, não mede a qualidade completa da explicação, a validade metodológica dos estudos ou a correção clínica da conclusão.

**Taxa de abstinência da LLM** mede quantas vezes o modelo declarou evidência insuficiente em vez de produzir uma conclusão:

$$
\text{Taxa de abstinência} =
\frac{\text{respostas UNCERTAIN ou ABSTAIN}}
{\text{total de respostas}}
$$

No ArtFact, a abstinência é um comportamento de segurança. Ela é desejável quando não existem evidências suficientes, mas indesejável quando o corpus contém evidências claras. Por isso, a taxa isolada não é interpretada como boa ou ruim. Também verificamos o acerto da decisão de abstinência nos casos com e sem evidência anotada.

### Como as métricas entram no produto

| Etapa do pipeline | Métricas principais | Uso no produto |
|---|---|---|
| BM25, embeddings e ranking híbrido | Precision@k, Recall@k, MRR e nDCG@k | Verificar se evidências relevantes chegam às etapas seguintes e em boas posições |
| Seleção de candidatos | Precision, Recall e abstinência | Escolher `top_k` e limiares sem enviar excesso de ruído |
| NLI | Accuracy, macro-F1, matriz de confusão e taxa de incerteza | Avaliar suporte, contradição e neutralidade |
| LLM | JSON válido e concordância de relação | Verificar se a saída pode ser processada e se preserva a direção esperada |
| Fundamentação | IDs válidos, citações literais, cobertura e groundedness | Impedir referências inventadas e manter rastreabilidade |
| Pipeline completo | Abstinência, latência e taxa de sucesso | Avaliar segurança e viabilidade operacional |

Essas métricas são relevantes porque correspondem às responsabilidades reais de cada componente. Elas não são intercambiáveis: Precision de recuperação não mede qualidade do NLI, Accuracy do NLI não mede qualidade das citações e groundedness estrutural não comprova validade clínica.

> A avaliação demonstra se o pipeline recupera, classifica, estrutura e referencia evidências conforme o comportamento esperado nos casos anotados. Ela não comprova verdade científica, segurança clínica, ausência de viés ou correção integral das explicações geradas.
