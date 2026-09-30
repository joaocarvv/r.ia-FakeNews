"""Busca federada, normalização e deduplicação de trabalhos científicos."""

from __future__ import annotations

import json
import re
import ssl
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .pubmed import PubMedClient, PubMedError, Publication
from .retrieval import RetrievalError
from .search_preparation import SearchPlan
from .transport import default_ssl_context


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
SCIELO_SOURCE_LIST_FILTER = "primary_location.source.listed_in:scielo"
JsonFetcher = Callable[[str, Mapping[str, str]], Mapping[str, Any]]
Sleeper = Callable[[float], None]
TRANSIENT_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})


class FederatedSearchError(RetrievalError):
    """Nenhuma fonte conseguiu executar o plano de busca."""


@dataclass(frozen=True)
class SourceRank:
    """Posição de um registro em uma fonte e consulta específicas."""

    source: str
    query: str
    rank: int


@dataclass(frozen=True)
class ScientificWork:
    """Representação canônica de um trabalho, inclusive sem PMID."""

    title: str
    authors: tuple[str, ...]
    journal: str | None
    publication_date: str | None
    doi: str | None
    pmid: str | None
    url: str
    matched_queries: tuple[str, ...]
    sources: tuple[str, ...]
    source_ids: tuple[tuple[str, str], ...]
    source_ranks: tuple[SourceRank, ...]
    retrieval_score: float = 0.0

    def to_publication(self) -> Publication | None:
        """Converte apenas trabalhos vinculados ao PubMed para o fluxo atual."""

        if self.pmid is None:
            return None
        return Publication(
            pmid=self.pmid,
            title=self.title,
            authors=self.authors,
            journal=self.journal,
            publication_date=self.publication_date,
            doi=self.doi,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/",
            matched_queries=self.matched_queries,
            source=", ".join(self.sources),
        )


@dataclass(frozen=True)
class ProviderSearchResult:
    source: str
    query: str
    total_matches: int
    works: tuple[ScientificWork, ...]


@dataclass(frozen=True)
class FederatedQueryResult:
    source: str
    query: str
    total_matches: int
    retrieved_count: int


@dataclass(frozen=True)
class SourceSearchFailure:
    source: str
    query: str
    reason: str


@dataclass(frozen=True)
class FederatedSearchResult:
    """Resultado completo e subconjunto atualmente processável pelo PMC."""

    query_results: tuple[FederatedQueryResult, ...]
    works: tuple[ScientificWork, ...]
    publications: tuple[Publication, ...]
    unresolved_works: tuple[ScientificWork, ...]
    failures: tuple[SourceSearchFailure, ...]


class ArticleSearchProvider(Protocol):
    name: str

    def search(self, query: str, *, max_results: int) -> ProviderSearchResult: ...


def normalize_doi(value: str | None) -> str | None:
    """Normaliza DOI informado como identificador, URL ou prefixado por ``doi:``."""

    if not value:
        return None
    normalized = value.strip().casefold()
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"^doi:\s*", "", normalized)
    normalized = normalized.rstrip(" .;,)")
    return normalized or None


def normalize_pmid(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?:pubmed\.ncbi\.nlm\.nih\.gov/)?(\d+)(?:/)?$", value.strip())
    return match.group(1) if match else None


def _comparison_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text))


def _publication_year(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b(?:19|20)\d{2}\b", value)
    return match.group(0) if match else None


def _first_author_key(authors: Sequence[str]) -> str | None:
    if not authors:
        return None
    normalized = _comparison_text(authors[0])
    return normalized or None


def _identity_keys(work: ScientificWork) -> tuple[str, ...]:
    keys: list[str] = []
    doi = normalize_doi(work.doi)
    pmid = normalize_pmid(work.pmid)
    if doi:
        keys.append(f"doi:{doi}")
    if pmid:
        keys.append(f"pmid:{pmid}")

    title = _comparison_text(work.title)
    year = _publication_year(work.publication_date)
    author = _first_author_key(work.authors)
    if title and year and author:
        keys.append(f"metadata:{title}|{year}|{author}")
    return tuple(keys)


def _first_nonempty(records: Sequence[ScientificWork], field: str) -> Any:
    for record in records:
        value = getattr(record, field)
        if value:
            return value
    return None


def deduplicate_works(
    works: Sequence[ScientificWork],
    *,
    source_order: Sequence[str] = (),
) -> tuple[ScientificWork, ...]:
    """Agrupa identidades transitivamente por DOI, PMID ou título/ano/autor."""

    if not works:
        return ()

    parents = list(range(len(works)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    seen_keys: dict[str, int] = {}
    for index, work in enumerate(works):
        for key in _identity_keys(work):
            previous = seen_keys.get(key)
            if previous is None:
                seen_keys[key] = index
            else:
                union(previous, index)

    groups: dict[int, list[tuple[int, ScientificWork]]] = {}
    for index, work in enumerate(works):
        groups.setdefault(find(index), []).append((index, work))

    priority = {source: index for index, source in enumerate(source_order)}
    merged: list[tuple[int, ScientificWork]] = []
    for records_with_index in groups.values():
        first_seen = min(index for index, _ in records_with_index)
        records = [record for _, record in records_with_index]
        records.sort(
            key=lambda record: min(
                (priority.get(source, len(priority)) for source in record.sources),
                default=len(priority),
            )
        )

        sources = tuple(
            dict.fromkeys(source for record in records for source in record.sources)
        )
        source_ids = tuple(
            dict.fromkeys(item for record in records for item in record.source_ids)
        )
        source_ranks = tuple(
            dict.fromkeys(item for record in records for item in record.source_ranks)
        )
        matched_queries = tuple(
            dict.fromkeys(query for record in records for query in record.matched_queries)
        )
        score = sum(1.0 / (60 + item.rank) for item in source_ranks)
        doi = next(
            (normalize_doi(record.doi) for record in records if normalize_doi(record.doi)),
            None,
        )
        pmid = next(
            (
                normalize_pmid(record.pmid)
                for record in records
                if normalize_pmid(record.pmid)
            ),
            None,
        )
        merged.append(
            (
                first_seen,
                ScientificWork(
                    title=_first_nonempty(records, "title") or "Título indisponível",
                    authors=_first_nonempty(records, "authors") or (),
                    journal=_first_nonempty(records, "journal"),
                    publication_date=_first_nonempty(records, "publication_date"),
                    doi=doi,
                    pmid=pmid,
                    url=_first_nonempty(records, "url") or "",
                    matched_queries=matched_queries,
                    sources=sources,
                    source_ids=source_ids,
                    source_ranks=source_ranks,
                    retrieval_score=score,
                ),
            )
        )

    merged.sort(key=lambda item: (-item[1].retrieval_score, item[0]))
    return tuple(work for _, work in merged)


class PubMedSearchProvider:
    name = "PubMed"

    def __init__(self, client: PubMedClient) -> None:
        self.client = client

    def search(self, query: str, *, max_results: int) -> ProviderSearchResult:
        total, identifiers = self.client.search_ids(query, max_results=max_results)
        matches = {identifier: (query,) for identifier in identifiers}
        publications = self.client.fetch_summaries(identifiers, matches)
        works = tuple(
            ScientificWork(
                title=item.title,
                authors=item.authors,
                journal=item.journal,
                publication_date=item.publication_date,
                doi=normalize_doi(item.doi),
                pmid=normalize_pmid(item.pmid),
                url=item.url,
                matched_queries=(query,),
                sources=(self.name,),
                source_ids=((self.name, item.pmid),),
                source_ranks=(SourceRank(self.name, query, rank),),
            )
            for rank, item in enumerate(publications, start=1)
        )
        return ProviderSearchResult(self.name, query, total, works)


class OpenAlexClient:
    """Cliente mínimo do endpoint de trabalhos do OpenAlex."""

    def __init__(
        self,
        *,
        email: str | None = None,
        api_key: str | None = None,
        timeout: float = 20.0,
        max_attempts: int = 3,
        retry_delay: float = 0.5,
        fetch_json: JsonFetcher | None = None,
        sleep: Sleeper = time.sleep,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if timeout <= 0:
            raise RetrievalError("O timeout do OpenAlex deve ser maior que zero.")
        if not 1 <= max_attempts <= 5:
            raise RetrievalError("max_attempts do OpenAlex deve estar entre 1 e 5.")
        if retry_delay < 0:
            raise RetrievalError("retry_delay do OpenAlex não pode ser negativo.")
        self.email = email
        self.api_key = api_key
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self._sleep = sleep
        self._fetch_json = fetch_json or self._request_json
        self._ssl_context = ssl_context or default_ssl_context()

    def _request_json(
        self, url: str, params: Mapping[str, str]
    ) -> Mapping[str, Any]:
        request = Request(
            f"{url}?{urlencode(params)}",
            headers={"User-Agent": "FatoOuFake/0.1"},
        )
        payload: Any = None
        for attempt in range(self.max_attempts):
            try:
                with urlopen(
                    request,
                    timeout=self.timeout,
                    context=self._ssl_context,
                ) as response:
                    payload = json.load(response)
                break
            except HTTPError as error:
                can_retry = (
                    error.code in TRANSIENT_HTTP_STATUS
                    and attempt + 1 < self.max_attempts
                )
                if not can_retry:
                    raise RetrievalError(
                        f"Falha ao consultar o OpenAlex: {error}"
                    ) from error
                self._sleep(self.retry_delay * (2**attempt))
            except (URLError, TimeoutError, json.JSONDecodeError) as error:
                raise RetrievalError(f"Falha ao consultar o OpenAlex: {error}") from error
        if not isinstance(payload, dict):
            raise RetrievalError("O OpenAlex retornou JSON inesperado.")
        return payload

    def search_works(
        self,
        query: str,
        *,
        max_results: int,
        source_filter: str | None = None,
    ) -> tuple[int, tuple[Mapping[str, Any], ...]]:
        if not 1 <= max_results <= 100:
            raise ValueError("max_results deve estar entre 1 e 100.")
        params = {
            "search": query,
            "per_page": str(max_results),
            "sort": "-relevance_score",
        }
        if source_filter:
            params["filter"] = source_filter
        if self.email:
            params["mailto"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        payload = self._fetch_json(OPENALEX_WORKS_URL, params)
        raw_results = payload.get("results") or []
        if not isinstance(raw_results, list):
            raise RetrievalError("Resposta de resultados do OpenAlex inválida.")
        try:
            total = max(int((payload.get("meta") or {}).get("count", len(raw_results))), 0)
        except (TypeError, ValueError) as error:
            raise RetrievalError("Contagem do OpenAlex inválida.") from error
        results = tuple(item for item in raw_results if isinstance(item, Mapping))
        return total, results


class OpenAlexSearchProvider:
    """Normaliza o OpenAlex geral ou uma lista de fontes selecionada."""

    def __init__(
        self,
        client: OpenAlexClient,
        *,
        name: str = "OpenAlex",
        source_filter: str | None = None,
    ) -> None:
        self.client = client
        self.name = name
        self.source_filter = source_filter

    @staticmethod
    def _text(value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    def _normalize(self, item: Mapping[str, Any], query: str, rank: int) -> ScientificWork:
        ids = item.get("ids") if isinstance(item.get("ids"), Mapping) else {}
        primary = (
            item.get("primary_location")
            if isinstance(item.get("primary_location"), Mapping)
            else {}
        )
        source = primary.get("source") if isinstance(primary.get("source"), Mapping) else {}
        authors: list[str] = []
        for authorship in item.get("authorships") or []:
            if not isinstance(authorship, Mapping):
                continue
            author = authorship.get("author")
            if not isinstance(author, Mapping):
                continue
            name = self._text(author.get("display_name"))
            if name:
                authors.append(name)

        openalex_id = self._text(item.get("id")) or "unknown"
        doi = normalize_doi(self._text(item.get("doi")) or self._text(ids.get("doi")))
        pmid = normalize_pmid(self._text(ids.get("pmid")))
        url = (
            self._text(primary.get("landing_page_url"))
            or (f"https://doi.org/{doi}" if doi else None)
            or openalex_id
        )
        title = self._text(item.get("display_name")) or self._text(item.get("title"))
        if not title:
            title = "Título indisponível"
        publication_date = self._text(item.get("publication_date"))
        if not publication_date and item.get("publication_year"):
            publication_date = str(item["publication_year"])
        return ScientificWork(
            title=title,
            authors=tuple(authors),
            journal=self._text(source.get("display_name")),
            publication_date=publication_date,
            doi=doi,
            pmid=pmid,
            url=url,
            matched_queries=(query,),
            sources=(self.name,),
            source_ids=((self.name, openalex_id),),
            source_ranks=(SourceRank(self.name, query, rank),),
        )

    def search(self, query: str, *, max_results: int) -> ProviderSearchResult:
        total, records = self.client.search_works(
            query,
            max_results=max_results,
            source_filter=self.source_filter,
        )
        works = tuple(
            self._normalize(item, query, rank)
            for rank, item in enumerate(records, start=1)
        )
        return ProviderSearchResult(self.name, query, total, works)


class ScieloSearchProvider(OpenAlexSearchProvider):
    """Busca temática em periódicos da lista SciELO, indexados pelo OpenAlex."""

    def __init__(self, client: OpenAlexClient) -> None:
        super().__init__(
            client,
            name="SciELO (via OpenAlex)",
            source_filter=SCIELO_SOURCE_LIST_FILTER,
        )


class FederatedSearchEngine:
    """Executa todas as fontes, isola falhas e aplica RRF antes do processamento."""

    def __init__(self, providers: Sequence[ArticleSearchProvider]) -> None:
        if not providers:
            raise RetrievalError("A busca federada exige ao menos uma fonte.")
        names = [provider.name for provider in providers]
        if len(names) != len(set(names)):
            raise RetrievalError("Cada fonte federada deve possuir um nome único.")
        self.providers = tuple(providers)

    def search(
        self,
        search_plan: SearchPlan,
        *,
        max_results_per_query: int = 5,
    ) -> FederatedSearchResult:
        if not 1 <= max_results_per_query <= 100:
            raise RetrievalError("max_results_per_query deve estar entre 1 e 100.")

        query_results: list[FederatedQueryResult] = []
        failures: list[SourceSearchFailure] = []
        raw_works: list[ScientificWork] = []
        for provider in self.providers:
            for query in search_plan.queries:
                try:
                    result = provider.search(query, max_results=max_results_per_query)
                except (PubMedError, RetrievalError, ValueError) as error:
                    failures.append(
                        SourceSearchFailure(provider.name, query, str(error))
                    )
                    continue
                query_results.append(
                    FederatedQueryResult(
                        source=result.source,
                        query=result.query,
                        total_matches=result.total_matches,
                        retrieved_count=len(result.works),
                    )
                )
                raw_works.extend(result.works)

        if not query_results:
            raise FederatedSearchError(
                "Todas as fontes científicas falharam durante a busca federada."
            )

        source_order = tuple(provider.name for provider in self.providers)
        works = deduplicate_works(raw_works, source_order=source_order)
        publications: list[Publication] = []
        unresolved: list[ScientificWork] = []
        for work in works:
            publication = work.to_publication()
            if publication is None:
                unresolved.append(work)
            else:
                publications.append(publication)
        return FederatedSearchResult(
            query_results=tuple(query_results),
            works=works,
            publications=tuple(publications),
            unresolved_works=tuple(unresolved),
            failures=tuple(failures),
        )
