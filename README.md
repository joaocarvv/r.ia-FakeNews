# Fato ou Fake? — MVP PubMed/PMC orientado a evidências

O fluxo principal definido para o MVP está documentado em [`docs/fluxo-mvp.md`](docs/fluxo-mvp.md).

O runtime desta branch usa somente o ecossistema da National Library of Medicine: pesquisa e metadados pelo PubMed e texto completo pelo PubMed Central (PMC), quando disponível. PDFs enviados pelo usuário continuam aceitos como documento de entrada. Integrações históricas com outras bases permanecem no código para preservar o trabalho anterior, mas não são instanciadas pela aplicação.

A aplicação não declara que um artigo é verdadeiro, falso ou metodologicamente confiável. O modelo organiza trechos citáveis e descreve relações textuais; desenho, amostra, população e transparência são apresentados apenas quando explicitamente encontrados. Risco de viés, adequação metodológica e validade das conclusões ficam marcados como não avaliados automaticamente.

## Escopo desta branch

- Busca por tema em português ou inglês: termos organizados por IA quando disponível,
  consultas exibidas ao usuário e resultados com opção de selecionar um artigo.
- Filtros opcionais para revisões sistemáticas/meta-análises e ensaios randomizados.
- Fonte de descoberta: PubMed.
- Texto integral automatizado: somente PMC.
- Fallback: abstract do PubMed, identificado na interface.
- Entrada opcional: PDF ou imagem enviados pelo usuário.
- Sem OpenAlex, SciELO, Europe PMC, Unpaywall, Semantic Scholar, Crossref, DataCite ou ClinicalTrials.gov no runtime.
- Sem pontuação automática de qualidade, GRADE, RoB 2, ROBINS-I ou AMSTAR 2.

O entrypoint `create_live_retrieval_app` delega ao factory `create_pubmed_only_app`.
PMID, DOI e links de artigo do PubMed são aceitos; referências sem conteúdo
recuperável no PubMed/PMC pedem o PDF, sem navegação do LLM. Dados factuais da
tabela de comparação são conservados somente se encontrados literalmente nos
trechos fornecidos, com seção e fonte. Isso não valida a interpretação científica.
O classificador continua sendo o Gemini; treinamento supervisionado e avaliação
com ground truth não foram implementados nesta redução de escopo.

O banco padrão desta branch é `data/analysis-jobs-pubmed.sqlite3`, preservando os
relatórios anteriores em `analysis-jobs.sqlite3`. Uma configuração explícita de
`JOB_DATABASE_PATH` continua sendo respeitada.

A busca temática usa `POST /api/v1/pubmed-search` com
`{"topic": "exercício e diabetes", "article_type": "ALL"}`. `article_type` aceita
`ALL`, `REVIEWS` ou `TRIALS`. A IA só formula consultas; títulos, PMIDs e metadados
vêm do PubMed. Sem chave ou se a expansão falhar, a consulta original continua
disponível. São apresentados até dez artigos potencialmente relacionados, sem
avaliação de qualidade metodológica. Ao selecionar um resultado, o formulário de
análise é preenchido; a análise só começa após clicar em “Verificar artigo”.

## Arquivos principais

- `fato_ou_fake_poc.ipynb`: notebook completo e salvo com uma execução de exemplo.
- `notebooks/17_validacao_orquestracao_multiartigo.ipynb`: validação do serviço que parte da alegação, processa múltiplos artigos e gera o relatório final.
- `notebooks/18_validacao_api_http.ipynb`: validação reproduzível do contrato HTTP assíncrono para iniciar e consultar análises.
- `notebooks/19_validacao_confiabilidade.ipynb`: benchmark inicial das regras de abstenção e exclusão de artigos retratados.
- `notebooks/20_validacao_pesquisa_adversarial.ipynb`: validação controlada do pesquisador, crítico e árbitro determinístico com checagem de proveniência.
- `notebooks/21_validacao_fontes_cientificas.ipynb`: auditoria ao vivo de acesso e papel das fontes científicas abertas, editoriais e manuais consideradas pelo grupo.
- `notebooks/22_validacao_busca_federada.ipynb`: validação da normalização, deduplicação, proveniência e ranking federado entre PubMed, OpenAlex e SciELO via OpenAlex.
- `notebooks/23_validacao_ingestao_liteparse.ipynb`: validação da leitura local de PDFs e da repetição segura de falhas temporárias do Gemini.
- `notebooks/24_validacao_verificacao_artigo.ipynb`: validação da busca relacionada, compatibilidade textual e índice de cobertura da verificação.
- `notebooks/25_validacao_texto_completo_rastreavel.ipynb`: validação da prioridade de texto completo, seções, tabelas e proveniência por página.
- `notebooks/26_validacao_saida_coerente.ipynb`: validação da narrativa consolidada, dos denominadores e da abstenção apresentada ao usuário.
- `notebooks/27_validacao_multiplas_alegacoes.ipynb`: validação da extração atômica, deduplicação e análise independente de várias alegações do mesmo artigo.
- `notebooks/28_validacao_indicadores_separados.ipynb`: validação da separação entre cobertura da busca, compatibilidade das evidências e confiança metodológica, sem percentual geral de verdade.
- `notebooks/29_validacao_ficha_artigo.ipynb`: validação da precedência determinística na classificação do desenho e da ficha auditável do artigo enviado.
- `notebooks/30_validacao_busca_expandida_reranking.ipynb`: validação da expansão rastreável por tema, vocabulário biomédico, revisões, DOI/autor e grafo científico, com reranking por cobertura conceitual.
- `notebooks/16_eda_pubmed.ipynb`: análise exploratória executada do corpus PubMed usado no estudo de caso.
- `data/pubmed_cafe_cancer_prostata.csv`: snapshot dos 100 registros analisados na EDA.
- `data/pubmed_cafe_cancer_prostata_metadata.json`: consulta, fonte, data e cobertura da coleta.
- `docs/EDA_PubMed_Grupo08.docx`: relatório acadêmico da EDA com tabelas, medidas de dispersão e gráficos incorporados.
- `build_notebook.py`: gerador reproduzível do notebook.
- `.env.example`: modelo das variáveis de ambiente.
- `requirements.txt`: dependências principais.
- `requirements-live.txt`: dependências principais mais Crawl4AI.

## Pré-requisitos

- Python 3.11.
- Git.
- Recomendado: [uv](https://docs.astral.sh/uv/getting-started/installation/) para criar e gerenciar o ambiente Python.
- Uma chave da API Gemini para usar a análise e a síntese por LLM.

O notebook também funciona sem Gemini: nesse caso, usa um modelo NLI local e uma síntese extrativa. As fontes continuam sendo reais; o projeto não substitui falhas de API por dados simulados.

## 1. Clonar e acessar a branch

```powershell
git clone https://github.com/joaocarvv/r.ia-FakeNews.git
cd r.ia-FakeNews
git switch fatofake
```

## 2. Criar o ambiente Python

No Windows com PowerShell:

```powershell
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

No Linux ou macOS:

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r requirements.txt
```

Na primeira execução, o `sentence-transformers` baixa os modelos abertos usados nos embeddings e no fallback local. Esse download pode demorar alguns minutos.

## 3. Criar a chave Gemini

1. Abra a página de [chaves do Google AI Studio](https://aistudio.google.com/app/apikey).
2. Entre com sua conta Google e aceite os termos, se solicitado.
3. Clique em **Create API key**.
4. Copie a chave criada.

Consulte também a [documentação oficial de chaves da Gemini API](https://ai.google.dev/gemini-api/docs/api-key). Nunca coloque a chave no notebook, no README ou no `.env.example`.

## 4. Criar e preencher o `.env`

Copie o arquivo de exemplo:

```powershell
Copy-Item .env.example .env
```

No Linux ou macOS:

```bash
cp .env.example .env
```

Abra o `.env` e preencha pelo menos:

```dotenv
GEMINI_API_KEY=cole_sua_chave_aqui
LLM_MODEL=gemini-flash-lite-latest
```

O `.env` está listado no `.gitignore` e não deve ser versionado.

### Variáveis disponíveis

| Variável | Obrigatória | Valor padrão | Finalidade |
|---|---:|---|---|
| `GEMINI_API_KEY` | Recomendada | vazio | Autentica a análise, classificação e síntese com Gemini. Sem ela, o notebook usa o fallback local. |
| `LLM_MODEL` | Não | `gemini-flash-lite-latest` | Modelo Gemini usado pelo endpoint REST. Troque somente por um modelo disponível na sua conta. |
| `EMBEDDING_MODEL` | Não | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Modelo local multilíngue usado na busca semântica. |
| `TRANSLATION_MODEL` | Não | `Helsinki-NLP/opus-mt-ROMANCE-en` | Traduz localmente a alegação em português para ampliar a busca científica em inglês; não produz o veredito. |
| `NCBI_API_KEY` | Não | vazio | Aumenta o limite da API do NCBI. A POC funciona sem essa chave. |
| `NCBI_EMAIL` | Recomendada | vazio | Identifica o responsável pelas chamadas ao NCBI. Use um e-mail de contato válido. |
| `MAX_SOURCES` | Não | `8` | Máximo de publicações recuperadas por claim. |
| `CHUNK_WORDS` | Não | `60` | Tamanho aproximado de cada chunk em palavras. |
| `CHUNK_OVERLAP` | Não | `12` | Sobreposição entre chunks consecutivos. Deve ser menor que `CHUNK_WORDS`. |
| `TOP_K` | Não | `6` | Número máximo de trechos enviados à classificação. |
| `HTTP_TIMEOUT` | Não | `20` | Timeout, em segundos, para APIs e páginas externas. |
| `LLM_TIMEOUT` | Não | `120` | Timeout, em segundos, para uma chamada Gemini. |
| `LLM_MAX_ATTEMPTS` | Não | `3` | Tentativas para erros temporários `429`, `5xx` e falhas de rede da Gemini. |
| `LLM_RETRY_BACKOFF` | Não | `1` | Espera exponencial inicial, em segundos, entre tentativas da Gemini. |
| `DOCUMENT_MAX_PAGES` | Não | `100` | Limite de páginas processadas localmente pelo LiteParse. |
| `DOCUMENT_PARSE_TIMEOUT` | Não | `45` | Limite, em segundos, para interpretar um documento local. |

Exemplo completo:

```dotenv
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
TRANSLATION_MODEL=Helsinki-NLP/opus-mt-ROMANCE-en
GEMINI_API_KEY=cole_sua_chave_aqui
LLM_MODEL=gemini-flash-lite-latest
NCBI_API_KEY=
NCBI_EMAIL=seu-email@exemplo.com
MAX_SOURCES=8
CHUNK_WORDS=60
CHUNK_OVERLAP=12
TOP_K=6
HTTP_TIMEOUT=20
LLM_TIMEOUT=120
```

## 5. Chave opcional do NCBI/PubMed

O PubMed pode ser consultado sem chave. Para limites maiores:

1. Crie ou acesse sua [conta NCBI](https://account.ncbi.nlm.nih.gov/).
2. Abra **Account Settings**.
3. Em **API Key Management**, selecione **Create an API Key**.
4. Preencha `NCBI_API_KEY` no `.env`.

A documentação das [E-utilities do NCBI](https://www.ncbi.nlm.nih.gov/books/NBK25497/#chapter2.API_Keys) explica os limites e recomenda informar `tool` e `email`. Nesta POC, a busca usa ESearch e EFetch da API oficial.

## 6. Abrir e executar o notebook

Pelo Jupyter Lab no Windows:

```powershell
.venv/Scripts/python.exe -m jupyter lab fato_ou_fake_poc.ipynb
```

No Linux ou macOS:

```bash
.venv/bin/python -m jupyter lab fato_ou_fake_poc.ipynb
```

No VS Code:

1. Abra `fatofake.code-workspace`.
2. Abra `fato_ou_fake_poc.ipynb`.
3. Selecione o interpretador `.venv` como kernel.
4. Use **Restart Kernel and Run All Cells**.

Para executar e salvar todas as saídas pelo terminal:

```powershell
.venv/Scripts/python.exe -m jupyter nbconvert --to notebook --execute --inplace fato_ou_fake_poc.ipynb --ExecutePreprocessor.timeout=300
```

## 7. Uso no código

Depois de executar as células de definição:

```python
resultado = verificar_claim("Tomar café causa câncer")
apresentar_resultado(resultado)
plot_evidence_map(resultado)
```

O retorno contém a claim, status, resumo, evidências, URLs, agregação, métricas, erros observados e os modelos usados.

### Teste web com artigos

Para abrir o protótipo que aceita link/DOI de artigo, PDF ou imagem:

```bash
.venv/bin/python run_acceptance_app.py
```

No Windows, use `.venv/Scripts/python.exe`. Depois, acesse
`http://127.0.0.1:5000`. PDFs são convertidos localmente pelo LiteParse antes da
extração das alegações; links do PubMed são resolvidos diretamente pelas APIs do
NCBI. Com `GEMINI_API_KEY` configurada, a aplicação primeiro gera um dossiê da
fonte principal: objetivo, pergunta de pesquisa, desenho, população, amostra,
métodos, resultados, conclusão, limitações, glossário e mapa das seções. Em PDFs,
as citações do dossiê são verificadas contra o texto extraído e associadas à página
quando possível. Depois, a aplicação extrai as principais alegações, busca evidências
independentes e valida os trechos citados nas fontes externas. A análise mede
compatibilidade, nunca declara o artigo verdadeiro ou falso.
Para links do PubMed, a recuperação combina busca temática e artigos relacionados
do ELink. O índice de confiança apresentado mede cobertura da verificação — textos
analisados, atualidade, citações e ramificação — e não a chance de o artigo estar correto.

#### Fluxo em três etapas

1. **Leitura do artigo.** O dossiê persistido (SQLite) traz texto por página e
   seção, tabelas e figuras (inventário determinístico das legendas + descrição do
   modelo), desenho, população, amostra, intervenção/exposição, comparador,
   desfechos, métodos estatísticos, resultados numéricos, conclusão dos autores,
   limitações declaradas pelos autores (separadas da leitura crítica),
   financiamento, conflitos de interesse e a cobertura real da leitura. Quando só
   há abstract ou metadados, a tela diz isso explicitamente.
2. **Revisão humana.** Cada alegação vira um cartão editável com afirmação
   normalizada, trecho literal com página/seção, tipo (causal, terapêutica,
   diagnóstica, prognóstica…), PICO e importância estimada. Texto editado é
   reestruturado (PICO e conceitos) antes da busca. O usuário escolhe busca rápida
   ou revisão profunda e vê tempo, tokens e custo estimados antes de investigar.
3. **Investigação.** As consultas são enviadas somente ao PubMed. Para cada PMID,
   o texto integral é obtido pelo PMC quando disponível; caso contrário, a análise
   fica explicitamente limitada ao abstract. A tabela copia informações factuais
   e trechos citáveis, sem atribuir risco de viés ou nota metodológica.

O resultado separa “não encontrado” de “não existe”, mostra a linha do tempo,
permite enviar o PDF de um estudo fechado e exporta o relatório em Markdown ou
pela impressão do navegador. Modelos, consultas, data e parâmetros ficam
registrados em `reproducibility`.

A aplicação não contorna paywalls: para artigos fechados, envie o PDF ao qual
você tem acesso.

#### Busca e recuperação

- **Fonte:** exclusivamente PubMed, com filtros Clinical Queries quando aplicáveis.
- **Texto integral:** exclusivamente PMC; na ausência, usa somente o abstract do
  PubMed e informa essa limitação.
- **Pesquisa complementar** (`POST /api/v1/analyses/<id>/claims/<claim>/complementary-search`):
  artigos relacionados no PubMed, consulta ampliada e termos em
  português; estudos indiretos e neutros são descartados.
- **Metodologia:** exibe apenas desenho declarado, amostra, população, intervenção,
  comparador, desfecho, registros e declarações encontradas no texto. Adequação do
  desenho, risco de viés e validade das conclusões não são avaliados automaticamente.
- **Prévias:** `GET /api/v1/analyses/<id>/source` devolve o texto lido do artigo
  enviado (por página/seção); a interface destaca os trechos de origem.

Chaves recomendadas: `NCBI_API_KEY` e `NCBI_EMAIL` para acesso estável às APIs do NCBI.

## 9. Executar com Docker e acompanhar logs no Grafana

A stack de desenvolvimento inclui a aplicação, Grafana, Loki e Grafana Alloy. Cada
requisição recebe um `request_id`, cada análise recebe um `analysis_id`, e as etapas
do pipeline emitem JSON estruturado com `stage`, `status`, `duration_ms`, contagens e
tipo de erro. Chaves de API e o texto integral dos documentos não são registrados.

Com Docker Desktop/Engine em execução:

```bash
docker compose up --build -d
docker compose ps
```

- aplicação: `http://127.0.0.1:5000`
- Grafana: `http://127.0.0.1:3000`
- saúde do Loki: `http://127.0.0.1:3100/ready`
- interface de diagnóstico do Alloy: `http://127.0.0.1:12345`

O login inicial do Grafana é `admin` / `admin`, a menos que
`GRAFANA_ADMIN_USER` e `GRAFANA_ADMIN_PASSWORD` sejam definidos no `.env`. O
datasource Loki e o dashboard **FatoFake — Execução e Logs** são provisionados
automaticamente. O dashboard permite filtrar por nível e `analysis_id`.

Comandos de operação:

```bash
docker compose logs -f app alloy loki grafana
docker compose down
# Remove também logs, modelos baixados e dados persistidos:
docker compose down -v
```

Os logs da aplicação são rotacionados em arquivos JSONL de 20 MB, com cinco
backups. O Loki mantém os dados por sete dias nesta configuração local.

## 10. Solução de problemas

### `401`, `403` ou chave inválida

- Confirme que `GEMINI_API_KEY` está no `.env` da raiz do projeto.
- Não use aspas nem espaços em torno da chave.
- Gere uma nova chave no [Google AI Studio](https://aistudio.google.com/app/apikey) se a anterior foi revogada ou exposta.

### `404` para o modelo Gemini

O catálogo da Gemini API muda ao longo do tempo. Atualize `LLM_MODEL` no `.env` para um modelo Flash disponível na sua conta. O padrão atual do projeto é `gemini-flash-lite-latest`.

### `429` ou `503` na Gemini API

A cota ou a capacidade temporária pode ter sido atingida. A aplicação repete a
chamada até `LLM_MAX_ATTEMPTS` vezes, com espera progressiva. Se todas falharem,
ela informa indisponibilidade temporária sem confundir essa falha com ausência de
alegação no artigo.

### PDF sem texto suficiente

O LiteParse trabalha localmente e usa OCR, mas documentos digitalizados, tabelas
densas, fórmulas e gráficos ainda podem exigir um parser mais avançado. A aplicação
interrompe a análise quando não há texto suficiente, em vez de fabricar conteúdo.

### Kernel ou imports não encontrados

Confirme que o notebook está usando o Python dentro de `.venv` e reinstale `requirements.txt` com o comando da seção 2.

### Crawl4AI não abre páginas

Execute o setup do Crawl4AI/Playwright e confirme que a página permite acesso automatizado. Paywalls, autenticação e bloqueios de crawler não são contornados.

## Limites da POC

Os resultados dependem da cobertura do PubMed e das páginas configuradas, da qualidade das consultas, da atualidade das fontes e da classificação automática. O `Evidence Score` é uma heurística sobre as evidências recuperadas, não uma probabilidade matemática de verdade. Toda conclusão relevante deve manter os trechos e URLs disponíveis para revisão humana.

O benchmark da etapa 19 é uma regressão de segurança com casos controlados. Ele não mede acurácia clínica; essa avaliação exige um conjunto ouro de casos reais revisados por especialistas.
