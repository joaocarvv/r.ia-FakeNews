# Levantamento de Datasets — Versão 2.0
**Projeto:** ArtFact — Verificação de Alegações de Saúde com IA  
**Grupo:** 08  
**Data:** Outubro de 2026  
**Branch de referência:** `refactor/pubmed-only-mvp`

---

## 1. Contexto e Evolução em Relação à v1.0

Na Versão 1.0, o projeto contemplava múltiplas fontes de dados (OpenAlex, SciELO, Europe PMC, Crossref, etc.). A Versão 2.0 consolida o escopo no ecossistema da **National Library of Medicine (NLM/NCBI)**, removendo dependências externas do runtime e priorizando dados rastreáveis e auditáveis.

---

## 2. Datasets Utilizados na v2.0

### 2.1 Dataset Principal — PubMed (Corpus de Estudo de Caso)

| Atributo | Valor |
|---|---|
| **Arquivo** | `data/pubmed_cafe_cancer_prostata.csv` |
| **Fonte** | PubMed / NCBI E-utilities |
| **URL** | https://pubmed.ncbi.nlm.nih.gov/ |
| **Consulta** | `("Coffee"[MeSH Terms] OR coffee[Title/Abstract]) AND ("Prostatic Neoplasms"[MeSH Terms] OR "prostate cancer"[Title/Abstract])` |
| **Ordenação** | Relevância |
| **Registros** | 100 artigos científicos indexados |
| **Formato** | CSV |
| **Cobertura** | Artigos com abstract disponível no PubMed |
| **Uso** | Estudo de caso — relação entre consumo de café e câncer de próstata |

**Metadados (arquivo:** `data/pubmed_cafe_cancer_prostata_metadata.json`**):**
- Fonte e URL de coleta
- Consulta exata utilizada
- Data e hora de coleta (UTC)
- Critérios de ordenação

### 2.2 Dataset de Confiabilidade e Segurança

| Atributo | Valor |
|---|---|
| **Arquivo** | `data/reliability_safety_cases.json` |
| **Tipo** | Casos de teste para avaliação de confiabilidade |
| **Uso** | Validação das regras de abstenção e exclusão de artigos retratados |
| **Referência** | `notebooks/19_validacao_confiabilidade.ipynb` |

### 2.3 Corpus de Validação do Pipeline de Recuperação

| Atributo | Valor |
|---|---|
| **Arquivo** | `tests/fixtures/retrieval/golden.json` |
| **Tipo** | Ground truth anotado manualmente |
| **Uso** | Avaliação das métricas de recuperação (Precision@k, Recall@k, MRR, nDCG@k) |

| Atributo | Valor |
|---|---|
| **Arquivo** | `tests/fixtures/retrieval/unlabelled.json` |
| **Tipo** | Consultas sem anotação de relevância |
| **Uso** | Avaliação de abstinência e cobertura de busca |

---

## 3. Fontes de Dados em Tempo Real (Runtime)

O sistema acessa as seguintes APIs durante a execução:

| Fonte | API / Endpoint | Tipo de Dado | Observação |
|---|---|---|---|
| **PubMed** | NCBI E-utilities (`esearch`, `efetch`, `einfo`) | Metadados, PMIDs, abstracts | Fonte principal de descoberta |
| **PubMed Central (PMC)** | NCBI E-utilities (`efetch` XML) | Texto completo dos artigos | Disponível somente para artigos com acesso aberto |
| **NCBI Gene** | E-utilities dinâmico | Registros genômicos | Ativado por alegações com entidades biomédicas |
| **ClinVar** | E-utilities dinâmico | Variantes clínicas | Ativado por alegações com entidades biomédicas |

**Observação:** OpenAlex, SciELO, Europe PMC, Unpaywall, Semantic Scholar, Crossref, DataCite e ClinicalTrials.gov **não são instanciados** no runtime da v2.0.

---

## 4. Fontes Removidas do Runtime (comparado à v1.0)

| Fonte | Status na v2.0 |
|---|---|
| OpenAlex | Código preservado, não instanciado |
| SciELO | Código preservado, não instanciado |
| Europe PMC | Código preservado, não instanciado |
| Crossref | Código preservado, não instanciado |
| Unpaywall | Removido do runtime |
| Semantic Scholar | Removido do runtime |
| DataCite | Removido do runtime |
| ClinicalTrials.gov | Removido do runtime |

---

## 5. Configuração de Coleta

Variáveis de ambiente que controlam o comportamento dos datasets:

| Variável | Padrão | Finalidade |
|---|---|---|
| `NCBI_API_KEY` | vazio | Aumenta o limite de chamadas ao NCBI |
| `NCBI_EMAIL` | vazio | Identifica o responsável pelas chamadas (recomendado) |
| `MAX_SOURCES` | 8 | Máximo de publicações recuperadas por alegação |
| `HTTP_TIMEOUT` | 20 | Timeout em segundos para chamadas externas |
| `STRUCTURED_SEARCH_CACHE_TTL` | 300 | Cache das consultas ao NCBI Gene/ClinVar (segundos) |

---

## 6. Limitações e Declarações de Integridade

- O MVP **não declara** que um artigo é verdadeiro ou falso com base nos datasets.
- Dados extraídos são conservados **somente se encontrados literalmente** no texto, com seção e fonte citada.
- Artigos **retratados** são excluídos da síntese e identificados na interface.
- A cobertura de texto completo depende da disponibilidade do artigo no PMC (acesso aberto).
- Quando apenas o abstract está disponível, isso é informado explicitamente ao usuário.

---

## 7. Rastreabilidade

| Componente | Arquivo de Referência |
|---|---|
| Coleta PubMed | `src/fatofake/pubmed.py` |
| Texto completo PMC | `src/fatofake/pmc.py` |
| Busca biomédica dinâmica | `src/fatofake/structured_sources.py` |
| Ingestão de artigos | `src/fatofake/article_ingestion.py` |
| Validação de confiabilidade | `notebooks/19_validacao_confiabilidade.ipynb` |
| EDA do corpus | `notebooks/16_eda_pubmed.ipynb` |
