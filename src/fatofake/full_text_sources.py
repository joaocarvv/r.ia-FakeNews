"""Localiza versões abertas do texto integral de estudos recuperados.

Consulta apenas serviços que indexam cópias legalmente abertas (Europe PMC,
Unpaywall, Semantic Scholar e o link aberto informado pelo OpenAlex). Não tenta
contornar paywall: para artigos fechados, o usuário pode enviar o próprio PDF.
"""

from __future__ import annotations

import json
import logging
import ssl
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .transport import default_ssl_context


logger = logging.getLogger(__name__)

EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/DOI:"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
CORE_SEARCH_URL = "https://api.core.ac.uk/v3/search/works"

JsonGetter = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True)
class FullTextCandidate:
    url: str
    source: str
    is_pdf: bool


@dataclass(frozen=True)
class FullTextLead:
    """O que os serviços abertos sabem sobre um DOI."""

    abstract: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    candidates: tuple[FullTextCandidate, ...] = ()
    consulted: tuple[str, ...] = field(default_factory=tuple)


class FullTextLocator:
    def __init__(
        self,
        *,
        email: str | None = None,
        core_api_key: str | None = None,
        timeout: float = 15.0,
        get_json: JsonGetter | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.email = email
        self.core_api_key = core_api_key
        self.timeout = timeout
        self._ssl_context = ssl_context or default_ssl_context()
        self._get_json = get_json or self._request_json

    def _request_json(self, url: str) -> Mapping[str, Any]:
        request = Request(
            url,
            headers={
                "User-Agent": f"FatoOuFake/0.1 (mailto:{self.email or 'unknown'})",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=self.timeout, context=self._ssl_context) as response:
            return json.loads(response.read(5_000_000).decode("utf-8"))

    def _safe_get(self, url: str, source: str) -> Mapping[str, Any] | None:
        try:
            payload = self._get_json(url)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            logger.info("Fonte de texto integral indisponível (%s): %s", source, error)
            return None
        return payload if isinstance(payload, Mapping) else None

    def _europe_pmc(
        self, doi: str | None, pmid: str | None
    ) -> tuple[dict[str, Any], list[FullTextCandidate]]:
        if doi:
            search = f'DOI:"{doi}"'
        elif pmid:
            search = f"EXT_ID:{pmid} AND SRC:MED"
        else:
            return {}, []
        query = urlencode(
            {"query": search, "resultType": "core", "format": "json", "pageSize": "1"}
        )
        payload = self._safe_get(f"{EUROPE_PMC_SEARCH_URL}?{query}", "Europe PMC")
        results = ((payload or {}).get("resultList") or {}).get("result") or []
        if not results:
            return {}, []
        record = results[0]
        candidates = []
        for item in ((record.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
            availability = str(item.get("availabilityCode") or "").upper()
            url = str(item.get("url") or "")
            if availability in {"OA", "F"} and url.startswith("https://"):
                candidates.append(
                    FullTextCandidate(
                        url=url,
                        source="Europe PMC",
                        is_pdf=str(item.get("documentStyle") or "").lower() == "pdf",
                    )
                )
        info = {
            "abstract": " ".join(str(record.get("abstractText") or "").split()) or None,
            "pmid": str(record.get("pmid") or "") or None,
            "pmcid": str(record.get("pmcid") or "") or None,
            "doi": str(record.get("doi") or "") or None,
        }
        return info, candidates

    def _openalex_locations(self, doi: str) -> list[FullTextCandidate]:
        """Todas as cópias abertas (repositórios, manuscritos), não só a principal."""

        params = {"select": "locations"}
        if self.email:
            params["mailto"] = self.email
        payload = self._safe_get(
            f"{OPENALEX_WORKS_URL}/doi:{quote(doi)}?{urlencode(params)}", "OpenAlex"
        )
        candidates = []
        for location in (payload or {}).get("locations") or []:
            if not location.get("is_oa"):
                continue
            pdf = str(location.get("pdf_url") or "")
            landing = str(location.get("landing_page_url") or "")
            if pdf.startswith("https://"):
                candidates.append(FullTextCandidate(pdf, "OpenAlex (repositório)", True))
            if landing.startswith("https://") and "doi.org" not in landing:
                candidates.append(FullTextCandidate(landing, "OpenAlex (repositório)", False))
        return candidates

    def _core(self, doi: str) -> list[FullTextCandidate]:
        """CORE agrega texto integral de repositórios institucionais (chave gratuita)."""

        if not self.core_api_key:
            return []
        query = urlencode({"q": f'doi:"{doi}"', "limit": "3", "api_key": self.core_api_key})
        payload = self._safe_get(f"{CORE_SEARCH_URL}?{query}", "CORE")
        candidates = []
        for item in (payload or {}).get("results") or []:
            url = str(item.get("downloadUrl") or "")
            if url.startswith("https://"):
                candidates.append(FullTextCandidate(url, "CORE", True))
        return candidates

    def _unpaywall(self, doi: str) -> list[FullTextCandidate]:
        if not self.email:
            return []
        payload = self._safe_get(
            f"{UNPAYWALL_URL}{quote(doi)}?{urlencode({'email': self.email})}",
            "Unpaywall",
        )
        candidates = []
        for location in (payload or {}).get("oa_locations") or []:
            for key, is_pdf in (("url_for_pdf", True), ("url_for_landing_page", False)):
                url = str(location.get(key) or "")
                if url.startswith("https://"):
                    candidates.append(FullTextCandidate(url, "Unpaywall", is_pdf))
        return candidates

    def _semantic_scholar(self, doi: str) -> list[FullTextCandidate]:
        payload = self._safe_get(
            f"{SEMANTIC_SCHOLAR_URL}{quote(doi)}?fields=openAccessPdf",
            "Semantic Scholar",
        )
        url = str(((payload or {}).get("openAccessPdf") or {}).get("url") or "")
        return [FullTextCandidate(url, "Semantic Scholar", True)] if url.startswith("https://") else []

    def locate(
        self,
        doi: str | None,
        *,
        known_url: str | None = None,
        pmid: str | None = None,
    ) -> FullTextLead:
        candidates: list[FullTextCandidate] = []
        consulted = ["OpenAlex"]
        if known_url and known_url.startswith("https://"):
            candidates.append(FullTextCandidate(known_url, "OpenAlex", known_url.lower().endswith(".pdf")))
        info: dict[str, Any] = {}
        if doi or pmid:
            info, europe = self._europe_pmc(doi, pmid)
            consulted.append("Europe PMC")
            candidates += europe
            # Registros antigos do PubMed às vezes só ganham DOI pelo Europe PMC.
            doi = doi or info.get("doi")
        if doi:
            candidates += self._openalex_locations(doi)
            candidates += self._unpaywall(doi)
            candidates += self._semantic_scholar(doi)
            candidates += self._core(doi)
            consulted += [
                *(("Unpaywall",) if self.email else ()),
                "Semantic Scholar",
                *(("CORE",) if self.core_api_key else ()),
            ]
        unique: dict[str, FullTextCandidate] = {}
        for item in candidates:
            unique.setdefault(item.url, item)
        # PDFs primeiro: o parser preserva página e faz OCR quando necessário.
        ordered = sorted(unique.values(), key=lambda item: not item.is_pdf)
        return FullTextLead(
            abstract=info.get("abstract"),
            pmid=info.get("pmid"),
            pmcid=info.get("pmcid"),
            doi=doi,
            candidates=tuple(ordered[:8]),
            consulted=tuple(dict.fromkeys(consulted)),
        )
