"""Audita acesso e papel das fontes científicas externas do projeto."""

from __future__ import annotations

import json
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .retrieval import RetrievalError
from .transport import default_ssl_context

PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PMC_ID_CONVERTER_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
CLINICAL_TRIALS_SEARCH_URL = "https://clinicaltrials.gov/api/v2/studies"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
DATACITE_DOIS_URL = "https://api.datacite.org/dois"
SCIELO_ARTICLE_IDENTIFIERS_URL = (
    "https://articlemeta.scielo.org/api/v1/article/identifiers"
)
SPRINGER_META_URL = "https://api.springernature.com/meta/v2/json"
SPRINGER_OPENACCESS_URL = "https://api.springernature.com/openaccess/json"
SCIENCEDIRECT_SEARCH_URL = "https://api.elsevier.com/content/search/sciencedirect"

JsonFetcher = Callable[
    [str, Mapping[str, str], Mapping[str, str]], Mapping[str, Any]
]


class SourceRole(str, Enum):
    DISCOVERY = "DISCOVERY"
    CONTENT = "CONTENT"
    VALIDATION = "VALIDATION"
    PUBLISHER = "PUBLISHER"
    MANUAL = "MANUAL"


class SourceProbeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    NO_RESULTS = "NO_RESULTS"
    CREDENTIAL_REQUIRED = "CREDENTIAL_REQUIRED"
    MANUAL_ONLY = "MANUAL_ONLY"
    COVERED_BY_OTHER = "COVERED_BY_OTHER"
    ERROR = "ERROR"


@dataclass(frozen=True)
class SourceAuditConfig:
    query: str
    limit: int = 5
    email: str | None = None
    ncbi_api_key: str | None = None
    springer_meta_api_key: str | None = None
    springer_openaccess_api_key: str | None = None
    elsevier_api_key: str | None = None

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise RetrievalError("A consulta da auditoria não pode estar vazia.")
        if not 1 <= self.limit <= 20:
            raise RetrievalError("O limite da auditoria deve estar entre 1 e 20.")


@dataclass(frozen=True)
class SourceAuditResult:
    source: str
    role: SourceRole
    status: SourceProbeStatus
    result_count: int | None
    query_specific: bool
    endpoint: str
    detail: str
    credential_env: str | None = None


@dataclass(frozen=True)
class SourceAuditReport:
    query: str
    results: tuple[SourceAuditResult, ...]

    @property
    def available_count(self) -> int:
        return sum(item.status is SourceProbeStatus.AVAILABLE for item in self.results)

    @property
    def error_count(self) -> int:
        return sum(item.status is SourceProbeStatus.ERROR for item in self.results)


class AcademicSourceAuditor:
    """Executa consultas pequenas sem tratar catálogos sobrepostos como independentes."""

    def __init__(
        self,
        *,
        timeout: float = 25.0,
        fetch_json: JsonFetcher | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if timeout <= 0:
            raise RetrievalError("O timeout deve ser maior que zero.")
        self.timeout = timeout
        self._fetch_json = fetch_json or self._request_json
        self._ssl_context = ssl_context or default_ssl_context()

    def _request_json(
        self,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> Mapping[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{url}{query}",
            headers={"User-Agent": "FatoOuFake/0.1", **dict(headers)},
        )
        try:
            with urlopen(
                request,
                timeout=self.timeout,
                context=self._ssl_context,
            ) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RetrievalError(f"Falha ao consultar {url}: {error}") from error
        if not isinstance(payload, dict):
            raise RetrievalError(f"{url} retornou JSON inesperado.")
        return payload

    @staticmethod
    def _status(count: int) -> SourceProbeStatus:
        return (
            SourceProbeStatus.AVAILABLE
            if count > 0
            else SourceProbeStatus.NO_RESULTS
        )

    @staticmethod
    def _result(
        source: str,
        role: SourceRole,
        count: int,
        query_specific: bool,
        endpoint: str,
        detail: str,
    ) -> SourceAuditResult:
        return SourceAuditResult(
            source=source,
            role=role,
            status=AcademicSourceAuditor._status(count),
            result_count=count,
            query_specific=query_specific,
            endpoint=endpoint,
            detail=detail,
        )

    @staticmethod
    def _safe_total(value: Any, fallback: int) -> int:
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return fallback

    def _pubmed(
        self, config: SourceAuditConfig
    ) -> tuple[SourceAuditResult, tuple[str, ...]]:
        params = {
            "db": "pubmed",
            "term": config.query,
            "retmax": str(config.limit),
            "retmode": "json",
            "sort": "relevance",
            "tool": "fatofake",
        }
        if config.email:
            params["email"] = config.email
        if config.ncbi_api_key:
            params["api_key"] = config.ncbi_api_key
        payload = self._fetch_json(PUBMED_SEARCH_URL, params, {})
        try:
            search = payload["esearchresult"]
            identifiers = tuple(str(value) for value in search["idlist"])
            total = self._safe_total(search["count"], len(identifiers))
        except (KeyError, TypeError) as error:
            raise RetrievalError("Resposta de busca do PubMed inválida.") from error
        return (
            self._result(
                "PubMed",
                SourceRole.DISCOVERY,
                total,
                True,
                PUBMED_SEARCH_URL,
                f"Busca temática; {len(identifiers)} registros recuperados na amostra.",
            ),
            identifiers,
        )

    def _pmc(
        self, config: SourceAuditConfig, pubmed_ids: tuple[str, ...]
    ) -> SourceAuditResult:
        if not pubmed_ids:
            return self._result(
                "PubMed Central (PMC)",
                SourceRole.CONTENT,
                0,
                True,
                PMC_ID_CONVERTER_URL,
                "O PubMed não forneceu PMIDs para verificar disponibilidade no PMC.",
            )
        params = {
            "ids": ",".join(pubmed_ids),
            "format": "json",
            "tool": "fatofake",
        }
        if config.email:
            params["email"] = config.email
        payload = self._fetch_json(PMC_ID_CONVERTER_URL, params, {})
        records = payload.get("records") or []
        available = sum(bool(item.get("pmcid")) for item in records if isinstance(item, dict))
        return self._result(
            "PubMed Central (PMC)",
            SourceRole.CONTENT,
            available,
            True,
            PMC_ID_CONVERTER_URL,
            f"{available} de {len(pubmed_ids)} PMIDs da amostra possuem PMCID.",
        )

    def _clinical_trials(self, config: SourceAuditConfig) -> SourceAuditResult:
        payload = self._fetch_json(
            CLINICAL_TRIALS_SEARCH_URL,
            {
                "query.term": config.query,
                "pageSize": str(config.limit),
                "format": "json",
                "countTotal": "true",
            },
            {},
        )
        studies = payload.get("studies") or []
        total = self._safe_total(payload.get("totalCount"), len(studies))
        return self._result(
            "ClinicalTrials.gov",
            SourceRole.VALIDATION,
            total,
            True,
            CLINICAL_TRIALS_SEARCH_URL,
            f"Busca de registros; {len(studies)} estudos recuperados na amostra.",
        )

    def _crossref(self, config: SourceAuditConfig) -> SourceAuditResult:
        params = {
            "query.bibliographic": config.query,
            "rows": str(config.limit),
        }
        if config.email:
            params["mailto"] = config.email
        payload = self._fetch_json(CROSSREF_WORKS_URL, params, {})
        message = payload.get("message") or {}
        items = message.get("items") or []
        total = self._safe_total(message.get("total-results"), len(items))
        return self._result(
            "Crossref",
            SourceRole.VALIDATION,
            total,
            True,
            CROSSREF_WORKS_URL,
            f"Busca de metadados; {len(items)} registros recuperados na amostra.",
        )

    def _retraction_watch(self, config: SourceAuditConfig) -> SourceAuditResult:
        params = {"filter": "update-type:retraction", "rows": "1"}
        if config.email:
            params["mailto"] = config.email
        payload = self._fetch_json(CROSSREF_WORKS_URL, params, {})
        message = payload.get("message") or {}
        items = message.get("items") or []
        total = self._safe_total(message.get("total-results"), len(items))
        return self._result(
            "Retraction Watch (via Crossref)",
            SourceRole.VALIDATION,
            total,
            False,
            CROSSREF_WORKS_URL,
            "Teste de disponibilidade do catálogo de retratações; a checagem real é por DOI.",
        )

    def _openalex(self, config: SourceAuditConfig) -> SourceAuditResult:
        payload = self._fetch_json(
            OPENALEX_WORKS_URL,
            {"search": config.query, "per-page": str(config.limit)},
            {},
        )
        results = payload.get("results") or []
        total = self._safe_total((payload.get("meta") or {}).get("count"), len(results))
        return self._result(
            "OpenAlex",
            SourceRole.DISCOVERY,
            total,
            True,
            OPENALEX_WORKS_URL,
            f"Busca temática; {len(results)} trabalhos recuperados na amostra.",
        )

    def _datacite(self, config: SourceAuditConfig) -> SourceAuditResult:
        payload = self._fetch_json(
            DATACITE_DOIS_URL,
            {"query": config.query, "page[size]": str(config.limit)},
            {},
        )
        data = payload.get("data") or []
        total = self._safe_total((payload.get("meta") or {}).get("total"), len(data))
        return self._result(
            "DataCite",
            SourceRole.VALIDATION,
            total,
            True,
            DATACITE_DOIS_URL,
            f"Busca de objetos de pesquisa; {len(data)} registros recuperados na amostra.",
        )

    def _scielo(self, config: SourceAuditConfig) -> SourceAuditResult:
        payload = self._fetch_json(
            SCIELO_ARTICLE_IDENTIFIERS_URL,
            {"collection": "scl", "limit": str(config.limit)},
            {},
        )
        objects = payload.get("objects") or []
        total = self._safe_total((payload.get("meta") or {}).get("total"), len(objects))
        return self._result(
            "SciELO",
            SourceRole.DISCOVERY,
            total,
            False,
            SCIELO_ARTICLE_IDENTIFIERS_URL,
            "O ArticleMeta respondeu, mas este endpoint testa o catálogo brasileiro, não busca temática.",
        )

    def _springer(self, config: SourceAuditConfig) -> SourceAuditResult:
        if not config.springer_meta_api_key:
            return SourceAuditResult(
                source="Springer Nature Meta",
                role=SourceRole.PUBLISHER,
                status=SourceProbeStatus.CREDENTIAL_REQUIRED,
                result_count=None,
                query_specific=True,
                endpoint=SPRINGER_META_URL,
                detail="A API de metadados exige chave; nenhum conteúdo foi consultado.",
                credential_env="SPRINGER_META_API_KEY",
            )
        payload = self._fetch_json(
            SPRINGER_META_URL,
            {
                "q": f"keyword:{config.query}",
                "p": str(config.limit),
                "api_key": config.springer_meta_api_key,
            },
            {},
        )
        records = payload.get("records") or []
        total = self._safe_total(
            ((payload.get("result") or [{}])[0]).get("total"), len(records)
        )
        return self._result(
            "Springer Nature Meta",
            SourceRole.PUBLISHER,
            total,
            True,
            SPRINGER_META_URL,
            f"Busca editorial; {len(records)} registros recuperados na amostra.",
        )

    def _springer_open_access(self, config: SourceAuditConfig) -> SourceAuditResult:
        if not config.springer_openaccess_api_key:
            return SourceAuditResult(
                source="Springer Nature Open Access",
                role=SourceRole.CONTENT,
                status=SourceProbeStatus.CREDENTIAL_REQUIRED,
                result_count=None,
                query_specific=True,
                endpoint=SPRINGER_OPENACCESS_URL,
                detail="A API Open Access exige chave; nenhum conteúdo foi consultado.",
                credential_env="SPRINGER_OPENACCESS_API_KEY",
            )
        payload = self._fetch_json(
            SPRINGER_OPENACCESS_URL,
            {
                "q": f"keyword:{config.query}",
                "p": str(config.limit),
                "api_key": config.springer_openaccess_api_key,
            },
            {},
        )
        records = payload.get("records") or []
        total = self._safe_total(
            ((payload.get("result") or [{}])[0]).get("total"), len(records)
        )
        return self._result(
            "Springer Nature Open Access",
            SourceRole.CONTENT,
            total,
            True,
            SPRINGER_OPENACCESS_URL,
            f"Busca em conteúdo aberto; {len(records)} registros recuperados na amostra.",
        )

    def _science_direct(self, config: SourceAuditConfig) -> SourceAuditResult:
        if not config.elsevier_api_key:
            return SourceAuditResult(
                source="ScienceDirect",
                role=SourceRole.PUBLISHER,
                status=SourceProbeStatus.CREDENTIAL_REQUIRED,
                result_count=None,
                query_specific=True,
                endpoint=SCIENCEDIRECT_SEARCH_URL,
                detail="A API da Elsevier exige chave; nenhum conteúdo foi consultado.",
                credential_env="ELSEVIER_API_KEY",
            )
        payload = self._fetch_json(
            SCIENCEDIRECT_SEARCH_URL,
            {"query": config.query, "count": str(config.limit)},
            {"X-ELS-APIKey": config.elsevier_api_key},
        )
        search = payload.get("search-results") or {}
        entries = search.get("entry") or []
        total = self._safe_total(search.get("opensearch:totalResults"), len(entries))
        return self._result(
            "ScienceDirect",
            SourceRole.PUBLISHER,
            total,
            True,
            SCIENCEDIRECT_SEARCH_URL,
            f"Busca editorial; {len(entries)} registros recuperados na amostra.",
        )

    @staticmethod
    def _fixed_results() -> tuple[SourceAuditResult, ...]:
        return (
            SourceAuditResult(
                source="Nature",
                role=SourceRole.PUBLISHER,
                status=SourceProbeStatus.COVERED_BY_OTHER,
                result_count=None,
                query_specific=False,
                endpoint="https://www.nature.com/",
                detail=(
                    "Marca editorial, não índice independente nesta arquitetura; seus "
                    "artigos podem aparecer em PubMed, Crossref, OpenAlex e Springer Nature."
                ),
            ),
            SourceAuditResult(
                source="Google Acadêmico",
                role=SourceRole.MANUAL,
                status=SourceProbeStatus.MANUAL_ONLY,
                result_count=None,
                query_specific=False,
                endpoint="https://scholar.google.com/",
                detail="Sem API pública suportada no projeto; mantido como conferência manual.",
            ),
        )

    @staticmethod
    def _error(source: str, role: SourceRole, endpoint: str, error: Exception) -> SourceAuditResult:
        return SourceAuditResult(
            source=source,
            role=role,
            status=SourceProbeStatus.ERROR,
            result_count=None,
            query_specific=False,
            endpoint=endpoint,
            detail=str(error),
        )

    def audit(self, config: SourceAuditConfig) -> SourceAuditReport:
        results: list[SourceAuditResult] = []
        pubmed_ids: tuple[str, ...] = ()
        try:
            pubmed, pubmed_ids = self._pubmed(config)
            results.append(pubmed)
        except Exception as error:
            results.append(
                self._error("PubMed", SourceRole.DISCOVERY, PUBMED_SEARCH_URL, error)
            )

        probes = (
            (
                "PubMed Central (PMC)",
                SourceRole.CONTENT,
                PMC_ID_CONVERTER_URL,
                lambda: self._pmc(config, pubmed_ids),
            ),
            (
                "ClinicalTrials.gov",
                SourceRole.VALIDATION,
                CLINICAL_TRIALS_SEARCH_URL,
                lambda: self._clinical_trials(config),
            ),
            ("Crossref", SourceRole.VALIDATION, CROSSREF_WORKS_URL, lambda: self._crossref(config)),
            (
                "Retraction Watch (via Crossref)",
                SourceRole.VALIDATION,
                CROSSREF_WORKS_URL,
                lambda: self._retraction_watch(config),
            ),
            ("OpenAlex", SourceRole.DISCOVERY, OPENALEX_WORKS_URL, lambda: self._openalex(config)),
            ("DataCite", SourceRole.VALIDATION, DATACITE_DOIS_URL, lambda: self._datacite(config)),
            ("SciELO", SourceRole.DISCOVERY, SCIELO_ARTICLE_IDENTIFIERS_URL, lambda: self._scielo(config)),
            (
                "Springer Nature Meta",
                SourceRole.PUBLISHER,
                SPRINGER_META_URL,
                lambda: self._springer(config),
            ),
            (
                "Springer Nature Open Access",
                SourceRole.CONTENT,
                SPRINGER_OPENACCESS_URL,
                lambda: self._springer_open_access(config),
            ),
            ("ScienceDirect", SourceRole.PUBLISHER, SCIENCEDIRECT_SEARCH_URL, lambda: self._science_direct(config)),
        )
        for source, role, endpoint, probe in probes:
            try:
                results.append(probe())
            except Exception as error:
                results.append(self._error(source, role, endpoint, error))
        results.extend(self._fixed_results())
        return SourceAuditReport(query=config.query.strip(), results=tuple(results))
