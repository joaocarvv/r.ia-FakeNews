# Fato ou Fake? — MVP PubMed/PMC orientado a evidências

O fluxo principal definido para o MVP está documentado em [`docs/fluxo-mvp.md`](docs/fluxo-mvp.md).

O runtime desta branch usa somente o ecossistema da National Library of Medicine: pesquisa e metadados pelo PubMed e texto completo pelo PubMed Central (PMC), quando disponível. PDFs enviados pelo usuário continuam aceitos como documento de entrada. Integrações históricas com outras bases permanecem no código para preservar o trabalho anterior, mas não são instanciadas pela aplicação.

A aplicação não declara que um artigo é verdadeiro ou falso. O modelo organiza
trechos citáveis e descreve relações textuais. O MVP apresenta metadados estruturados
com sua origem e dados extraídos literalmente do texto, com trechos de referência.
Campos sem respaldo são omitidos; cobertura e limites da leitura continuam visíveis.
`PublicationType` é apresentado como tipo de publicação informado pelo PubMed,
não como confirmação independente do desenho do estudo. O MVP não atribui nota de
qualidade, risco de viés ou certeza metodológica, mesmo que uma configuração antiga
contenha `ASSESS_METHODOLOGY=true`. Resumos narrativos são produzidos pelo modelo;
a localização literal de uma citação não valida sua interpretação científica.

## Escopo desta branch

- Várias alegações no mesmo artigo: seleção em lote, navegação durante a pesquisa,
  resultados por alegação e novas rodadas sem reler a fonte nem apagar as demais.
  Também é possível adicionar alegações próprias, identificadas como conteúdo do usuário.
- Comparação manual com até 20 referências: artigos da biblioteca, PMIDs, links do
  PubMed, DOIs indexados e PDFs. Esse modo usa somente os documentos escolhidos,
  registra a seleção por alegação e rejeita a comparação do artigo contra si próprio.
- Biblioteca local persistente no SQLite: guarda texto disponível, arquivos enviados, metadados,
  análises vinculadas, notas e etiquetas. A busca consulta título, texto e notas/etiquetas
  com FTS5. A biblioteca pertence à instalação; autenticação e bibliotecas por conta
  ainda não fazem parte do MVP. Não há índice FAISS nesta implementação.


- Interface organizada em fonte, leitura e evidências, com abas para tema, referência
  e arquivo. O resultado começa pelo resumo e pelos trechos; detalhes adicionais
  ficam em seções expansíveis. O layout funciona em desktop e celular.
- Leitor com todo o texto disponível e trechos de origem destacados. Ao passar o
  mouse ou tocar, é possível selecionar, editar ou investigar a alegação.
  Quando só há resumo, a tela informa essa limitação; citações não localizadas
  permanecem na lista, sem destaque por aproximação.
- Busca por tema em português ou inglês: termos organizados por IA quando disponível,
  consultas exibidas ao usuário e resultados com opção de selecionar um artigo.
- Filtros opcionais para revisões sistemáticas/meta-análises e ensaios randomizados.
- Fonte de descoberta: PubMed.
- Texto integral automatizado: somente PMC.
- Fallback: abstract do PubMed, identificado na interface.
- Entrada opcional: PDF ou imagem enviados pelo usuário.
- Sem OpenAlex, SciELO, Europe PMC, Unpaywall, Semantic Scholar, Crossref, DataCite ou ClinicalTrials.gov no runtime.
- Sem avaliação automática de GRADE, RoB 2, ROBINS-I ou AMSTAR 2 no MVP.

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

Durante a análise de um artigo, cada alegação selecionada também pode acionar uma
consulta dinâmica ao NCBI Gene e ao ClinVar via E-utilities. Os registros aparecem
na seção **Pesquisa biomédica dinâmica** do resultado, separados da literatura do
PubMed/PMC. O endpoint auxiliar `POST /api/v1/structured-search` também aceita
`{"claim": "A variante BRCA1 c.5266dupC aumenta o risco de câncer de mama?"}` para
demonstrações isoladas. O retorno separa entidades detectadas, registros estruturados
e falhas por fonte; esses registros não geram sozinhos um veredito de verdadeiro ou
falso. As respostas ficam em cache em memória pelo período de
`STRUCTURED_SEARCH_CACHE_TTL`.

## Arquivos principais

<!-- Verificar todos os arquivos: Se continuam existindo, se ainda estamos os utilizando etc -->

- `fato_ou_fake_poc.ipynb`: notebook completo e salvo com uma execução de exemplo. <!-- Substituir esse notebook por um novo, visto que este está relacionado com o projeto antigo-->
- `notebooks/17_validacao_orquestracao_multiartigo.ipynb`: validação do serviço que parte da alegação, processa múltiplos artigos e gera o relatório final. 
- `notebooks/18_validacao_api_http.ipynb`: validação reproduzível do contrato HTTP assíncrono para iniciar e consultar análises.
- `notebooks/19_validacao_confiabilidade.ipynb`: benchmark inicial das regras de abstenção e exclusão de artigos retratados.
- `notebooks/20_validacao_pesquisa_adversarial.ipynb`: validação controlada do pesquisador, crítico e árbitro determinístico com checagem de proveniência.
- `notebooks/21_validacao_fontes_cientificas.ipynb`: auditoria ao vivo de acesso e papel das fontes científicas abertas, editoriais e manuais consideradas pelo grupo.
- `notebooks/22_validacao_busca_federada.ipynb`: validação da normalização, deduplicação, proveniência e ranking federado entre PubMed, OpenAlex e SciELO via OpenAlex. <!-- Atualizar esse notebook, visto que está incluindo OpenAlex e SciELO -->
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

<!-- Verificar todos os arquivos: Se continuam existindo, se ainda estamos os utilizando etc -->

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
git switch refactor/pubmed-only-mvp
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

<!-- Verificar todas as variáveis: Se continuam existindo, se ainda estamos os utilizando etc -->

| Variável | Obrigatória | Valor padrão | Finalidade |
|---|---:|---|---|
| `GEMINI_API_KEY` | Recomendada | vazio | Autentica a análise, classificação e síntese com Gemini. Sem ela, o notebook usa o fallback local. |
| `LLM_MODEL` | Não | `gemini-flash-lite-latest` | Modelo Gemini usado pelo endpoint REST. Troque somente por um modelo disponível na sua conta. |
| `ASSESS_METHODOLOGY` | Não | `false` | Configuração legada; ignorada pelo MVP, que apresenta somente dados rastreáveis. |
| `EMBEDDING_MODEL` | Não | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Modelo local multilíngue usado na busca semântica. |
| `TRANSLATION_MODEL` | Não | `Helsinki-NLP/opus-mt-ROMANCE-en` | Modelo local preferido para traduzir consultas. Se os pacotes locais não estiverem instalados e houver chave Gemini, a tradução usa o Gemini; nenhum dos dois produz o veredito. |
| `NCBI_API_KEY` | Não | vazio | Aumenta o limite da API do NCBI. A POC funciona sem essa chave. |
| `NCBI_EMAIL` | Recomendada | vazio | Identifica o responsável pelas chamadas ao NCBI. Use um e-mail de contato válido. |
| `MAX_SOURCES` | Não | `8` | Máximo de publicações recuperadas por claim. |
| `CHUNK_WORDS` | Não | `60` | Tamanho aproximado de cada chunk em palavras. |
| `CHUNK_OVERLAP` | Não | `12` | Sobreposição entre chunks consecutivos. Deve ser menor que `CHUNK_WORDS`. |
| `TOP_K` | Não | `6` | Número máximo de trechos enviados à classificação. |
| `HTTP_TIMEOUT` | Não | `20` | Timeout, em segundos, para APIs e páginas externas. |
| `STRUCTURED_SEARCH_CACHE_TTL` | Não | `300` | Tempo, em segundos, do cache local das consultas dinâmicas ao NCBI Gene e ClinVar. |
| `LLM_TIMEOUT` | Não | `120` | Timeout, em segundos, para uma chamada Gemini. |
| `LLM_MAX_ATTEMPTS` | Não | `3` | Tentativas para erros temporários `429`, `5xx` e falhas de rede da Gemini. |
| `LLM_RETRY_BACKOFF` | Não | `1` | Espera exponencial inicial, em segundos, entre tentativas da Gemini. |
| `DOCUMENT_MAX_PAGES` | Não | `100` | Limite de páginas processadas localmente pelo LiteParse. |
| `DOCUMENT_PARSE_TIMEOUT` | Não | `45` | Limite, em segundos, para interpretar um documento local. |

<!-- Verificar todas as variáveis: Se continuam existindo, se ainda estamos os utilizando etc -->

Exemplo completo:

```dotenv
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
TRANSLATION_MODEL=Helsinki-NLP/opus-mt-ROMANCE-en
GEMINI_API_KEY=cole_sua_chave_aqui
LLM_MODEL=gemini-flash-lite-latest
ASSESS_METHODOLOGY=false
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

<!-- Atualizar o notebook abaixo para que seja correspondente ao exemplo -->

```powershell
.venv/Scripts/python.exe -m jupyter lab fato_ou_fake_poc.ipynb
```

No Linux ou macOS:

```bash
.venv/bin/python -m jupyter lab fato_ou_fake_poc.ipynb
```

No VS Code:

<!-- Atualizar arquivos -->

1. Abra `fatofake.code-workspace`.
2. Abra `fato_ou_fake_poc.ipynb`.
3. Selecione o interpretador `.venv` como kernel.
4. Use **Restart Kernel and Run All Cells**.

Para executar e salvar todas as saídas pelo terminal:

<!-- Atualizar arquivos -->

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
   e trechos citáveis. Com a triagem metodológica ativa, a tabela também mostra
   comparabilidade PICO, risco de viés por domínio, peso e certeza estimada; esses
   campos não substituem a aplicação humana dos instrumentos formais.

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

### Recuperação vetorial persistente (opcional)

SQLite continua guardando biblioteca, PDFs, notas e análises. Qdrant guarda os
embeddings e os chunks rastreáveis para reutilização, inclusive após reiniciar.
PubMed/PMC, parsing, Gemini/NLI, citações e síntese permanecem no pipeline atual.
FAISS não é necessário para esta implementação.

O padrão é `VECTOR_STORE_BACKEND=memory` e `HYBRID_RETRIEVAL_ENABLED=false`: a web
continua com BM25, sem carregar embeddings nem conectar um serviço vetorial.
`ScientificArticleProcessor` mantém o híbrido em memória já existente e aceita
um backend de chunks opcional por injeção de dependência.

Para ativar Qdrant local em desenvolvimento, instale `requirements.txt` e configure:

```dotenv
VECTOR_STORE_BACKEND=qdrant
HYBRID_RETRIEVAL_ENABLED=true
QDRANT_PATH=data/qdrant
EMBEDDING_REVISION=v1
VECTOR_STORE_FAILURE_MODE=error
```

O cliente local atende um processo. Para usar o serviço opcional do Compose:

```bash
docker compose --profile vector up -d qdrant
```

Configure `QDRANT_URL=http://localhost:6333` para um app no host, ou
`QDRANT_URL=http://qdrant:6333` para o app no Compose. A URL substitui o modo local.
O serviço usa a versão [Qdrant v1.19.2](https://github.com/qdrant/qdrant/releases/tag/v1.19.2),
porta publicada somente em loopback e volume persistente. Não é iniciado pelo perfil padrão.
`QDRANT_API_KEY` é opcional no cliente; quando usada, o servidor deve ter a configuração
correspondente. Nenhuma credencial é fornecida pelo projeto.

A collection combina prefixo, hash do modelo, revisão e schema; sua dimensão e
métrica Cosine são validadas. Troque `EMBEDDING_REVISION` ao mudar os pesos do modelo.
Texto, seção, página, URL, identificadores e versões do parser/chunker participam
da identidade do ponto. Upsert repetido não duplica o chunk nem recalcula seu vetor.
O payload mantém Unicode e permite reconstruir `EvidenceChunk`. Os textos exibidos
são os mesmos chunks persistidos. Não há normalização adicional para embedding.

BM25 e busca vetorial são combinados por RRF. O índice persistente só recupera os
chunks autorizados daquele documento; ambos os rankings recebem o mesmo escopo.
Ranking, contribuições e score são auditáveis, sem representar confiança científica.
`VECTOR_TOP_K`, `VECTOR_MIN_SCORE`, `QDRANT_COLLECTION_PREFIX` e `QDRANT_TIMEOUT`
controlam a recuperação. O modelo local é carregado na primeira busca; seus arquivos
podem ser baixados por Sentence Transformers se ausentes no cache.

Falhas de Qdrant, configuração ou embeddings geram erro explícito por padrão.
Somente `VECTOR_STORE_FAILURE_MODE=bm25` autoriza retorno ao BM25, registrado em
logs, nos trechos e nas ressalvas do resultado. Nenhum modelo alternativo é escolhido.
Para voltar ao comportamento padrão, use `VECTOR_STORE_BACKEND=memory` e
`HYBRID_RETRIEVAL_ENABLED=false`. Para híbrido sem persistência, use `memory` e `true`.
O alias antigo `VECTOR_BACKEND` é aceito quando a nova variável não está definida;
a busca híbrida sempre depende de `HYBRID_RETRIEVAL_ENABLED`.

A biblioteca continua com pesquisa textual FTS5. Vetores são indexados sob demanda
nas comparações. Recuperação vetorial não é treinamento de um modelo; o produto
não possui classificador supervisionado de fake news. ANN, limites de candidatos,
empates e limiares podem afetar o ranking. Um limiar zero pode recuperar trechos
sem relevância; resultados continuam sujeitos à checagem de citações e abstinência.

Avaliação offline, sem Gemini e com vetores controlados:

```bash
PYTHONPATH=src .venv/bin/python -m fatofake.retrieval_evaluation --output artifacts/retrieval-evaluation.json
```

Para avaliar o modelo real, escolha explicitamente `--encoder sentence-transformers`.
O relatório compara BM25, semântico em memória, híbrido em memória, Qdrant e híbrido
Qdrant; registra recall@k, precision@k, MRR, nDCG e abstinência da recuperação.
Os helpers de citações/groundedness verificam estrutura, sem medir verdade científica.
Não foram executadas respostas Gemini/NLI nessa avaliação.

Detalhes, limites, baseline e decisões estão em [recuperacao-vetorial.md](docs/recuperacao-vetorial.md).
As interfaces usam a documentação oficial do [cliente Qdrant](https://github.com/qdrant/qdrant-client)
e de [systemInstruction do Gemini](https://ai.google.dev/api/generate-content).

A comparação operacional de BM25, semântico, híbrido e MedCPT sem conjunto ouro
está documentada em [recuperação vetorial](docs/recuperacao-vetorial.md#experimento-operacional-sem-conjunto-ouro).
O reranker MedCPT pode ser habilitado com `MEDCPT_SHADOW_ENABLED=true`; o padrão
preserva o baseline e não carrega o modelo. Sem rótulos, o experimento mede tempo,
reutilização e mudanças de ranking, sem estimar melhoria de relevância.

Na aba **Pesquisar por tema**, os resultados do PubMed agora mostram clusters
BERTopic: mapa dos artigos, termos de cada tema e botões que filtram a lista.
O cálculo acontece depois da busca, sem bloquear a exibição dos artigos. Os grupos
usam os **títulos da página atual**, não todos os resultados da consulta. Ao trocar
de página, os grupos são recalculados; números de tema são locais à página.
Artigos classificados como ruído pelo HDBSCAN aparecem em **Sem grupo definido**.
Com menos de quatro artigos, o painel informa que não há dados suficientes.

A rota `POST /api/v1/pubmed-clusters` recebe `articles` com `pmid` e `title`
(até 100 artigos). O backend usa Sentence Transformers multilíngue, PCA, HDBSCAN
e c-TF-IDF do BERTopic. `BERTOPIC_EMBEDDING_MODEL` permite configurar o encoder,
independentemente dos encoders MedCPT da recuperação. Há cache limitado de
embeddings e de resultados por processo; clusters não alteram o ranking PubMed.
Falhas do agrupamento mantêm os artigos disponíveis. O mapa é uma projeção em duas
dimensões; os temas não expressam relevância, qualidade ou concordância científica.
A [documentação do BERTopic](https://maartengr.github.io/BERTopic/getting_started/dim_reduction/dim_reduction.html)
descreve a integração de PCA como alternativa ao UMAP.

### Citações e comparação de bibliografias

Nos resultados de uma pesquisa concluída, a seção **Relações entre os artigos** permite consultar as referências reais via PubMed EFetch e PMC JATS, sem chamadas ao LLM. A consulta usa os artigos da alegação selecionada e inclui o artigo enviado quando há identificador; o conjunto exibido é limitado a 21 artigos. O PMC ID Converter pode resolver o DOI do artigo enviado.

O botão **Verificar referências** mostra ligações direcionais entre artigos, referências compartilhadas, bibliografias individuais e contextos literais de citações quando disponíveis no PMC. Identidade é confirmada somente por PMID, PMCID ou DOI; títulos semelhantes não criam ligações. A sobreposição Jaccard considera obras com identificadores reconhecidos. Bibliografias indisponíveis não são tratadas como listas vazias. Referências compartilhadas não demonstram dependência entre estudos.

`POST /api/v1/analyses/<analysis_id>/references` recebe `{"claim_id":"…","refresh":false}`. Em análises com várias alegações, informe `claim_id`. Os artigos são lidos do resultado salvo no servidor. A comparação é persistida em `reference_comparison`, reaberta com a análise e reutilizada enquanto o conjunto de artigos não mudar. **Atualizar referências** consulta novamente as fontes, inclusive quando a cobertura anterior foi parcial.
