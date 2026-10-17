# Guiding Questions — Versão 2.0
**Projeto:** ArtFact — MVP PubMed/PMC Orientado a Evidências Científicas  
**Programa:** RES IA ELD UnB — Turma 1 | Grupo 08  
**Data:** Outubro de 2026  
**Autores:** Victor Barbosa da Silva, Keila Alves Ferreira, Thayná Gonçalves Dutra, João Vitor Carvalho Barbosa, Vinícius César Sena Torres, Ketlyn Karen Silva de Morais  
**Branch de Referência:** `refactor/pubmed-only-mvp`

---

## 1. Evolução das Guiding Questions: Da v1.0 para a v2.0

Na concepção inicial do projeto (Versão 1.0), as discussões norteadoras giravam em torno da viabilidade de construir um "chatbot de checagem de fatos em saúde" com temas fixos pré-definidos (4 temas de senso comum), explorando datasets como BioASQ e múltiplas bases científicas heterogêneas (SciELO, OpenAlex, Europe PMC).

Ao longo do ciclo de engenharia e na consolidação da **Versão 2.0 (branch `refactor/pubmed-only-mvp`)**, a equipe enfrentou desafios práticos de consistência de dados, alucinações de LLMs e limites metodológicos da literatura científica. Como resultado, as perguntas norteadoras amadureceram para um enquadramento rigoroso, auditável e fundamentado em engenharia de confiabilidade.

---

## 2. Perguntas Norteadoras Centrais (v2.0)

### 2.1 Qual é o problema real a ser enfrentado e qual é o escopo delimitado?
- **Desafio da Desinformação e a Poluição da Literatura em Saúde:** A desinformação em saúde é dinâmica, contextual e raramente binária. Muitas alegações distorcem conclusões científicas preliminares ou convertem associações estatísticas modestas em prescrições universais. Contudo, na Versão 2.0, o problema diagnosticado pela equipe revelou uma camada ainda mais crítica: a **desinformação científica institucionalizada** impulsionada pela proliferação de **revistas predatórias (*predatory journals*)** e **fábricas de artigos (*paper mills*)**.
  - **Revistas Predatórias:** Periódicos que adotam modelos de publicação corrompidos, cobrando taxas de processamento de artigos (*Article Processing Charges - APCs*) sem realizar avaliação por pares (*peer review*) real ou com revisões puramente burocráticas e desprovidas de crivo metodológico. Tais veículos publicam trabalhos metodologicamente falhos, pseudocientíficos ou anticientíficos sob uma fachada formal de autoridade acadêmica.
  - **Fábricas de Artigos (*Paper Mills*):** Entidades comerciais clandestinas que fabricam manuscritos científicos fictícios em escala industrial, manipulando dados laboratoriais, gerando imagens biomédicas forjadas e comercializando autorias para pesquisadores pressionados pela cultura do *"publish or perish"*.
  - **Impacto Crítico na Ciência e na Saúde Pública:**
    1. *Contaminação da Base Primária:* Ensaios clínicos falsificados e estudos laboratoriais inexistentes infiltram-se em bases de dados bibliográficas.
    2. *Envenenamento de Meta-Análises e Diretrizes Clínicas:* Revisões sistemáticas e meta-análises — consideradas o padrão-ouro da medicina baseada em evidências — correm risco de incluir estudos forjados em suas sínteses estatísticas, gerando recomendações terapêuticas ineficazes ou diretamente lesivas a pacientes.
    3. *Armamento da Desinformação nas Redes:* Agentes de desinformação utilizam artigos publicados nesses periódicos como "comprovação científica definitiva" para respaldar tratamentos inócuos, promover pânico vacinal ou desencorajar intervenções oncológicas consagradas.
    4. *Risco de Amplificação por Inteligência Artificial:* Se um sistema de IA/RAG aceitar de forma ingênua qualquer "artigo indexado na web", ele se tornará um megafone automatizado para fraudes científicas e estudos de *paper mills*.
- **Resposta e Escopo v2.0:** O ArtFact não busca ser um "oráculo da verdade". O escopo v2.0 define o produto como uma ferramenta de **apoio à decisão e leitura crítica de evidências primárias**. Para mitigar os riscos de contaminação por periódicos predatórios e artigos corrompidos, o escopo operacional foi focado exclusivamente no ecossistema curado da **National Library of Medicine (NLM)**:
  - **Descoberta e Metadados Curados:** PubMed (NCBI E-utilities), cujos títulos e periódicos passam pelo crivo contínuo do comitê LSTRC (*Literature Selection Technical Review Committee* da NLM);
  - **Texto Integral Auditável:** PubMed Central (PMC), quando em acesso aberto oficial;
  - **Fallback Controlado:** Abstract do PubMed explicitamente identificado na interface com indicação clara dos limites da leitura;
  - **Entrada Opcional do Usuário:** Envio direto de PDF/imagem para análise, com rastreamento da proveniência por página e sem navegação autônoma cega da IA;
  - **Dados Genômicos/Clínicos Oficiais:** Consultas dinâmicas ao NCBI Gene e ClinVar para alegações com variantes genéticas ou entidades biomédicas específicas.

---

### 2.2 O sistema deve emitir um veredito binário de "Verdadeiro" ou "Falso"?
- **Decisão Crítica da v2.0:** **NÃO.**
- **Fundamentação Técnica e Ética:** Declarar que uma alegação é categoricamente "fato" ou "fake" com base em IA generativa representa um risco sanitário e científico inaceitável. O ArtFact v2.0 abandona o formato binário e adota uma **matriz de relações textuais**:
  - `SUPPORTS` (Apoia a alegação);
  - `CONTRADICTS` (Contradiz a alegação);
  - `NEUTRAL` (Menciona o tema sem apontar causalidade ou efeito conclusivo);
  - `UNCERTAIN` (Evidência insuficiente, conflitante ou abaixo dos limiares de confiança estatística).
- **Apresentação:** A interface entrega uma tabela de evidências estruturadas com componentes PICO (População, Intervenção, Comparação, Desfecho), trechos literais citados e indicação de limitações do estudo.

---

### 2.3 Como garantir que a IA não sofra com alucinações ou citações inventadas?
- **Mecanismos Implementados na v2.0:**
  1. **Isolamento de Contexto:** O LLM (Gemini) recebe **apenas** os trechos científicos recuperados e indexados pelo pipeline do ArtFact. Ele não é autorizado a navegar livremente na web nem a recorrer à sua memória paramétrica para formular evidências.
  2. **Groundedness Estrutural:** O sistema calcula métricas contínuas de validação:
     - *Citation Validity:* Valida se o PMID e o ID do trecho (`passage_id`) existem fisicamente no conjunto de documentos enviados;
     - *Literal Quote Matching:* Normaliza espaços e caracteres e exige correspondência textual exata entre o trecho citado na resposta e o documento original;
     - Omissão de dados sem respaldo textual direto: campos sem comprovação no texto são omitidos da interface.
  3. **Regras Estritas de Abstenção:** Se os índices lexicais e semânticos não recuperarem trechos que superem os limiares mínimos de similaridade, o sistema emite abstenção formal (`ABSTAIN`), informando que não há base científica suficiente no corpus disponível.

---

### 2.4 Como resolver a barreira de idioma entre a dúvida do usuário (em português) e a literatura científica (em inglês)?
- **Solução Arquitetural:**
  - **Busca Semântica Multilíngue:** Uso do modelo de embeddings denso `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensões), capaz de mapear alegações em português diretamente no mesmo espaço vetorial de resumos biomédicos em inglês.
  - **Expansão Assistida de Termos:** Uso do LLM para desdobrar a dúvida do usuário em termos formais do vocabulário MeSH em inglês (ex.: "café e próstata" $\rightarrow$ `("Coffee"[MeSH] OR coffee) AND ("Prostatic Neoplasms"[MeSH] OR "prostate cancer")`), exibindo de forma transparente ao usuário quais consultas foram executadas.
  - **Fallback Local:** Disponibilidade de tradução local via `Helsinki-NLP/opus-mt-ROMANCE-en` para ambientes sem acesso à API Gemini.

---

### 2.5 Como estruturar a recuperação de informação para evitar perda de artigos importantes?
- **Decisão Técnica:** Adoção de **Recuperação Híbrida (Hybrid Retrieval)** combinando:
  - **BM25 (Lexical):** Captura exata de termos médicos, substâncias químicas, dosagens e acrônimos biomédicos;
  - **Busca Semântica Vetorial:** Captura paráfrases e intenção clínica conceitual;
  - **Fusão por Posição (Reciprocal Rank Fusion - RRF):** Combinação determinística das posições dos rankings sem somar pontuações de escalas matemáticas incompatíveis.
- **Validação:** Métricas formais de IR avaliadas via notebook com dados anotados (*Golden set*): Precision@k, Recall@k, MRR (Mean Reciprocal Rank) e nDCG@k.

---

### 2.6 Como lidar com artigos que contêm múltiplas alegações simultâneas?
- **Inovação da v2.0 (`notebooks/27`):**
  - O sistema lê o artigo de entrada e extrai de forma atômica as alegações declaradas no documento.
  - O usuário pode selecionar quais alegações deseja verificar (em lote ou individualmente).
  - Cada alegação passa por uma rodada independente de recuperação e confronto contra a literatura científica, sem necessidade de reprocessar o documento principal.
  - O usuário pode inclusive adicionar alegações manuais complementares, marcadas explicitamente na interface como "conteúdo do usuário".

---

### 2.7 Como tratar artigos retratados (*retractions*) ou literatura corrompida por fraudes e paper mills?
- **Regra de Segurança da v2.0 (`notebooks/19`):**
  - Com o avanço das investigações sobre *paper mills* na comunidade científica internacional, milhares de artigos têm sido formalmente retratados por dados forjados, revisões por pares falsificadas e manipulação de imagens.
  - No ArtFact v2.0, artigos com **retratação confirmada no PubMed são imediatamente excluídos da síntese de evidências**.
  - O artigo retratado não é simplesmente silenciado ou ocultado: ele é apresentado na interface acompanhado de um **alerta visual destacado de integridade em vermelho**, informando expressamente o motivo do descarte (retratação oficial) para educar o usuário sobre a invalidação daquele conteúdo pela comunidade médica.

---

### 2.8 Como permitir que pesquisadores e profissionais realizem comparações manuais dirigidas?
- **Recurso da v2.0 (`src/fatofake/manual_comparison.py`):**
  - O modo de Comparação Manual permite confrontar uma alegação contra até **20 referências explicitamente selecionadas** pelo usuário (artigos da biblioteca local, PMIDs, DOIs indexados ou uploads de PDFs).
  - O sistema impede a comparação tautológica (artigo contra si mesmo) e restringe a análise exclusivamente ao conjunto escolhido.

---

### 2.9 Como garantir persistência e consulta histórica dos resultados?
- **Solução Implementada (`src/fatofake/library.py`):**
  - Criação de uma Biblioteca Local baseada em SQLite com suporte a busca textual eficiente via motor **FTS5** (Full-Text Search 5).
  - Armazena metadados, arquivos, resumos, análises vinculadas, notas pessoais e etiquetas personalizadas do usuário.

---

## 3. Matriz de Decisões de Design (v1.0 vs. v2.0)

| Dimensão | Versão 1.0 (Concepção Inicial) | Versão 2.0 (`refactor/pubmed-only-mvp`) |
|---|---|---|
| **Fonte Primária** | Múltiplas bases dispersas (OpenAlex, SciELO, Europe PMC) | Ecossistema NLM oficial (PubMed + PMC + NCBI Gene/ClinVar) |
| **Classificação** | Tendência a veredito "Fato ou Fake" | Relações textuais estritas (*SUPPORTS, CONTRADICTS, NEUTRAL, UNCERTAIN*) |
| **Metodologia de Risco** | Pretensão de cálculo automatizado de GRADE/AMSTAR 2 | Apresentação transparente de `PublicationType` do PubMed sem carimbos arbitrários |
| **Escopo de Alegações** | Uma única alegação por sessão de chat | Múltiplas alegações por artigo, seleção em lote e claims customizadas |
| **Comparação** | Apenas busca automatizada genérica | Busca temática aberta + Comparação manual dirigida (até 20 referências) |
| **Persistência** | Sessão de aplicação temporária | Biblioteca persistente em SQLite com busca indexada FTS5 |
| **Integridade e Confiabilidade** | Dependência opaca da API de LLM sem filtros de integridade editorial | Validação de citações literais, ID de passagens, exclusão de retratações e mitigação contra contaminação por *paper mills* e revistas predatórias |
