# Requisitos Funcionais e Não Funcionais — Versão 2.0
**Projeto:** ArtFact — Verificação de Alegações de Saúde com IA  
**Grupo:** 08  
**Data:** Outubro de 2026  
**Branch de referência:** `refactor/pubmed-only-mvp`

---

## 1. Visão Geral da Evolução

A Versão 2.0 representa uma **redução de escopo intencional** — o sistema abandona a ambição de integrar múltiplas bases científicas e foca em entregar uma pipeline auditável, rastreável e confiável, usando exclusivamente o ecossistema do NCBI/NLM (PubMed + PMC).

---

## 2. Requisitos Funcionais

### RF01 — Entrada de Alegação e Artigo
- O sistema deve aceitar uma alegação de saúde em texto livre (português ou inglês).
- O sistema deve aceitar PMID, DOI, link de artigo PubMed ou PDF/imagem como entrada opcional.
- A entrada deve ser validada antes do processamento.
- **Comprovação:** `notebooks/01_validacao_entrada.ipynb`

### RF02 — Preparação e Planejamento de Busca
- O sistema deve estruturar a alegação em termos de busca científica.
- Quando disponível, deve usar IA (Gemini) para expandir e organizar os termos; sem chave, a consulta original é preservada.
- **Comprovação:** `notebooks/02_validacao_plano_busca.ipynb`

### RF03 — Busca no PubMed
- O sistema deve consultar o PubMed via NCBI E-utilities e normalizar os artigos encontrados.
- Deve suportar filtros opcionais por tipo de artigo: revisões sistemáticas/meta-análises (`REVIEWS`) e ensaios randomizados (`TRIALS`).
- Devem ser apresentados até 10 resultados potencialmente relacionados.
- **Comprovação:** `notebooks/03_validacao_pubmed.ipynb`

### RF04 — Recuperação de Texto Completo (PMC)
- O sistema deve obter o texto completo de artigos disponíveis no PubMed Central.
- Quando apenas o abstract estiver disponível, o sistema deve informar isso ao usuário.
- **Comprovação:** `notebooks/05_validacao_conteudo_pmc.ipynb`

### RF05 — Chunking e Recuperação de Evidências
- O sistema deve dividir o conteúdo em trechos rastreáveis.
- Deve suportar recuperação lexical (BM25) e semântica (embeddings multilíngues).
- Deve combinar os dois métodos em um ranking híbrido.
- **Comprovação:** `notebooks/06_validacao_chunking.ipynb`, `07`, `08`, `09`

### RF06 — Extração e Classificação de Evidências
- O sistema deve extrair afirmações científicas rastreáveis dos trechos.
- Deve classificar cada par (trecho × alegação) como: apoio, contradição, neutro ou incerto.
- Deve preservar probabilidades, modelo, justificativa e proveniência.
- **Comprovação:** `notebooks/10_validacao_extracao_evidencias.ipynb`, `11`

### RF07 — Síntese de Evidências
- O sistema deve agregar as classificações por artigo e entre artigos.
- Artigos retratados devem ser excluídos da síntese e identificados na interface.
- **Comprovação:** `notebooks/12_validacao_sintese_evidencias.ipynb`, `19`

### RF08 — Resposta Explicável ao Usuário
- O sistema deve gerar uma resposta estruturada separando: sinal, força da evidência, limitações e fontes.
- Campos sem respaldo no texto devem ser omitidos.
- **Comprovação:** `notebooks/15_validacao_resposta_explicavel.ipynb`

### RF09 — Múltiplas Alegações
- O sistema deve suportar várias alegações do mesmo artigo em lote.
- Cada alegação deve ser processada independentemente.
- **Comprovação:** `notebooks/27_validacao_multiplas_alegacoes.ipynb`

### RF10 — Comparação Manual com Referências
- O sistema deve permitir comparação manual com até 20 referências (artigos da biblioteca, PMIDs, links, DOIs, PDFs).
- Deve rejeitar a comparação do artigo contra si próprio.
- **Comprovação:** Módulo `src/fatofake/manual_comparison.py`

### RF11 — Biblioteca Local Persistente
- O sistema deve manter uma biblioteca local em SQLite com texto, metadados, análises, notas e etiquetas.
- A busca deve usar FTS5 (Full-Text Search).
- **Comprovação:** Módulo `src/fatofake/library.py`

### RF12 — Interface Web
- A interface deve estar organizada em abas: fonte, leitura e evidências.
- Deve funcionar em desktop e celular.
- Deve incluir leitor com trechos de origem destacados.
- **Comprovação:** `src/fatofake/web_ui.py`, `src/fatofake/static/`

### RF13 — API HTTP Assíncrona
- O sistema deve expor uma API REST com: contrato de entrada, consulta de progresso, resultado estruturado e erros seguros.
- Endpoint de busca temática: `POST /api/v1/pubmed-search`
- Endpoint de busca biomédica: `POST /api/v1/structured-search`
- **Comprovação:** `notebooks/18_validacao_api_http.ipynb`

### RF14 — Busca Biomédica Dinâmica (NCBI Gene / ClinVar)
- Durante a análise, o sistema deve acionar consultas ao NCBI Gene e ClinVar para alegações com entidades biomédicas.
- Os resultados devem aparecer separados da literatura PubMed/PMC.
- **Comprovação:** `notebooks/03_validacao_pubmed.ipynb`, `src/fatofake/structured_sources.py`

### RF15 — Busca por Tema
- O sistema deve aceitar busca por tema em português ou inglês.
- Deve apresentar os termos organizados pela IA ao usuário.
- **Comprovação:** Módulo `src/fatofake/topic_search.py`

---

## 3. Requisitos Não Funcionais

### RNF01 — Rastreabilidade e Auditabilidade
- Todos os dados apresentados ao usuário devem ter proveniência explícita (seção e fonte).
- Dados sem citação localizável no texto devem ser omitidos.
- A cobertura da leitura deve permanecer visível ao usuário.

### RNF02 — Confiabilidade, Abstenção e Integridade Editorial
- O sistema não deve produzir conclusão quando as evidências forem inteiramente incertas.
- Artigos com retratação confirmada (decorrentes de falhas metodológicas ou de investigações de fraudes em *paper mills* e periódicos predatórios) não devem contribuir para a síntese e devem ser destacados com alerta de integridade na interface.
- O sistema deve priorizar fontes biomédicas curadas (NLM/PubMed/PMC) para mitigar a infiltração de manuscritos predatórios no contexto de análise da IA.
- **Comprovação:** `notebooks/19_validacao_confiabilidade.ipynb`

### RNF03 — Neutralidade e Não Veredito
- O sistema **não deve declarar** que um artigo é verdadeiro ou falso.
- Não deve atribuir nota de qualidade, risco de viés ou certeza metodológica automaticamente.
- `ASSESS_METHODOLOGY=true` é uma configuração legada **ignorada** pelo MVP.

### RNF04 — Desempenho
- O sistema deve suportar timeout configurável para chamadas externas (`HTTP_TIMEOUT`, padrão 20s).
- O sistema deve suportar retry com backoff exponencial para o LLM (`LLM_MAX_ATTEMPTS`, `LLM_RETRY_BACKOFF`).
- Respostas de busca biomédica devem ser cacheadas em memória (`STRUCTURED_SEARCH_CACHE_TTL`, padrão 300s).

### RNF05 — Observabilidade
- O sistema deve registrar logs estruturados.
- Deve suportar integração com Grafana + Loki via Grafana Alloy.
- **Comprovação:** `observability/`, `src/fatofake/structured_logging.py`

### RNF06 — Portabilidade
- O sistema deve suportar execução via Docker.
- Deve funcionar em Windows (PowerShell) e Linux/macOS.
- **Comprovação:** `Dockerfile`, `docker-compose.yml`

### RNF07 — Segurança de Dados
- A chave de API Gemini não deve ser versionada (`.gitignore`).
- O banco de dados local pertence à instalação; autenticação por conta não faz parte do MVP.

### RNF08 — Escalabilidade de Escopo
- O código das integrações removidas do runtime (OpenAlex, SciELO, etc.) deve ser preservado para reativação futura.
- O entrypoint `create_live_retrieval_app` deve delegar ao factory `create_pubmed_only_app`.

### RNF09 — Fallback sem LLM
- O sistema deve funcionar sem a chave Gemini, usando modelo NLI local e síntese extrativa.
- As fontes de dados continuam sendo reais — sem simulação de dados.

### RNF10 — Banco de Dados
- O banco padrão da v2.0 é `data/analysis-jobs-pubmed.sqlite3`.
- Relatórios anteriores permanecem em `analysis-jobs.sqlite3`.
- Uma configuração explícita de `JOB_DATABASE_PATH` é respeitada.

---

## 4. Requisitos Removidos/Suspensos da v1.0

| Requisito | Motivo da Remoção |
|---|---|
| GRADE / RoB 2 / ROBINS-I / AMSTAR 2 automáticos | Fora do escopo do MVP |
| Integração com OpenAlex, SciELO, Europe PMC | Removidos do runtime |
| Avaliação PICO comparativa | Fora do escopo do MVP |
| Treinamento supervisionado com ground truth | Pendente para versão futura |
| Autenticação e bibliotecas por conta | Fora do escopo do MVP |

---

## 5. Configurações de Parâmetros

| Variável | Padrão | Finalidade |
|---|---|---|
| `GEMINI_API_KEY` | vazio | Autenticação LLM |
| `LLM_MODEL` | `gemini-flash-lite-latest` | Modelo Gemini |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Embeddings semânticos |
| `TRANSLATION_MODEL` | `Helsinki-NLP/opus-mt-ROMANCE-en` | Tradução local |
| `MAX_SOURCES` | 8 | Máx. publicações por alegação |
| `CHUNK_WORDS` | 60 | Tamanho do chunk em palavras |
| `CHUNK_OVERLAP` | 12 | Sobreposição entre chunks |
| `TOP_K` | 6 | Trechos enviados à classificação |
| `LLM_TIMEOUT` | 120 | Timeout do Gemini (s) |
| `LLM_MAX_ATTEMPTS` | 3 | Tentativas em erros 429/5xx |
