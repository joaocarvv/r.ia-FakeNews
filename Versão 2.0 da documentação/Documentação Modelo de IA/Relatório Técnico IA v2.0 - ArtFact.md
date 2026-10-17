# Relatório Técnico do Modelo de IA — Versão 2.0
**Projeto:** ArtFact — Sistema RAG de Verificação de Evidências Biomédicas  
**Programa:** RES IA ELD UnB — Turma 1 | Grupo 08  
**Data:** Outubro de 2026  
**Autores:** Victor Barbosa da Silva, Keila Alves Ferreira, Thayná Gonçalves Dutra, João Vitor Carvalho Barbosa, Vinícius César Sena Torres, Ketlyn Karen Silva de Morais  
**Branch de Referência:** `refactor/pubmed-only-mvp`

---

## 1. Introdução

O presente relatório técnico descreve a arquitetura, o pipeline de dados, a seleção de modelos e as decisões de engenharia implementadas na **Versão 2.0 do ArtFact**. O produto opera como um sistema avançado de **Retrieval-Augmented Generation (RAG)** em ambiente biomédico, projetado para analisar alegações de saúde em português e confrontá-las diretamente com a literatura científica indexada no ecossistema da **National Library of Medicine (PubMed e PMC)**.

Diferente de sistemas simplistas de checagem que tentam atribuir um rótulo binário superficial ("fato" ou "fake"), o ArtFact v2.0 tem como objetivo central estruturar um corpo auditável de evidências primárias, extraindo trechos literais comprovados, classificando relações lógicas de suporte ou contradição, expondo limitações metodológicas e garantindo rastreabilidade completa até a fonte original.

---

## 2. Pipeline de Dados e Preparação

```text
[ Entrada do Usuário ]
  ├─ Texto livre da alegação (PT/EN)
  └─ Artigo opcional (PMID, DOI, Link PubMed ou PDF/Imagem)
        │
        ▼
[ 1. Ingestão e Descoberta ]
  ├─ NCBI E-utilities (PubMed API)
  ├─ Texto completo via PubMed Central (PMC XML)
  └─ Fallback: Abstract do PubMed
        │
        ▼
[ 2. Chunking Granular ]
  ├─ Segmentação: ~60 a 90 palavras
  ├─ Sobreposição (Overlap): 12 a 15 palavras
  └─ Atribuição de Metadados e passage_id único
        │
        ▼
[ 3. Recuperação Híbrida (Hybrid Retrieval) ]
  ├─ Índice Lexical: BM25 (k1=1.5, b=0.75)
  ├─ Índice Semântico: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384d)
  └─ Fusão por Posição: Reciprocal Rank Fusion (RRF)
        │
        ▼
[ 4. Classificação Textual de Relações (NLI / LLM) ]
  ├─ Modelo NLI: MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli
  ├─ Relações: SUPPORTS, CONTRADICTS, NEUTRAL, UNCERTAIN
  └─ Regras de Abstenção em Evidência Insuficiente
        │
        ▼
[ 5. Síntese Estruturada e Verificação (LLM Gemini) ]
  ├─ Modelo: gemini-flash-lite-latest (Schema JSON forçado)
  ├─ Ancoragem estrita de passagens (Groundedness)
  └─ Checagem de citações literais (Literal Quote Matching)
        │
        ▼
[ Resposta Final Estruturada na Interface ]
```

### 2.1 Ingestão e Normalização
- **Orquestração NCBI (`src/fatofake/pubmed.py`):** Realiza chamadas com tratamento automático de retentativas e respeito aos limites da API.
- **Parsing de Texto Completo (`src/fatofake/pmc.py`, `document_parsing.py`):** Extrai seções padronizadas (*Introduction*, *Methods*, *Results*, *Discussion*, *Conclusion*) a partir do XML oficial do PMC. Em caso de uploads manuais em PDF, emprega parsing local preservando a proveniência por página.

### 2.2 Segmentação em Chunks (*EvidenceChunk*)
A granularidade do texto é crucial para evitar que passagens irrelevantes contaminem o contexto da LLM:
- **Tamanho dos Chunks:** 60 a 90 palavras;
- **Sobreposição (*Overlap*):** 12 a 15 palavras;
- Cada chunk recebe um identificador determinístico composto por `PMID:chunk_index` e hash de proveniência, permitindo auditoria ponta a ponta.

---

## 3. Seleção de Modelos e Abordagem Adotada

### 3.1 Modelo de Embeddings Semânticos
- **Modelo:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (revisão `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`);
- **Dimensão Vetorial:** 384 dimensões;
- **Justificativa:** Capacidade comprovada de projetar consultas em português e abstracts científicos em inglês no mesmo espaço vetorial contínuo, sem depender de tradução prévia por máquina que possa distorcer termos médicos.

### 3.2 Indexação Vetorial com Qdrant
- **Módulo:** `src/fatofake/qdrant_retrieval.py`;
- **Mecanismo:** Armazenamento em memória/persistente dos vetores densos normalizados por distância de cosseno, possibilitando busca por k-vizinhos mais próximos (k-NN) com alta velocidade e baixo consumo de memória.

### 3.3 Recuperação Lexical com BM25
- **Parâmetros:** $k_1 = 1{,}5$, $b = 0{,}75$;
- **Justificativa:** Imprescindível para termos biomédicos raros, acrônimos de genes (ex.: *BRCA1*, *PSA*), substâncias químicas e dosagens numéricas que poderiam ser suavizadas excessivamente por embeddings semânticos.

### 3.4 Fusão de Rankings (Reciprocal Rank Fusion - RRF)
O sistema combina as listas ranqueadas do BM25 e da busca vetorial utilizando a fórmula:
$$
RRF(d) = \sum_{m \in \{BM25, Semantico\}} \frac{1}{60 + r_m(d)}
$$
onde $r_m(d)$ é a posição do documento no método $m$. Essa técnica evita a soma inadequada de scores de naturezas matemáticas distintas (pontuação BM25 aberta vs. similaridade de cosseno $[-1, 1]$).

### 3.5 Modelo de Inferência em Linguagem Natural (NLI)
- **Modelo Local:** `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` (revisão `0a71e92a985b6e1ad1828cf67ce9c459639c1dca`);
- **Função:** Estimar formalmente a probabilidade condicional de acarretamento (*entailment* / `SUPPORTS`), contradição (`CONTRADICTS`) ou neutralidade (`NEUTRAL`) entre o trecho científico e a alegação.
- **Regra de Incerteza:** Se a maior probabilidade não atingir o limiar estipulado ou a diferença entre as duas maiores classes for inferior a um delta de segurança, a classificação é promovida para `UNCERTAIN`.

### 3.6 Modelo Generativo de Síntese (LLM Gemini)
- **Modelo:** `gemini-flash-lite-latest` via Google AI Studio API;
- **Engenharia de Prompt:** O prompt instrui o modelo a atuar como sintetizador de literatura clínica, impondo:
  - Formato estrito via JSON Schema forçado;
  - Proibição terminante de utilizar conhecimentos prévios não contidos nas passagens enviadas;
  - Preenchimento da tabela de componentes epidemiológicos PICO;
  - Citação literal de frases entre aspas com indicação obrigatória do `passage_id`.

---

## 4. Mitigação de Alucinações e Engenharia de Confiabilidade

Para assegurar confiabilidade clínica e segurança da informação, a v2.0 implementa quatro camadas de validação determinística:

1. **Validação Estrutural de Schema:** Respostas fora do JSON Schema são rejeitadas pelo backend.
2. **Auditoria de IDs de Citação (`passage_id`):** O backend confere se cada passagem citada pelo LLM foi efetivamente entregue no prompt. Citações com IDs fictícios são sumariamente descartadas.
3. **Checagem de Citações Literais (*Literal Quote Matching*):** Cada trecho alegado como citação textual é submetido a um algoritmo de correspondência substring exata no texto da passagem original (com normalização de espaços em branco). Se o LLM alterar palavras ou inventar sentenças, a citação é invalidada.
4. **Filtro de Artigos Retratados:** Artigos com sinalização de retratação científica no PubMed são barrados da síntese e destacados em alerta na interface do usuário.

---

## 5. Resultados Experimentais de Desempenho

Os testes de recuperação realizados sobre o conjunto anotado de referência (*Golden set* de 31 chunks) registraram os seguintes resultados consolidados:

| Método de Recuperação | k | Precision@k | Recall@k | MRR | nDCG@k |
|---|---|---|---|---|---|
| **BM25** | 1 | 0,8333 | 0,5556 | 0,9167 | 0,8333 |
| **BM25** | 3 | 0,6111 | 0,9444 | 0,9167 | 0,9084 |
| **BM25** | 5 | 0,4000 | 1,0000 | 0,9167 | 0,9421 |
| **Semântico Denso** | 1 | 1,0000 | 0,6111 | 1,0000 | 1,0000 |
| **Semântico Denso** | 3 | 0,6111 | 0,9444 | 1,0000 | 0,9609 |
| **Semântico Denso** | 5 | 0,4000 | 1,0000 | 1,0000 | 0,9843 |
| **Híbrido (RRF)** | **1** | **1,0000** | **0,6111** | **1,0000** | **1,0000** |
| **Híbrido (RRF)** | **3** | **0,6111** | **0,9444** | **1,0000** | **0,9507** |
| **Híbrido (RRF)** | **5** | **0,4000** | **1,0000** | **1,0000** | **0,9843** |

### Interpretação dos Resultados
- **Recall Máximo com k=5:** Atingiu **1,0000** (100% dos trechos relevantes recuperados entre os 5 primeiros colocados), comprovando que o pipeline não omite estudos pertinentes antes da etapa de síntese.
- **MRR Perfeito no Semântico e Híbrido:** O valor de **1,0000** indica que em 100% das consultas o documento clinicamente mais relevante apareceu logo na **primeira posição** do ranking.
- **Excelente Ordenação (nDCG@5 = 0,9843):** O ranqueamento posicionou os trechos altamente pertinentes no topo, minimizando ruído para o contexto de entrada do LLM.

---

## 6. Principais Desafios Enfrentados

1. **Heterogeneidade de Acesso:** Artigos com texto integral restrito (*paywall*) impedem a leitura completa automatizada. O sistema contornou isso operando com transparência: consome o abstract do PubMed e sinaliza expressamente que a análise está limitada ao resumo, oferecendo ao usuário a opção de fornecer o PDF completo.
2. **Latência de Processamento:** A execução de busca léxica, inferência de embeddings e consulta ao LLM em série representava um gargalo de tempo de resposta. A arquitetura resolveu o problema adotando **processamento assíncrono com polling de status via API HTTP**, permitindo que a interface apresente barras de progresso contínuas.
3. **Resiliência a Rate Limits e Erros 429:** A API do Gemini e as E-utilities do NCBI possuem limites de vazão por minuto. Foi implementada uma política de retentativa exponencial com backoff (`LLM_MAX_ATTEMPTS=3`, `LLM_RETRY_BACKOFF=1s`).

---

## 7. Lições Aprendidas e Conclusão

O desenvolvimento da Versão 2.0 do ArtFact consolidou a convicção de que **a precisão científica de um sistema RAG decorre fundamentalmente da qualidade dos seus componentes de recuperação e das suas salvaguardas de ancoragem**, e não do tamanho bruto do modelo gerativo utilizado.

Ao reduzir o escopo para um ecossistema fidedigno (PubMed/PMC), descartar vereditos categóricos simplistas e vincular cada afirmação da IA a uma citação literal comprovada, o ArtFact v2.0 entrega um ambiente transparente, reproduzível e academicamente responsável para a análise crítica de literatura médica.
