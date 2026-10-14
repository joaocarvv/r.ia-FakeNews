# ArtFact — integração frontend/backend

A partir desta branch, a estrutura integrada é:

```text
artfact---verificador-de-artigos/
├── src/                 # React + TypeScript, login Firebase e indicadores
├── r.ia-FakeNews/       # API Flask, PubMed, IA e validação de evidências
├── firestore.rules      # regras do histórico (publicar manualmente no console)
├── vite.config.ts       # proxy /api -> backend local
├── tests/               # testes frontend
└── package.json
```

**Importante:** o backend já está incorporado ao repositório ArtFact. Não é necessário clonar novamente o GitHub do João nem extrair um ZIP `frontend`. O frontend é a pasta raiz do repositório. As instruções do README do backend continuam úteis para instalação do pipeline científico.

## Iniciar
No PowerShell, em um terminal:

```powershell
cd C:\artfact2\r.ia-FakeNews
# Use o ambiente Python 3.11 que já tiver instalado:
.\.venv\Scripts\python.exe run_acceptance_app.py
```

Em outro terminal:

```powershell
cd C:\artfact2
npm ci
npm run dev
```

Navegue até http://localhost:8443. Verifique antes se http://127.0.0.1:5000/api/v1/health responde.

Crie um `.env` local para o backend a partir de `.env.example` apenas se ainda não possuir um. Configure `GEMINI_API_KEY` e demais serviços necessários. **Nunca compartilhe ou publique este arquivo, senhas, tokens ou chaves de contas de serviço.**

## Contrato com a API Flask
| Ação | Rota |
| --- | --- |
| Iniciar análise de link, DOI ou arquivo | POST `/api/v1/article-analyses` |
| Consultar progresso | GET `/api/v1/analyses/{id}?view=status` |
| Obter alegações e resultados | GET `/api/v1/analyses/{id}` |
| Selecionar alegações | POST `/api/v1/article-analyses/{id}/claims` |
| Relatório Markdown | GET `/api/v1/analyses/{id}/report.md` |

O usuário seleciona até 10 alegações. O frontend não simula o resultado; utiliza os status enviados pelo backend: QUEUED, RUNNING, AWAITING_CLAIM_SELECTION, RESEARCHING, SUCCEEDED, FAILED.

## Indicadores científicos
Cobertura, quantidade de artigos, trechos de evidência e triagem metodológica são lidos de `user_summary` e `verification`. Não significam “X% verdadeiro”; indicadores sem dados suficientes permanecem `N/D`.

## Login, Firestore e segurança
Autenticação Google e Email/Senha (Firebase Authentication). Habilite os provedores e os domínios no console Firebase. O histórico dos artigos é resumido e salvo no Firestore por UID, exigindo que as regras de `firestore.rules` sejam aplicadas manualmente. Teste isolamento com duas contas. O Flask continua sem validação de ID token; não use seus endpoints como armazenamento privado até que a autorização no backend seja implementada.

## Testes
```powershell
npm test
npm run typecheck
npm run build
```

O GitHub Actions também executa estes passos. Não substitui testes de artigos reais com PubMed/Gemini nem a revisão científica humana.
