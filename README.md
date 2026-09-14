# Fato ou Fake? — POC orientada a evidências

Notebook executável que verifica claims pelo cruzamento de fontes reais. O pipeline consulta o PubMed pela API oficial, normaliza e deduplica documentos, recupera trechos com busca híbrida, classifica evidências e produz uma síntese fundamentada.

## Configuração

1. Crie uma chave gratuita no [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Copie `.env.example` para `.env`.
3. Preencha somente esta variável:

   ```dotenv
   GEMINI_API_KEY=sua_chave_aqui
   ```

4. Prepare e abra o notebook:

   ```powershell
   uv venv .venv --python 3.11
   uv pip install --python .venv/Scripts/python.exe -r requirements.txt
   .venv/Scripts/python.exe -m jupyter lab fato_ou_fake_poc.ipynb
   ```

Para usar páginas web fornecidas em `WEB_URLS`, instale também `requirements-live.txt`. O adaptador respeita `robots.txt` e acessa somente as URLs explicitamente configuradas.

## Execução sem chave

Sem `GEMINI_API_KEY`, o notebook continua usando documentos reais e tenta classificar os trechos com um modelo NLI local aberto. A síntese passa a ser extrativa e fica identificada como fallback. Nenhuma falha de API é preenchida com dado simulado.

O arquivo `fato_ou_fake_poc.ipynb` está salvo com uma execução completa dos três casos de demonstração. Os resultados mudam conforme o PubMed atualiza o índice e conforme o modelo configurado.
