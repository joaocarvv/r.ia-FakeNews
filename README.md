# Repositório de Documentação Versionada — ArtFact
**Programa:** Residência em IA — ELD / Universidade de Brasília (UnB) — Turma 1  
**Equipe:** Grupo 08  
- **Vinícius César Sena Torres** (Product Owner e Co-Lead de IA)
- **Keila Alves Ferreira** (Front-End, UX e Co-Lead de Documentação)
- **Thayná Gonçalves Dutra** (Scrum Master, Front-End, Acessibilidade e Co-Lead de Documentação)
- **João Vitor Carvalho Barbosa** (Back-End, DevOps, Docker e Co-Lead de IA)
- **Ketlyn Karen Silva de Morais** (Full-Stack: Front-End e Back-End)
- **Victor Barbosa da Silva** (QA Tester / Quality Assurance)

*(Nota: O desenvolvimento do núcleo de IA foi realizado majoritariamente por Vinícius e João Vitor; a elaboração da documentação foi realizada majoritariamente por Thayná e Keila).*

**Repositório de Código:** [`https://github.com/joaocarvv/r.ia-FakeNews`](https://github.com/joaocarvv/r.ia-FakeNews)  
**Branch de Referência Atual (v2.0):** [`refactor/pubmed-only-mvp`](https://github.com/joaocarvv/r.ia-FakeNews/tree/refactor/pubmed-only-mvp)

---

## Estrutura do Repositório

```text
Documentacao versionada/
│
├── Versão 1.0 da documentação/
│   ├── Grupo 08 - Guiding Questions.pdf
│   ├── Levantamento de Datasets.pdf
│   ├── Relatório EDA Grupo8.pdf
│   ├── SCRUM - Grupo 08.pdf
│   ├── Documentação Modelo de IA/
│   │   ├── ARTFACT-Relatorio-Tecnico-Grupo8.pdf
│   │   └── Notebook.md
│   └── Levantamento de Requisitos/
│       ├── Análise SWOT.png
│       ├── Business Model Canvas.png
│       ├── DIAGRAMAS.png
│       └── Requisitos - Grupo 8.pdf
│
└── Versão 2.0 da documentação/
    ├── Descrição Final do Produto ArtFact v2.0.md
    ├── Guiding Questions v2.0 - Grupo 08.md
    ├── SCRUM e Organização da Equipe v2.0 - Grupo 08.md
    ├── Datasets/
    │   └── Levantamento de Datasets v2.0.md
    ├── Levantamento de Requisitos/
    │   └── Requisitos v2.0.md
    ├── EDA/
    │   └── Relatório EDA v2.0 - Grupo 08.md
    └── Documentação Modelo de IA/
        ├── Relatório Técnico IA v2.0 - ArtFact.md
        └── Métricas e Pipeline do Modelo de IA v2.0.md
```

---

## Mapa da Versão 2.0 (Entrega Final)

| Elemento Solicitado | Arquivo na Versão 2.0 | Principais Mudanças em Relação à v1.0 |
|---|---|---|
| **1. Datasets** | [`Versão 2.0 da documentação/Datasets/Levantamento de Datasets v2.0.md`](file:///c:/Users/iverz/Downloads/Documentacao%20versionada/Vers%C3%A3o%202.0%20da%20documenta%C3%A7%C3%A3o/Datasets/Levantamento%20de%20Datasets%20v2.0.md) | Foco exclusivo no ecossistema oficial NLM (PubMed, PMC, NCBI Gene e ClinVar). Isolamento de bases externas no runtime. |
| **2. Requisitos (RF e RNF)** | [`Versão 2.0 da documentação/Levantamento de Requisitos/Requisitos v2.0.md`](file:///c:/Users/iverz/Downloads/Documentacao%20versionada/Vers%C3%A3o%202.0%20da%20documenta%C3%A7%C3%A3o/Levantamento%20de%20Requisitos/Requisitos%20v2.0.md) | Eliminação de vereditos categóricos, inclusão do modo de Múltiplas Alegações, Comparação Manual, leitor de texto integral e persistência local FTS5. |
| **3. Análise Exploratória (EDA)** | [`Versão 2.0 da documentação/EDA/Relatório EDA v2.0 - Grupo 08.md`](file:///c:/Users/iverz/Downloads/Documentacao%20versionada/Vers%C3%A3o%202.0%20da%20documenta%C3%A7%C3%A3o/EDA/Relat%C3%B3rio%20EDA%20v2.0%20-%20Grupo%2008.md) | Relatório acadêmico detalhado do corpus de 100 artigos PubMed sobre café e câncer de próstata (1964–2026), estatísticas de autoria e triagem conceitual. |
| **4. Guiding Questions** | [`Versão 2.0 da documentação/Guiding Questions v2.0 - Grupo 08.md`](file:///c:/Users/iverz/Downloads/Documentacao%20versionada/Vers%C3%A3o%202.0%20da%20documenta%C3%A7%C3%A3o/Guiding%20Questions%20v2.0%20-%20Grupo%2008.md) | Amadurecimento conceitual: abandono do "fato ou fake", resposta via matriz de relações (*SUPPORTS*, *CONTRADICTS*, *NEUTRAL*, *UNCERTAIN*) e mitigação estrita de alucinações. |
| **5. Organização / Scrum e Papéis** | [`Versão 2.0 da documentação/SCRUM e Organização da Equipe v2.0 - Grupo 08.md`](file:///c:/Users/iverz/Downloads/Documentacao%20versionada/Vers%C3%A3o%202.0%20da%20documenta%C3%A7%C3%A3o/SCRUM%20e%20Organiza%C3%A7%C3%A3o%20da%20Equipe%20v2.0%20-%20Grupo%2008.md) | Atribuição nominal dos papéis de cada membro, histórico das Sprints 1 a 6 e cerimônias que conduziram à refatoração estratégica *PubMed-Only*. |
| **6. Modelo de IA + Relatório Técnico** | [`Versão 2.0 da documentação/Documentação Modelo de IA/Relatório Técnico IA v2.0 - ArtFact.md`](file:///c:/Users/iverz/Downloads/Documentacao%20versionada/Vers%C3%A3o%202.0%20da%20documenta%C3%A7%C3%A3o/Documenta%C3%A7%C3%A3o%20Modelo%20de%20IA/Relat%C3%B3rio%20T%C3%A9cnico%20IA%20v2.0%20-%20ArtFact.md) & [`Métricas e Pipeline do Modelo de IA v2.0.md`](file:///c:/Users/iverz/Downloads/Documentacao%20versionada/Vers%C3%A3o%202.0%20da%20documenta%C3%A7%C3%A3o/Documenta%C3%A7%C3%A3o%20Modelo%20de%20IA/M%C3%A9tricas%20e%20Pipeline%20do%20Modelo%20de%20IA%20v2.0.md) | Especificação completa do RAG Híbrido (BM25 + Qdrant Embeddings via MiniLM Multilíngue + RRF), NLI local, síntese Gemini com JSON Schema e resultados com MRR=1,0 e Recall@5=1,0. |
| **7. Descrição Final do Produto** | [`Versão 2.0 da documentação/Descrição Final do Produto ArtFact v2.0.md`](file:///c:/Users/iverz/Downloads/Documentacao%20versionada/Vers%C3%A3o%202.0%20da%20documenta%C3%A7%C3%A3o/Descri%C3%A7%C3%A3o%20Final%20do%20Produto%20ArtFact%20v2.0.md) | Documento consolidado com visão de produto, proposta de valor, fluxos de uso, salvaguardas éticas, arquitetura de software e roadmap. |
