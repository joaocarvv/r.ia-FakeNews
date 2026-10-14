# ArtFact — Verificador de Artigos Científicos

Plataforma de pesquisa e verificação de alegações científicas. Frontend em React, TypeScript e Vite; backend Flask/Python em `r.ia-FakeNews/`. Integração Gemini/PubMed configurada por variáveis de ambiente.

## Rodar localmente (Windows / PowerShell)

Pré-requisitos: Node.js >=22.12, Python 3.11, Git.

### Backend (terminal 1)
```powershell
cd C:\artfact2\r.ia-FakeNews
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Preencha o GEMINI_API_KEY no .env local; nunca envie este arquivo ao Git.
.\.venv\Scripts\python.exe run_acceptance_app.py
```
Se você já possui um `.env` configurado ou ambiente virtual, não o sobrescreva. Confirme http://127.0.0.1:5000/api/v1/health.

### Frontend (terminal 2)
```powershell
cd C:\artfact2
npm ci
npm run dev
```
Abra http://localhost:8443. O proxy Vite envia `/api/*` à porta 5000. O backend deve continuar rodando.

## Firebase
1. No projeto `ria-fakenews`, em **Authentication > Sign-in method**, habilite Google e Email/Password.
2. Autorize o domínio usado em Authentication > Settings > Authorized domains.
3. Crie Firestore Database em modo produção.
4. Em **Firestore Database > Rules**, mescle e publique o conteúdo de `firestore.rules`. O arquivo no GitHub, isoladamente, **não aplica regras no Firebase**.
5. Teste com dois usuários distintos para verificar o isolamento do histórico.

A interface guarda apenas metadados de até 50 análises recuperadas por usuário, permite buscar por título, reabrir resultados mantidos pelo backend e excluir entradas; não envia senhas ao backend próprio. Se o backend original não possuir mais a análise, o registro continua visível, mas o relatório não poderá ser reaberto. **A API Flask ainda não valida tokens Firebase para proteger análises**: antes de usar artigos privados com dados pessoais, implemente autorização server-side.

## Indicadores
A porcentagem apresentada é **cobertura do material pesquisado**, não um score de verdade, qualidade ou credibilidade. Ausência de dado aparece como `N/D`. Trechos devem ser conferidos na fonte e no relatório.

## Validação automática
```powershell
npm test
npm run typecheck
npm run build
```

Leia [README-INTEGRACAO.md](README-INTEGRACAO.md) e [ROADMAP-MELHORIAS.md](ROADMAP-MELHORIAS.md).
