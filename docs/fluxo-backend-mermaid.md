flowchart TD
    client["Cliente HTTP"]

    subgraph http ["API Flask - src/fatofake/api.py"]
        health["GET /api/v1/health"]
        createClaim["POST /api/v1/analyses<br/>claim + article_reference opcional"]
        createArticle["POST /api/v1/article-analyses<br/>article_reference ou article_file"]
        getStatus["GET /api/v1/analyses/{analysis_id}"]
        validateJson["Validar JSON, campos e tipos"]
        invalidHttp["Erro HTTP 400 / 415 / 422"]
        notFound["Erro HTTP 404<br/>ANALYSIS_NOT_FOUND"]
    end

    subgraph jobs ["Execucao assincrona - AnalysisJobService"]
        validateInput["validate_analysis_input<br/>normaliza alegacao e DOI/URL"]
        articleSubmission["validate_article_submission"]
        queued["Criar snapshot<br/>QUEUED / progresso 0"]
        executor["ThreadPoolExecutor<br/>agenda _run ou _run_article"]
        running["Transicao para RUNNING<br/>progresso 10"]
        jobStore["InMemoryAnalysisJobStore<br/>lock + transicoes monotônicas"]
        failedSchedule["FAILED / SCHEDULING_FAILED"]
        failedKnown["FAILED / ANALYSIS_FAILED"]
        failedArticle["FAILED / ARTICLE_ANALYSIS_FAILED"]
        failedInternal["FAILED / INTERNAL_ANALYSIS_ERROR"]
        succeeded["SUCCEEDED / progresso 100<br/>resultado serializado"]
        serializeJob["serialize_analysis_job"]
    end

    subgraph claimPipeline ["Pipeline de alegacao - MultiArticleAnalysisService"]
        plan["prepare_search_plan<br/>ate 3 consultas normalizadas"]
        searchChoice{"search_engine configurado?"}
        federated["FederatedSearchEngine.search<br/>PubMed + OpenAlex + Scielo via OpenAlex"]
        pubmed["search_pubmed<br/>PubMedClient"]
        candidates["Candidatos normalizados<br/>e possiveis falhas por fonte"]
        articleLoop{"Ainda ha candidato e<br/>target_articles nao foi atingido?"}
        processArticle["ScientificArticleProcessor.process"]
        articleFailure["ArticleProcessingError<br/>registrar falha com PMID e etapa"]
        retracted{"Retratacao confirmada?"}
        excluded["Excluir da sintese<br/>registrar falha de elegibilidade"]
        accepted["Adicionar ArticleEvidenceBundle"]
        enough{"Artigos processaveis >=<br/>minimum_successful_articles?"}
        insufficient["AnalysisServiceError<br/>artigos processaveis insuficientes"]
        flatten["Coletar assessments e perfis<br/>de qualidade por artigo"]
        synthesize["synthesize_evidence<br/>artigo primeiro, corpus depois"]
        report["generate_evidence_report<br/>direcao, forca, limitacoes e fontes"]
        serializeResult["serialize_multi_article_analysis<br/>contrato JSON + verification cards"]
    end

    subgraph articlePipeline ["Pipeline de artigo enviado"]
        articleRunner["ArticleAnalysisRunner.analyze_article"]
        articleResult["Resultado estruturado do artigo"]
    end

    client --> health
    health --> healthResponse["200 { status: ok }"]
    client --> createClaim
    createClaim --> validateJson
    createArticle --> validateJson
    validateJson -->|"JSON invalido, tipo incorreto ou campo desconhecido"| invalidHttp
    validateJson -->|"rota de alegacao"| validateInput
    validateJson -->|"rota de artigo"| articleSubmission
    validateInput -->|"InputValidationError"| invalidHttp
    validateInput --> queued
    articleSubmission -->|"InputValidationError"| invalidHttp
    articleSubmission --> queued
    queued --> jobStore
    queued --> executor
    executor -->|"falha ao agendar"| failedSchedule
    executor --> running
    failedSchedule --> jobStore
    running --> jobStore

    executor -->|"_run"| plan
    plan --> searchChoice
    searchChoice -->|"sim"| federated
    searchChoice -->|"nao"| pubmed
    federated --> candidates
    pubmed --> candidates
    candidates --> articleLoop
    articleLoop -->|"sim"| processArticle
    articleLoop -->|"nao"| enough
    processArticle --> content["retrieve_article_content<br/>PMC / abstract fallback"]
    content --> chunk["chunk_article_content<br/>trechos rastreaveis"]
    chunk --> retrieval["BM25 + SemanticIndex<br/>HybridIndex com RRF"]
    retrieval --> extraction["extract_evidence_statements<br/>+ build_claim_evidence_pairs"]
    extraction --> classification["classify_claim_evidence_pairs<br/>apoio, contradicao, neutro ou incerto"]
    classification --> quality["validate_article_quality<br/>identidade, retratacao, desenho, dados e protocolo"]
    quality --> retracted
    processArticle -.->|"ChunkingError, ContentRetrievalError<br/>ou RetrievalError"| articleFailure
    articleFailure --> articleLoop
    retracted -->|"sim"| excluded
    excluded --> articleLoop
    retracted -->|"nao"| accepted
    accepted --> articleLoop
    enough -->|"nao"| insufficient
    enough -->|"sim"| flatten
    insufficient --> failedKnown
    flatten --> synthesize
    synthesize --> report
    report --> serializeResult
    serializeResult --> succeeded

    executor -->|"_run_article"| articleRunner
    articleRunner --> articleResult
    articleRunner -.->|"AnalysisServiceError, ArticleIngestionError<br/>ou GeminiAnalysisError"| failedArticle
    articleResult --> succeeded
    articleResult -.->|"excecao inesperada"| failedInternal

    plan -.->|"excecao inesperada"| failedInternal
    processArticle -.->|"falha inesperada"| failedInternal
    synthesize -.->|"falha inesperada"| failedInternal
    report -.->|"falha inesperada"| failedInternal
    failedKnown --> jobStore
    failedArticle --> jobStore
    failedInternal --> jobStore
    succeeded --> jobStore

    jobStore --> serializeJob
    client --> getStatus
    getStatus --> jobStore
    getStatus -->|"job inexistente"| notFound
    serializeJob --> statusResponse["200<br/>QUEUED, RUNNING, SUCCEEDED ou FAILED"]
    statusResponse -->|"QUEUED/RUNNING: Retry-After 1"| client
    statusResponse -->|"SUCCEEDED: result"| client
    statusResponse -->|"FAILED: error"| client

    classDef api fill:#e8f1ff,stroke:#2563eb,color:#102a43;
    classDef async fill:#fff4d6,stroke:#b7791f,color:#513b08;
    classDef pipeline fill:#e8f7ef,stroke:#27864b,color:#123b24;
    classDef decision fill:#f4e8ff,stroke:#7c3aed,color:#3b176b;
    classDef error fill:#ffe8e8,stroke:#c53030,color:#5f1717;
    classDef output fill:#e9ecef,stroke:#495057,color:#212529;

    class health,createClaim,createArticle,getStatus,validateJson,healthResponse api;
    class validateInput,articleSubmission,queued,executor,running,jobStore,succeeded,serializeJob async;
    class plan,federated,pubmed,candidates,processArticle,content,chunk,retrieval,extraction,classification,quality,excluded,accepted,flatten,synthesize,report,serializeResult,articleRunner,articleResult pipeline;
    class searchChoice,articleLoop,retracted,enough decision;
    class invalidHttp,notFound,failedSchedule,failedKnown,failedArticle,failedInternal,articleFailure,insufficient error;
    class statusResponse output;

%% [src/fatofake/api.py](../src/fatofake/api.py)
%% [src/fatofake/analysis_service.py](../src/fatofake/analysis_service.py)
%% [src/fatofake/input_validation.py](../src/fatofake/input_validation.py)
%% [src/fatofake/search_preparation.py](../src/fatofake/search_preparation.py)