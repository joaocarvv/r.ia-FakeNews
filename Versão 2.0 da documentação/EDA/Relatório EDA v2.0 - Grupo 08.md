# Análise Exploratória de Dados (EDA) — Versão 2.0
**Corpus PubMed: Associação entre Consumo de Café e Risco de Câncer de Próstata**  
**Projeto:** ArtFact — Verificação de Alegações de Saúde com IA  
**Programa:** RES IA ELD UnB — Turma 1 | Grupo 08  
**Data:** Outubro de 2026  
**Autores:** Victor Barbosa da Silva, Keila Alves Ferreira, Thayná Gonçalves Dutra, João Vitor Carvalho Barbosa, Vinícius César Sena Torres, Ketlyn Karen Silva de Morais  
**Branch de Referência:** `refactor/pubmed-only-mvp`

---

## 1. Resumo Executivo e Contextualização

### 1.1 Contextualização do Tema
Esta análise exploratória utiliza como estudo de caso a investigação da associação entre o **consumo de café e o risco de câncer de próstata**. O tema foi selecionado por representar com fidelidade o perfil de alegações de saúde disseminadas em mídias digitais e redes sociais de forma reducionista, frequentemente convertendo correlações observacionais em afirmações categóricas de causalidade ("café cura câncer" ou "café causa câncer").

A literatura biomédica indexada sobre o tema compreende estudos observacionais (coorte e caso-controle), ensaios pré-clínicos, revisões sistemáticas e meta-análises, com populações de origens geográficas diversas, métodos de preparo variados e conclusões por vezes heterogêneas. Essa complexidade torna o corpus ideal para o estresse do pipeline RAG (Retrieval-Augmented Generation) do **ArtFact**, exigindo:
- Recuperação precisa de literatura primária via PubMed/PMC;
- Descarte de conclusões binárias precipitadas ("fato" ou "fake");
- Extração de trechos literais e citação rastreável de evidências;
- Reconhecimento explícito de limitações e conflitos no corpo de evidências.

### 1.2 Principais Achados
- **Volume e Cobertura:** Foram analisados 100 registros bibliográficos dos 116 retornados pela consulta oficial via NCBI E-utilities (cobertura amostral de **86,2%**).
- **Integridade Cadastral:** Ausência total de duplicações em PMIDs e títulos normalizados (0% de duplicatas).
- **Completude de Metadados:** PMIDs, títulos, periódicos, datas e URLs canônicas apresentaram 100% de preenchimento. Apenas 7 registros (7,0%) não possuíam DOI (comum em artigos clássicos anteriores aos anos 2000), e 2 registros (2,0%) não informavam autoria individual.
- **Distribuição Temporal:** O corpus cobre um intervalo de 62 anos (**1964 a 2026**), com forte concentração a partir da década de 2010, refletindo a evolução metodológica na epidemiologia nutricional.
- **Aderência Temática dos Títulos:** 39 títulos mencionam simultaneamente termos relacionados a "café" e "próstata"; 12 títulos não mencionam nenhum dos dois diretamente (foram indexados devido ao abstract ou termos MeSH como *Dietary Factors* ou *Prostatic Neoplasms*).

---

## 2. Metodologia de Coleta e Fonte dos Dados

| Parâmetro | Especificação |
|---|---|
| **Fonte Oficial** | PubMed — National Library of Medicine (NLM / NCBI) |
| **Interface de Coleta** | NCBI E-utilities (`esearch` e `efetch` em XML/JSON) |
| **Consulta Utilizada** | `("Coffee"[MeSH Terms] OR coffee[Title/Abstract]) AND ("Prostatic Neoplasms"[MeSH Terms] OR "prostate cancer"[Title/Abstract])` |
| **Ordenação da Coleta** | Relevância padrão do PubMed (*Best Match*) |
| **Timestamp UTC** | `2026-09-28T11:45:37.295122+00:00` |
| **Arquivo Snapshot** | `data/pubmed_cafe_cancer_prostata.csv` |
| **Arquivo de Metadados** | `data/pubmed_cafe_cancer_prostata_metadata.json` |
| **Script de Execução** | `notebooks/16_eda_pubmed.ipynb` |

### Limitações Metodológicas Declaradas
1. A ordenação por relevância do PubMed é algorítmica e reflete termos de indexação e atualidade, não equivalendo a uma amostragem probabilística nem a um censo de toda a literatura biomédica.
2. A análise inicial de títulos é um indicador preliminar de escopo e não substitui a leitura estruturada dos abstracts e dos textos integrais (obtidos pelo PMC).
3. A frequência de termos indica vocabulário recorrente, não expressando isoladamente se o estudo suporta ou contradiz a hipótese investigada.

---

## 3. Dicionário de Dados

| Campo | Tipo | Descrição | Preenchimento | Observação no Pipeline ArtFact |
|---|---|---|---|---|
| `pmid` | String | Identificador numérico único no PubMed | 100% (100/100) | Chave primária canônica para rastreabilidade de citações |
| `title` | String | Título completo da publicação | 100% (100/100) | Insumo para indexação lexical e semântica |
| `journal` | String | Nome normalizado do periódico científico | 100% (100/100) | Avaliação de proveniência editorial |
| `publication_date`| String | Data original registrada na NLM | 100% (100/100) | Registro cronológico original |
| `year` | Inteiro | Ano extraído da publicação (AAAA) | 100% (100/100) | Filtro de atualidade e análise de evolução temporal |
| `author_count` | Inteiro | Quantidade total de autores listados | 100% (100/100) | 2 registros apresentam valor 0 (autoria institucional/ausente) |
| `first_author` | String | Primeiro autor citado (Sobrenome e Iniciais) | 98% (98/100) | Rastreabilidade acadêmica formal |
| `doi` | String | Digital Object Identifier | 93% (93/100) | Interoperabilidade e resolução externa de links |
| `url` | String | Link canônico HTTPS no portal PubMed | 100% (100/100) | Proveniência apresentada na interface do usuário |

---

## 4. Análise Exploratória e Métricas Estatísticas

### 4.1 Completude e Qualidade Cadastral
```text
PMID:             [====================] 100% (100/100)
Título:           [====================] 100% (100/100)
Periódico:        [====================] 100% (100/100)
Ano:              [====================] 100% (100/100)
URL Oficial:      [====================] 100% (100/100)
Primeiro Autor:   [===================.]  98% (98/100)
DOI:              [==================..]  93% (93/100)
```

### 4.2 Estatísticas Descritivas de Autoria e Métricas Temporais

| Métrica | Ano de Publicação (`year`) | Contagem de Autores (`author_count`) |
|---|---|---|
| **Média** | 2013,8 | 7,4 |
| **Desvio Padrão** | 9,8 anos | 5,8 autores |
| **Mínimo** | 1964 | 0 (autoria ausente) |
| **1º Quartil (Q1 - 25%)** | 2011 | 4,0 |
| **Mediana (Q2 - 50%)** | 2016 | 6,0 |
| **3º Quartil (Q3 - 75%)** | 2021 | 9,0 |
| **Máximo** | 2026 | 32 autores |

**Interpretação:**
- Mais de 75% dos artigos do corpus foram publicados a partir de 2011, assegurando que o estudo de caso se debruce sobre literatura contemporânea com designs de estudos mais modernos (meta-análises de coortes prospectivas e padronização de doses).
- A contagem de autores apresenta mediana de 6 autores por publicação, típica de consórcios internacionais e estudos epidemiológicos multicêntricos.

### 4.3 Triagem Conceitual nos Títulos
A análise de coocorrência de termos-chave nos títulos revela:
- **Café + Próstata:** 39 títulos mencionam expressamente ambos os elementos (ex.: *"Coffee consumption and prostate cancer risk: a meta-analysis"*).
- **Apenas Próstata:** 42 títulos mencionam próstata sem citar café no título (investigam fatores dietéticos amplos, onde o café é uma das variáveis internas do estudo).
- **Apenas Café:** 7 títulos mencionam café sem focar exclusivamente na próstata (tratam de múltiplos sítios de neoplasias).
- **Nenhum no título:** 12 títulos não possuem os termos exatos, tendo sido capturados via vocabulário controlado MeSH (*Medical Subject Headings*) no abstract.

Essa constatação justifica a necessidade do pipeline híbrido (BM25 + vetores densos), pois uma busca puramente léxica pelo título descartaria estudos relevantes que abordam o café em tabelas ou seções internas do resumo.

---

## 5. Periódicos com Maior Concentração de Estudos

Os periódicos mais representados no corpus selecionado são:
1. *International Journal of Cancer* (11 artigos)
2. *Cancer Causes & Control* (8 artigos)
3. *European Journal of Clinical Nutrition* (6 artigos)
4. *Nutrients* (5 artigos)
5. *British Journal of Nutrition* (5 artigos)
6. *American Journal of Clinical Nutrition* (4 artigos)
7. *Cancer Epidemiology, Biomarkers & Prevention* (4 artigos)

A predominância de periódicos de alto fator de impacto na área de oncologia e epidemiologia nutricional reforça a robustez do corpus para testes de confiabilidade.

---

## 6. Implicações para a Arquitetura da Versão 2.0 do ArtFact

1. **Prioridade para o Resumo e Texto Completo (PMC):** Como apenas 39% dos títulos contêm ambos os termos explicitamente, o pipeline do ArtFact v2.0 nunca baseia suas decisões somente no título. Ele decompõe os abstracts e textos completos do PMC em trechos granulares (*chunks* de ~60 a 90 palavras).
2. **Eliminação de Vereditos Categóricos:** A variedade de desfechos encontrados (efeito protetor modesto, ausência de efeito para câncer de baixo grau, ou efeito nulo após ajuste para tabagismo) demonstrou empiricamente a impossibilidade científica de emitir um carimbo de "Verdadeiro" ou "Falso". O ArtFact v2.0 adota uma matriz de relações (*SUPPORTS*, *CONTRADICTS*, *NEUTRAL*, *UNCERTAIN*) e tabela de evidências PICO.
3. **Respeito à Rastreabilidade:** Todos os trechos apresentados na tela do usuário devem manter citação literal e PMID rastreável, prevenindo que o LLM sintetize dados fictícios não ancorados nas fontes recuperadas.

---

## 7. Rastreabilidade no Código

- **Caderno de Análise:** `notebooks/16_eda_pubmed.ipynb`
- **Arquivo de Dados:** `data/pubmed_cafe_cancer_prostata.csv`
- **Metadados da Coleta:** `data/pubmed_cafe_cancer_prostata_metadata.json`
- **Módulo de Ingestão:** `src/fatofake/pubmed.py`
