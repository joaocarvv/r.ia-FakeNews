"""Cliente PubMed baseado nas E-utilities oficiais do NCBI."""

from __future__ import annotations

import json
import ssl
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .search_preparation import SearchPlan
from .transport import default_ssl_context


EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
JsonFetcher = Callable[[str, Mapping[str, str]], Mapping[str, Any]]

class PubMedError(RuntimeError):
    """Falha de comunicação ou de formato na resposta do PubMed."""


@dataclass(frozen=True)
class Publication:
    """Representação canônica inicial de um artigo recuperado."""

    pmid: str
    title: str
    authors: tuple[str, ...]
    journal: str | None
    publication_date: str | None
    doi: str | None
    url: str
    matched_queries: tuple[str, ...]
    source: str = "PubMed"


@dataclass(frozen=True)
class QueryResult:
    """Quantidade total informada pelo PubMed para uma consulta."""

    query: str
    total_matches: int


@dataclass(frozen=True)
class PubMedSearchResult:
    """Resultado normalizado de todas as consultas de um plano."""

    query_results: tuple[QueryResult, ...]
    publications: tuple[Publication, ...]


class PubMedClient:
    """Executa ESearch e ESummary respeitando o limite básico do NCBI."""

    def __init__(
        self,
        *,
        email: str | None = None,
        api_key: str | None = None,
        timeout: float = 20.0,
        fetch_json: JsonFetcher | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.email = email
        self.api_key = api_key
        self.timeout = timeout
        self._last_request_at: float | None = None
        self._fetch_json = fetch_json or self._request_json
        self._ssl_context = ssl_context or default_ssl_context()

    def _request_json(self, endpoint: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        minimum_interval = 0.11 if self.api_key else 0.34
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < minimum_interval:
                time.sleep(minimum_interval - elapsed)

        url = f"{EUTILS_BASE_URL}/{endpoint}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "FatoOuFake/0.1"})
        try:
            with urlopen(
                request,
                timeout=self.timeout,
                context=self._ssl_context,
            ) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise PubMedError(f"Falha ao consultar o PubMed: {error}") from error
        finally:
            self._last_request_at = time.monotonic()

        if not isinstance(payload, dict):
            raise PubMedError("O PubMed retornou uma resposta JSON inesperada.")
        return payload

    def _common_params(self) -> dict[str, str]:
        params = {"db": "pubmed", "retmode": "json", "tool": "fatofake"}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def search_ids(self, query: str, *, max_results: int) -> tuple[int, tuple[str, ...]]:
        if not 1 <= max_results <= 100:
            raise ValueError("max_results deve estar entre 1 e 100.")

        params = self._common_params()
        params.update({"term": query, "retmax": str(max_results), "sort": "relevance"})
        payload = self._fetch_json("esearch.fcgi", params)

        try:
            result = payload["esearchresult"]
            total = int(result["count"])
            identifiers = tuple(str(identifier) for identifier in result["idlist"])
        except (KeyError, TypeError, ValueError) as error:
            raise PubMedError("Resposta ESearch inválida ou incompleta.") from error

        return total, identifiers

    def fetch_summaries(
        self,
        identifiers: tuple[str, ...],
        matched_queries: Mapping[str, tuple[str, ...]],
    ) -> tuple[Publication, ...]:
        if not identifiers:
            return ()

        params = self._common_params()
        params["id"] = ",".join(identifiers)
        payload = self._fetch_json("esummary.fcgi", params)

        try:
            result = payload["result"]
        except (KeyError, TypeError) as error:
            raise PubMedError("Resposta ESummary inválida ou incompleta.") from error

        publications: list[Publication] = []
        for identifier in identifiers:
            try:
                document = result[identifier]
                title = str(document["title"]).strip()
            except (KeyError, TypeError) as error:
                raise PubMedError(f"Resumo ausente ou inválido para o PMID {identifier}.") from error

            article_ids = document.get("articleids") or []
            doi = next(
                (
                    str(article_id.get("value")).strip()
                    for article_id in article_ids
                    if article_id.get("idtype") == "doi" and article_id.get("value")
                ),
                None,
            )
            authors = tuple(
                str(author.get("name")).strip()
                for author in (document.get("authors") or [])
                if author.get("name")
            )
            publication_date = document.get("epubdate") or document.get("pubdate") or None
            journal = document.get("fulljournalname") or document.get("source") or None

            publications.append(
                Publication(
                    pmid=identifier,
                    title=title,
                    authors=authors,
                    journal=str(journal).strip() if journal else None,
                    publication_date=str(publication_date).strip() if publication_date else None,
                    doi=doi,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{identifier}/",
                    matched_queries=matched_queries.get(identifier, ()),
                )
            )

        return tuple(publications)


def search_pubmed(
    search_plan: SearchPlan,
    client: PubMedClient,
    *,
    max_results_per_query: int = 5,
) -> PubMedSearchResult:
    """Executa o plano, consolida PMIDs e normaliza os artigos recuperados."""

    query_results: list[QueryResult] = []
    ordered_identifiers: list[str] = []
    matches: dict[str, list[str]] = defaultdict(list)

    for query in search_plan.queries:
        total, identifiers = client.search_ids(query, max_results=max_results_per_query)
        query_results.append(QueryResult(query=query, total_matches=total))
        for identifier in identifiers:
            if identifier not in matches:
                ordered_identifiers.append(identifier)
            matches[identifier].append(query)

    normalized_matches = {
        identifier: tuple(queries) for identifier, queries in matches.items()
    }
    publications = client.fetch_summaries(tuple(ordered_identifiers), normalized_matches)
    return PubMedSearchResult(tuple(query_results), publications)
