# Organização da Equipe e Framework Scrum — Versão 2.0
**Projeto:** ArtFact — MVP PubMed/PMC Orientado a Evidências Científicas  
**Programa:** RES IA ELD UnB — Turma 1 | Grupo 08  
**Data:** Outubro de 2026  
**Autores:** Victor Barbosa da Silva, Keila Alves Ferreira, Thayná Gonçalves Dutra, João Vitor Carvalho Barbosa, Vinícius César Sena Torres, Ketlyn Karen Silva de Morais  
**Branch de Referência:** `refactor/pubmed-only-mvp`

---

## 1. Metodologia de Gestão Ágil

O projeto ArtFact é conduzido utilizando o framework **Scrum**, adaptado para o contexto de pesquisa e desenvolvimento em inteligência artificial e engenharia de software biomédica.

### 1.1 Pilares Fundamentais na Prática da v2.0
- **Transparência:** Todos os impedimentos técnicos (tais como limites de requisição da API do NCBI, latência na geração de embeddings e eventuais erros 429 na API Gemini) foram catalogados abertamente em branches de teste, notebooks de validação e logs estruturados.
- **Inspeção:** O progresso do software foi validado continuamente não apenas por testes unitários clássicos, mas por métricas objetivas de Recuperação da Informação (Precision@k, Recall@k, MRR, nDCG@k) e integridade de citações (*literal quotation matching*).
- **Adaptação:** A decisão crucial de pivotar da Versão 1.0 (múltiplas APIs não confiáveis) para a Versão 2.0 (`refactor/pubmed-only-mvp`) resultou diretamente das cerimônias de retrospectiva e inspeção técnica da equipe.

---

## 2. Atribuição de Papéis e Responsabilidades (v2.0)

| Integrante | Papel Scrum | Responsabilidades e Contribuições Efetivas na Versão 2.0 |
|---|---|---|
| **Vinícius César Sena Torres** | **Product Owner (PO) & Co-Lead de IA** | • Definição e priorização do Product Backlog com foco em valor científico e rastreabilidade.<br>• Decisão de negócio e arquitetura pela redução de escopo para a abordagem *PubMed-Only MVP*.<br>• Desenvolvimento do núcleo da **Inteligência Artificial (IA em si)**, conduzido **majoritariamente em parceria com João Vitor** (arquitetura RAG, embeddings, scripts de entrega do modelo e engenharia de prompts).<br>• Definição dos critérios de aceitação para o modo de Múltiplas Alegações e Comparação Manual. |
| **Thayná Gonçalves Dutra** | **Scrum Master (SM), Front-End, Acessibilidade & Co-Lead de Documentação** | • Facilitação dos rituais ágeis (Sprint Planning, Dailies, Sprint Review e Retrospectivas) e remoção proativa de impedimentos.<br>• Atuação direta no desenvolvimento de **Front-End** da aplicação.<br>• Responsável pela implementação e garantia das diretrizes de **acessibilidade** (a11y) e usabilidade inclusiva na interface web.<br>• Elaboração **majoritária de toda a documentação técnica, acadêmica e versionada** do projeto, conduzida em parceria com **Keila**.<br>• Monitoramento de fluxo da equipe e conformidade com os requisitos do programa RES IA ELD UnB. |
| **Keila Alves Ferreira** | **Desenvolvedora Front-End, UX & Co-Lead de Documentação** | • Concepção, arquitetura visual e desenvolvimento da interface web responsiva (desktop e mobile).<br>• Elaboração **majoritária de toda a documentação técnica, acadêmica e versionada** do projeto, conduzida em parceria com **Thayná**.<br>• Planejamento da experiência do usuário (UX) e estruturação do fluxo de navegação por abas (Fonte, Leitor, Evidências).<br>• Desenvolvimento do leitor científico interativo com marcação (*highlighting*) de trechos de origem das citações. |
| **João Vitor Carvalho Barbosa** | **Desenvolvedor Back-End, DevOps & Co-Lead de IA** | • Desenvolvimento do núcleo da **Inteligência Artificial (IA em si)**, conduzido **majoritariamente em parceria com Vinícius** (pipeline RAG híbrido, vetorização semântica Qdrant/MiniLM e orquestração).<br>• Configuração de conteinerização com **Docker** e `docker-compose` para reprodutibilidade de ambiente.<br>• Desenvolvimento e manutenção de componentes do **Back-End** e rotas da API REST.<br>• Integração com as E-utilities do NCBI (PubMed, PMC, Gene e ClinVar) e infraestrutura de observabilidade. |
| **Ketlyn Karen Silva de Morais** | **Desenvolvedora Full-Stack** | • Atuação técnica abrangente e contínua em ambas as frentes de código do sistema.<br>• Desenvolvimento de recursos de **Front-End** (telas, componentes visuais e integrações com o usuário).<br>• Desenvolvimento de regras de negócio e rotinas de **Back-End** (processamento de dados e suporte a endpoints). |
| **Victor Barbosa da Silva** | **QA Tester (Quality Assurance)** | • Atuação focada exclusivamente em **Garantia de Qualidade (QA)**.<br>• Planejamento, criação e execução da suíte de testes de ponta a ponta e testes de regressão (`tests/test_api.py`, `tests/test_pubmed_only_mvp.py`).<br>• Auditoria de casos de segurança, validação de integridade dos esquemas JSON e checagem de conformidade das regras de abstenção e artigos retratados. |

> **Nota de Atribuição Transversal:**  
> - **Desenvolvimento da Inteligência Artificial (IA em si):** A formulação dos modelos, estratégias RAG híbridas, prompts de extração PICO, ancoragem de passagens e testes de inferência foram realizados **majoritariamente por Vinícius César Sena Torres e João Vitor Carvalho Barbosa**.  
> - **Elaboração da Documentação do Projeto:** O levantamento, estruturação, redação acadêmica e versionamento de todos os artefatos documentais da Versão 1.0 e da Versão 2.0 foram realizados **majoritariamente por Thayná Gonçalves Dutra e Keila Alves Ferreira**.

---

## 3. Histórico de Sprints e Evolução do Projeto

### Sprint 1: Concepção, Guiding Questions e Pesquisa Exploratória
- **Objetivos:** Definir o problema de desinformação em saúde, formalizar as Guiding Questions iniciais e identificar datasets de suporte (BioASQ, PubMed).
- **Entregas:** Documento de Guiding Questions v1.0, especificação preliminar de requisitos e seleção do estudo de caso (associação entre café e câncer de próstata).

### Sprint 2: Prova de Conceito (PoC) e Análise Exploratória (EDA)
- **Objetivos:** Construir o pipeline inicial de ingestão e realizar a análise estatística completa do corpus do estudo de caso.
- **Entregas:** `fato_ou_fake_poc.ipynb`, `data/pubmed_cafe_cancer_prostata.csv` com 100 registros e `notebooks/16_eda_pubmed.ipynb` com gráficos de dispersão, métricas de autoria e distribuição temporal.

### Sprint 3: Avaliação de Múltiplas Fontes e Desafios de Integração
- **Objetivos:** Testar integração federada entre bases heterogêneas (OpenAlex, SciELO, Europe PMC, Crossref).
- **Desafios Identificados:** Diferenças profundas de esquemas de metadados, links quebrados em artigos de acesso aberto externos, inconsistência na cobertura e instabilidade de latência.
- **Retrospectiva:** Decisão unânime da equipe de revisar a arquitetura em direção a um núcleo estável e auditável.

### Sprint 4: Refatoração Estratégica (`refactor/pubmed-only-mvp`)
- **Objetivos:** Simplificação intencional do escopo em prol de robustez e integridade acadêmica.
- **Entregas:**
  - Isolamento estrito no ecossistema PubMed / PubMed Central (PMC);
  - Eliminação de classificações binárias de "verdadeiro/falso";
  - Implementação do ranking híbrido (BM25 + vetores semânticos com RRF);
  - Exclusão compulsória de artigos retratados da síntese.

### Sprint 5: Recursos Avançados de Usabilidade e Análise Granular
- **Objetivos:** Ampliar a capacidade investigativa do usuário sobre documentos científicos complexos.
- **Entregas:**
  - Módulo de extração atômica de múltiplas alegações por artigo (`notebooks/27`);
  - Módulo de Comparação Manual com até 20 referências dirigidas (`src/fatofake/manual_comparison.py`);
  - Biblioteca persistente em SQLite com busca textual via motor FTS5 (`src/fatofake/library.py`);
  - Leitor com texto completo e realce visual dos trechos citados.

### Sprint 6: Testes Finais, Observabilidade e Fechamento da v2.0
- **Objetivos:** Garantir confiabilidade operacional, monitoramento de produção e consolidação da documentação versionada.
- **Entregas:**
  - Configuração da pilha de observabilidade estruturada (`observability/` com Grafana, Loki e Alloy);
  - Suíte completa de testes de aceitação e contratos HTTP assíncronos;
  - Empacotamento Docker e documentação final versionada para a entrega acadêmica.

---

## 4. Cerimônias e Ferramentas Utilizadas

- **Repositório Git & Controle de Versão:** GitHub (`joaocarvv/r.ia-FakeNews`), ramificação por features e branch de consolidação `refactor/pubmed-only-mvp`.
- **Comunicação e Alinhamento:** Reuniões de Daily Scrum síncronas/assíncronas e sprints semanais de planejamento.
- **Ambiente de Testes e Desenvolvimento:** Python 3.11 gerenciado via `uv`, ambiente isolado `.venv`, SQLite e Docker para reprodutibilidade.
- **Monitoramento e Diagnóstico:** Grafana + Loki para ingestão de logs estruturados de cada etapa do pipeline RAG.
