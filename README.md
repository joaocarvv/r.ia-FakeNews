# Fato ou Fake? — POC orientada a evidências

Jupyter Notebook executável para verificar afirmações pelo cruzamento de fontes reais. O pipeline analisa a claim, consulta o PubMed, normaliza e deduplica documentos, cria chunks, executa busca híbrida, classifica as evidências e gera uma síntese com as fontes utilizadas.

A aplicação não pede ao modelo que decida sozinho se algo é verdadeiro ou falso. O resultado descreve o conjunto recuperado como `EVIDENCE_SUPPORTS`, `EVIDENCE_AGAINST`, `INCONCLUSIVE` ou `CONFLICTING_EVIDENCE`.

## Arquivos principais

- `fato_ou_fake_poc.ipynb`: notebook completo e salvo com uma execução de exemplo.
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
| `NCBI_API_KEY` | Não | vazio | Aumenta o limite da API do NCBI. A POC funciona sem essa chave. |
| `NCBI_EMAIL` | Recomendada | vazio | Identifica o responsável pelas chamadas ao NCBI. Use um e-mail de contato válido. |
| `MAX_SOURCES` | Não | `8` | Máximo de publicações recuperadas por claim. |
| `CHUNK_WORDS` | Não | `60` | Tamanho aproximado de cada chunk em palavras. |
| `CHUNK_OVERLAP` | Não | `12` | Sobreposição entre chunks consecutivos. Deve ser menor que `CHUNK_WORDS`. |
| `TOP_K` | Não | `6` | Número máximo de trechos enviados à classificação. |
| `HTTP_TIMEOUT` | Não | `20` | Timeout, em segundos, para APIs e páginas externas. |
| `LLM_TIMEOUT` | Não | `120` | Timeout, em segundos, para uma chamada Gemini. |
| `WEB_URLS` | Não | vazio | URLs públicas adicionais, separadas por vírgula. Exige Crawl4AI. |

Exemplo completo:

```dotenv
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
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
WEB_URLS=
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

## 7. Usar páginas adicionais com Crawl4AI

Essa etapa é opcional. Instale as dependências extras:

```powershell
uv pip install --python .venv/Scripts/python.exe -r requirements-live.txt
.venv/Scripts/crawl4ai-setup.exe
```

Se o executável de setup não estiver disponível no Windows, use:

```powershell
.venv/Scripts/python.exe -m playwright install chromium
```

Depois informe somente URLs públicas e autorizadas, separadas por vírgula:

```dotenv
WEB_URLS=https://exemplo.org/pagina-a,https://exemplo.org/pagina-b
```

O adaptador acessa apenas essas URLs e verifica `robots.txt`. Consulte a [documentação oficial de instalação do Crawl4AI](https://docs.crawl4ai.com/basic/installation/).

## 8. Uso no código

Depois de executar as células de definição:

```python
resultado = verificar_claim("Tomar café causa câncer")
apresentar_resultado(resultado)
plot_evidence_map(resultado)
```

O retorno contém a claim, status, resumo, evidências, URLs, agregação, métricas, erros observados e os modelos usados.

## 9. Solução de problemas

### `401`, `403` ou chave inválida

- Confirme que `GEMINI_API_KEY` está no `.env` da raiz do projeto.
- Não use aspas nem espaços em torno da chave.
- Gere uma nova chave no [Google AI Studio](https://aistudio.google.com/app/apikey) se a anterior foi revogada ou exposta.

### `404` para o modelo Gemini

O catálogo da Gemini API muda ao longo do tempo. Atualize `LLM_MODEL` no `.env` para um modelo Flash disponível na sua conta. O padrão atual do projeto é `gemini-flash-lite-latest`.

### `429` ou `503` na Gemini API

A cota gratuita ou a capacidade temporária pode ter sido atingida. Aguarde e execute novamente. O notebook registra a falha e tenta o classificador local quando possível.

### Kernel ou imports não encontrados

Confirme que o notebook está usando o Python dentro de `.venv` e reinstale `requirements.txt` com o comando da seção 2.

### Crawl4AI não abre páginas

Execute o setup do Crawl4AI/Playwright e confirme que a página permite acesso automatizado. Paywalls, autenticação e bloqueios de crawler não são contornados.

## Limites da POC

Os resultados dependem da cobertura do PubMed e das páginas configuradas, da qualidade das consultas, da atualidade das fontes e da classificação automática. O `Evidence Score` é uma heurística sobre as evidências recuperadas, não uma probabilidade matemática de verdade. Toda conclusão relevante deve manter os trechos e URLs disponíveis para revisão humana.
