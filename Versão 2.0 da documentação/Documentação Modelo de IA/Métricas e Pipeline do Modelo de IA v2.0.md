# Métricas de Avaliação e Pipeline do Modelo de IA — Versão 2.0
**Projeto:** ArtFact — Sistema RAG de Verificação de Evidências Biomédicas  
**Programa:** RES IA ELD UnB — Turma 1 | Grupo 08  
**Data:** Outubro de 2026  
**Autores:** Victor Barbosa da Silva, Keila Alves Ferreira, Thayná Gonçalves Dutra, João Vitor Carvalho Barbosa, Vinícius César Sena Torres, Ketlyn Karen Silva de Morais  
**Branch de Referência:** `refactor/pubmed-only-mvp`

---

## 1. Por que Avaliar com Múltiplas Métricas?

O ArtFact não é um classificador monolítico simples. O sistema atua em etapas encadeadas:
1. **Recuperação e Ranqueamento:** Localiza e ordena trechos científicos potencialmente relevantes para a alegação;
2. **Classificação Textual de Relações:** Avalia a compatibilidade lógica (apoio, contradição, neutralidade) entre o trecho e a alegação;
3. **Síntese e Ancoragem Generativa:** Gera uma explicação estruturada baseada estritamente nos trechos validados.

Portanto, **não existe uma métrica única capaz de medir a qualidade de todo o sistema**. Se a recuperação falhar, a melhor LLM do mundo não terá dados para trabalhar; se a LLM alucinar, uma recuperação perfeita terá sido inútil. Cada conjunto de métricas audita uma camada específica do pipeline.

```text
Alegação
   ↓
BM25 + embeddings + ranking híbrido
   ↓  [ Métricas de Recuperação da Informação: Precision@k, Recall@k, MRR, nDCG@k ]
Trechos selecionados
   ↓
NLI / Validação Lógica
   ↓  [ Métricas de Classificação: Accuracy, Macro-F1, Matriz de Confusão, Taxa de Incerteza ]
Relações: Apoio, Contradição, Neutralidade ou Incerteza
   ↓
LLM com Schema Forçado
   ↓  [ Métricas de Groundedness: JSON Schema, Citation Validity, Literal Quote Matching, Abstinência ]
Resposta final com citações literais e proveniência auditável
```

---

## 2. Métricas de Recuperação da Informação (IR)

As métricas de recuperação verificam se o BM25, a busca semântica vetorial e o ranking híbrido colocam os trechos científicos pertinentes nas posições cimeiras do ranking.

### 2.1 Precision@k
Mede a fração de trechos relevantes entre as $k$ primeiras posições retornadas:
$$
Precision@k = \frac{|\text{trechos relevantes recuperados até } k|}{k}
$$
- **Relevância no ArtFact:** O contexto enviado ao NLI e ao LLM tem capacidade limitada. Trechos irrelevantes aumentam o custo computacional, a latência e o risco de induzir o modelo generativo ao erro.

### 2.2 Recall@k
Mede a proporção de trechos relevantes conhecidos que foram encontrados até a posição $k$:
$$
Recall@k = \frac{|\text{trechos relevantes recuperados até } k|}{|\text{total de trechos relevantes anotados no corpus}|}
$$
- **Relevância no ArtFact:** Em saúde, omitir um estudo que contradiz uma alegação perigosa é inaceitável. O Recall avalia se a cobertura de evidências é suficiente para alimentar a síntese.

### 2.3 Mean Reciprocal Rank (MRR)
Avalia a rapidez com que a primeira evidência relevante é disponibilizada:
$$
RR = \frac{1}{\text{posição do primeiro trecho relevante}}, \quad MRR = \frac{1}{|Q|} \sum_{q \in Q} RR(q)
$$
- **Relevância no ArtFact:** O primeiro resultado frequentemente define a primeira passagem inspecionada pela interface do usuário e priorizada pelo pipeline de classificação.

### 2.4 Normalized Discounted Cumulative Gain (nDCG@k)
Mede a qualidade global da ordenação ao longo das $k$ primeiras posições, aplicando uma penalização logarítmica progressiva para posições mais baixas:
$$
DCG@k = \sum_{i=1}^{k} \frac{rel_i}{\log_2(i+1)}, \quad nDCG@k = \frac{DCG@k}{IDCG@k}
$$
onde $IDCG@k$ é o ganho ideal obtido com a ordenação perfeita dos documentos relevantes.

---

## 3. Resultados Consolidados de Avaliação Offline

Os dados a seguir foram extraídos do artefato oficial de teste da branch (`entrega_modelo_ia/pipeline_completo/artefatos_artfact/resultados_avaliacao.json`), avaliados sobre o conjunto de teste autocontido (*Golden set* de 6 documentos e 31 chunks vetoriais):

| Método | Posição ($k$) | Precision@k | Recall@k | MRR | nDCG@k |
|---|:---:|:---:|:---:|:---:|:---:|
| **BM25** | $k=1$ | 0,8333 | 0,5556 | 0,9167 | 0,8333 |
| **BM25** | $k=3$ | 0,6111 | 0,9444 | 0,9167 | 0,9084 |
| **BM25** | $k=5$ | 0,4000 | 1,0000 | 0,9167 | 0,9421 |
| **Semântico (MiniLM)** | $k=1$ | 1,0000 | 0,6111 | 1,0000 | 1,0000 |
| **Semântico (MiniLM)** | $k=3$ | 0,6111 | 0,9444 | 1,0000 | 0,9609 |
| **Semântico (MiniLM)** | $k=5$ | 0,4000 | 1,0000 | 1,0000 | 0,9843 |
| **Híbrido (BM25 + Semântico)** | **k=1** | **1,0000** | **0,6111** | **1,0000** | **1,0000** |
| **Híbrido (BM25 + Semântico)** | **k=3** | **0,6111** | **0,9444** | **1,0000** | **0,9507** |
| **Híbrido (BM25 + Semântico)** | **k=5** | **0,4000** | **1,0000** | **1,0000** | **0,9843** |

### Conclusões sobre a Recuperação
1. **Recall Total em $k=5$:** Tanto o BM25 quanto o Semântico e o Híbrido alcançaram $1{,}0000$ de Recall ao considerar os 5 primeiros resultados. Isso significa que a escolha de `TOP_K = 5` garante que nenhuma evidência anotada é descartada antes da classificação.
2. **Vantagem da Abordagem Híbrida:** A combinação pelo Reciprocal Rank Fusion assegura que termos literais raros (pelo BM25) e conceitos formulados em português (pelo embedding multilíngue) alcancem $MRR = 1{,}0000$ e $nDCG@5 = 0{,}9843$.

---

## 4. Métricas do NLI (Natural Language Inference)

Após a recuperação dos trechos mais relevantes, o modelo NLI classifica a relação entre cada trecho e a alegação em três categorias primárias:
- `SUPPORTS` (Apoio textual);
- `CONTRADICTS` (Contradição textual);
- `NEUTRAL` (Neutralidade / Ausência de correlação causal direta).

### 4.1 Accuracy e Macro-F1
$$
Accuracy = \frac{\text{Classificações Corretas}}{\text{Total de Pares Avaliados}}
$$
$$
Macro\text{-}F1 = \frac{F1_{SUPPORTS} + F1_{CONTRADICTS} + F1_{NEUTRAL}}{3}
$$
- **Importância do Macro-F1:** Em saúde, a distribuição de classes costuma ser desbalanceada (maior presença de artigos neutros ou inconclusivos). O Macro-F1 atribui o mesmo peso à capacidade de detectar uma contradição e à de detectar um apoio, evitando modelos enviesados.

### 4.2 Taxa de Incerteza (`UNCERTAIN`)
Quando a probabilidade predita da classe majoritária não atinge o limiar de corte ($p < 0{,}65$) ou a diferença entre as duas maiores classes for inferior a um delta de segurança ($\Delta < 0{,}15$), o sistema atribui a classe de segurança `UNCERTAIN`. Essa abstenção controlada reduz a taxa de erro clínico da aplicação.

---

## 5. Métricas da LLM e Ancoragem Estrutural (Groundedness)

A síntese generativa é avaliada não por estilo de escrita, mas por **propriedades formais verificáveis**:

### 5.1 Validade do Esquema JSON
$$
\text{Validade do Schema} = \frac{\text{Respostas em conformidade com o JSON Schema}}{\text{Total de Requisições}}
$$
Garante que a resposta contenha todos os campos obrigatórios (relação, justificativa, citações literais e limitações) sem corrupção sintática.

### 5.2 Validade das Referências (*Citation Validity*)
$$
\text{Citation Validity} = \frac{|\text{Passage IDs citados que existem no contexto enviado}|}{|\text{Total de IDs citados pela LLM}|}
$$
Impede que o modelo cite estudos externos ou invente identificadores ausentes nas evidências recuperadas.

### 5.3 Validade das Citações Literais (*Literal Quote Matching*)
$$
\text{Literal Quote Matching} = \frac{|\text{Citações textuais idênticas a substrings do trecho original}|}{|\text{Total de citações extraídas}|}
$$
Verifica se as frases apresentadas entre aspas pelo modelo constam com correspondência exata nos documentos originais, eliminando alucinações de citações.

### 5.4 Groundedness Estrutural Global
$$
\text{Groundedness Estrutural} = \frac{\text{Respostas não-abstidas com 100\% de citações literais válidas}}{\text{Total de Respostas Avaliadas}}
$$
Representa o percentual de avaliações em que cada declaração do modelo possui respaldo rastreável comprovado.

---

## 6. Manifesto do Pipeline de Entrega (`manifesto_pipeline.json`)

Para fins de reprodutibilidade científica e auditoria da entrega acadêmica, o pipeline na branch `refactor/pubmed-only-mvp` foi selado com o seguinte manifesto criptográfico:

```json
{
  "schema_version": 1,
  "created_at": "2026-10-09T14:34:25.678322+00:00",
  "mode": "offline",
  "sha256": "c14fbb7892719f3b95eb55a4b9ce8e562c9a94b31619fe11e8a5ce9a20bd4eb3",
  "data_hash": "b1b685d2938b279e589f544f32e8604458fe82adaf4650e3fbae358556403c51",
  "chunks_hash": "e24066d4761d2da24c79245ee2fadd70390e2d00d7c7142a8cec152ac23bdfd4",
  "vectors_hash": "da0620d6f19924effc6b45a15961c47de43c9bb7482567c0663c61cd2cb49f68",
  "documents": 6,
  "chunks": 31,
  "embedding_shape": [31, 384],
  "config": {
    "MODO": "offline",
    "REEXECUTAR_MODELOS_OFFLINE": false,
    "SEMENTE": 42,
    "TOP_K": 5,
    "BM25_K1": 1.5,
    "BM25_B": 0.75,
    "PESO_BM25": 0.5,
    "PESO_SEMANTICO": 0.5,
    "EMBEDDING_MODEL": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "NLI_MODEL": "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli",
    "GEMINI_MODEL": "gemini-flash-lite-latest",
    "EMBEDDING_REVISION": "e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
    "NLI_REVISION": "0a71e92a985b6e1ad1828cf67ce9c459639c1dca",
    "CHUNK_WORDS": 90,
    "CHUNK_OVERLAP": 15,
    "SEMANTIC_MIN": 0.35,
    "RRF_K": 60
  }
}
```

---

## 7. Quadro de Aplicação das Métricas no Ciclo de Vida

| Etapa do Pipeline | Métricas Principais | Impacto no Produto Final |
|---|---|---|
| **BM25 + Vetores Densos** | Precision@k, Recall@k, MRR, nDCG@k | Assegura que evidências relevantes estejam no $top\text{-}5$ sem poluição de contexto |
| **Filtros e Limiares** | Taxa de Abstinência e Cobertura | Impede avanço da análise quando o material bibliográfico for irrelevante |
| **Classificador NLI** | Accuracy, Macro-F1 e Matriz de Confusão | Identifica conflitos e nuances entre apoio e contradição nas fontes |
| **Geração LLM (Gemini)** | JSON Schema Validity, Citation Validity | Garante que o retorno seja processável e semanticamente amarrado aos dados |
| **Auditoria Textual** | Literal Quote Matching e Groundedness | Bloqueia alucinações e protege a credibilidade médica do produto |
| **Pipeline Completo** | Latência média, Taxa de Sucesso de Análise | Assegura viabilidade operacional na interface web e na API REST |
