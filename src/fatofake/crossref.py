"""Resolução de DOI e conferência de identidade por metadados do Crossref."""

from __future__ import annotations

import html
import json
import re
import ssl
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .pubmed import Publication
from .transport import default_ssl_context


CROSSREF_BASE_URL = "https://api.crossref.org/works"
TITLE_MATCH_THRESHOLD = 0.85
JsonFetcher = Callable[[str, Mapping[str, str], Mapping[str, str]], Mapping[str, Any]]


class CrossrefError(RuntimeError):
    """Falha de comunicação ou de formato na resposta do Crossref."""


class CrossrefNotFoundError(CrossrefError):
    """O DOI não foi localizado no Crossref."""


@dataclass(frozen=True)
class CrossrefUpdate:
    """Atualização editorial ligada ao registro, incluindo retratações."""

    update_type: str
    label: str | None
    source: str | None
    doi: str | None
    record_id: str | None


@dataclass(frozen=True)
class CrossrefWork:
    """Metadados externos normalizados de uma obra registrada."""

    doi: str
    title: str
    authors: tuple[str, ...]
    journal: str | None
    publisher: str | None
    publication_date: str | None
    work_type: str | None
    url: str
    updates: tuple[CrossrefUpdate, ...] = ()


@dataclass(frozen=True)
class IdentityVerification:
    """Resultado da conferência entre PubMed e Crossref."""

    pmid: str
    doi: str | None
    status: str
    title_similarity: float | None
    pubmed_title: str
    crossref_title: str | None
    crossref_url: str | None
    crossref_journal: str | None
    crossref_publisher: str | None
    crossref_publication_date: str | None
    reason: str
    crossref_updates: tuple[CrossrefUpdate, ...] = ()


def _updates(message: Mapping[str, Any]) -> tuple[CrossrefUpdate, ...]:
    normalized: list[CrossrefUpdate] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for field in ("updated-by", "update-to"):
        for item in message.get(field) or []:
            update_type = str(item.get("type") or "").strip().casefold()
            if not update_type:
                continue
            doi = str(item["DOI"]).strip() if item.get("DOI") else None
            source = str(item["source"]).strip() if item.get("source") else None
            key = (update_type, doi, source)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                CrossrefUpdate(
                    update_type=update_type,
                    label=str(item["label"]).strip() if item.get("label") else None,
                    source=source,
                    doi=doi,
                    record_id=str(item["record-id"]) if item.get("record-id") else None,
                )
            )
    return tuple(normalized)


def _first_text(value: Any) -> str | None:
    if isinstance(value, list) and value:
        text = str(value[0]).strip()
        return text or None
    if isinstance(value, str):
        return value.strip() or None
    return None


def _publication_date(message: Mapping[str, Any]) -> str | None:
    for field in ("published-print", "published-online", "published", "issued"):
        date_parts = (message.get(field) or {}).get("date-parts")
        if not date_parts or not date_parts[0]:
            continue
        parts = [int(part) for part in date_parts[0][:3]]
        return "-".join(
            [str(parts[0]), *(f"{part:02d}" for part in parts[1:])]
        )
    return None


def _normalize_title(title: str) -> str:
    without_markup = re.sub(r"<[^>]+>", " ", html.unescape(title))
    normalized = unicodedata.normalize("NFKD", without_markup).casefold()
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _title_similarity(left: str, right: str) -> float:
    return round(SequenceMatcher(None, _normalize_title(left), _normalize_title(right)).ratio(), 4)


class CrossrefClient:
    """Recupera um registro Crossref pelo DOI."""

    def __init__(
        self,
        *,
        email: str | None = None,
        timeout: float = 20.0,
        fetch_json: JsonFetcher | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.email = email
        self.timeout = timeout
        self._last_request_at: float | None = None
        self._fetch_json = fetch_json or self._request_json
        self._ssl_context = ssl_context or default_ssl_context()

    def _request_json(
        self,
        path: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> Mapping[str, Any]:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < 0.1:
                time.sleep(0.1 - elapsed)

        query_string = f"?{urlencode(params)}" if params else ""
        request = Request(f"{CROSSREF_BASE_URL}/{path}{query_string}", headers=dict(headers))
        try:
            with urlopen(
                request,
                timeout=self.timeout,
                context=self._ssl_context,
            ) as response:
                payload = json.load(response)
        except HTTPError as error:
            if error.code == 404:
                raise CrossrefNotFoundError("DOI não localizado no Crossref.") from error
            raise CrossrefError(f"Falha HTTP ao consultar o Crossref: {error}") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise CrossrefError(f"Falha ao consultar o Crossref: {error}") from error
        finally:
            self._last_request_at = time.monotonic()

        if not isinstance(payload, dict):
            raise CrossrefError("O Crossref retornou uma resposta JSON inesperada.")
        return payload

    def fetch_work(self, doi: str) -> CrossrefWork:
        normalized_doi = doi.strip().lower()
        params = {"mailto": self.email} if self.email else {}
        agent = "FatoOuFake/0.1"
        if self.email:
            agent = f"{agent} (mailto:{self.email})"
        payload = self._fetch_json(
            quote(normalized_doi, safe=""),
            params,
            {"User-Agent": agent},
        )

        try:
            message = payload["message"]
            returned_doi = str(message["DOI"]).strip()
            title = _first_text(message["title"])
        except (KeyError, TypeError) as error:
            raise CrossrefError("Resposta Crossref inválida ou incompleta.") from error
        if not title:
            raise CrossrefError("O registro Crossref não possui título.")

        authors: list[str] = []
        for author in message.get("author") or []:
            name = " ".join(
                part for part in (author.get("given"), author.get("family")) if part
            ).strip()
            if name:
                authors.append(name)

        return CrossrefWork(
            doi=returned_doi,
            title=title,
            authors=tuple(authors),
            journal=_first_text(message.get("container-title")),
            publisher=str(message["publisher"]).strip() if message.get("publisher") else None,
            publication_date=_publication_date(message),
            work_type=str(message["type"]).strip() if message.get("type") else None,
            url=str(message.get("URL") or f"https://doi.org/{returned_doi}").strip(),
            updates=_updates(message),
        )


def verify_publication_identity(
    publication: Publication,
    client: CrossrefClient,
) -> IdentityVerification:
    """Confere DOI e título sem interpretar a qualidade científica do artigo."""

    if not publication.doi:
        return IdentityVerification(
            pmid=publication.pmid,
            doi=None,
            status="NOT_CHECKED",
            title_similarity=None,
            pubmed_title=publication.title,
            crossref_title=None,
            crossref_url=None,
            crossref_journal=None,
            crossref_publisher=None,
            crossref_publication_date=None,
            reason="O registro do PubMed não informou DOI.",
        )

    try:
        work = client.fetch_work(publication.doi)
    except CrossrefNotFoundError:
        return IdentityVerification(
            pmid=publication.pmid,
            doi=publication.doi,
            status="NOT_FOUND",
            title_similarity=None,
            pubmed_title=publication.title,
            crossref_title=None,
            crossref_url=None,
            crossref_journal=None,
            crossref_publisher=None,
            crossref_publication_date=None,
            reason="O DOI informado pelo PubMed não foi localizado no Crossref.",
        )

    doi_matches = publication.doi.casefold() == work.doi.casefold()
    similarity = _title_similarity(publication.title, work.title)
    verified = doi_matches and similarity >= TITLE_MATCH_THRESHOLD
    return IdentityVerification(
        pmid=publication.pmid,
        doi=publication.doi,
        status="VERIFIED" if verified else "REVIEW_REQUIRED",
        title_similarity=similarity,
        pubmed_title=publication.title,
        crossref_title=work.title,
        crossref_url=work.url,
        crossref_journal=work.journal,
        crossref_publisher=work.publisher,
        crossref_publication_date=work.publication_date,
        reason=(
            "DOI resolvido e título compatível entre PubMed e Crossref."
            if verified
            else "Os metadados apresentam diferença que requer revisão."
        ),
        crossref_updates=work.updates,
    )


def verify_publications(
    publications: tuple[Publication, ...],
    client: CrossrefClient,
) -> tuple[IdentityVerification, ...]:
    """Confere uma coleção preservando a ordem recebida."""

    return tuple(verify_publication_identity(publication, client) for publication in publications)
