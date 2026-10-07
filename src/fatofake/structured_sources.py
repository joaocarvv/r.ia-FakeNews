"""Consultas dinâmicas e auditáveis às fontes estruturadas do NCBI."""

from __future__ import annotations

import json
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .transport import default_ssl_context, wait_for_ncbi_slot


EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_GENE_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9-]{1,14})(?![A-Za-z0-9])")
_VARIANT_TOKEN = re.compile(r"\b(?:c|g|m|n|p|r)\.[A-Za-z0-9_>*+-]+", re.IGNORECASE)
_GENE_STOPWORDS = {
    "A", "AND", "DNA", "FAKE", "GENE", "HIV", "IA", "NCBI", "OR", "PMC",
    "PMID", "RNA", "THE", "UMA", "UM",
}


class StructuredSourceError(RuntimeError):
    """Falha ao consultar ou normalizar uma fonte estruturada."""


@dataclass(frozen=True)
class StructuredSearchResult:
    """Resposta normalizada para exibição e auditoria."""

    claim: str
    entities: Mapping[str, tuple[str, ...]]
    gene_records: tuple[Mapping[str, Any], ...]
    clinvar_records: tuple[Mapping[str, Any], ...]
    failures: tuple[Mapping[str, str], ...]
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "entities": {key: list(value) for key, value in self.entities.items()},
            "gene_records": [dict(record) for record in self.gene_records],
            "clinvar_records": [dict(record) for record in self.clinvar_records],
            "failures": [dict(failure) for failure in self.failures],
            "checked_at": self.checked_at,
        }


def extract_biomedical_entities(claim: str) -> dict[str, tuple[str, ...]]:
    """Extrai sinais conservadores; a ausência de sinal não refuta a alegação."""

    genes = tuple(
        dict.fromkeys(
            token
            for token in _GENE_TOKEN.findall(claim)
            if token not in _GENE_STOPWORDS
        )
    )
    variants = tuple(dict.fromkeys(_VARIANT_TOKEN.findall(claim)))
    return {"genes": genes, "variants": variants}


class NCBIStructuredSearch:
    """Consulta Gene e ClinVar sob demanda, com cache em memória por processo."""

    def __init__(
        self,
        *,
        email: str | None = None,
        api_key: str | None = None,
        timeout: float = 20.0,
        cache_ttl: float = 300.0,
        fetch_json: Callable[[str, Mapping[str, str]], Mapping[str, Any]] | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if timeout <= 0 or cache_ttl < 0:
            raise ValueError("timeout deve ser positivo e cache_ttl não pode ser negativo.")
        self.email = email
        self.api_key = api_key
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._fetch_json = fetch_json or self._request_json
        self._ssl_context = ssl_context or default_ssl_context()
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, Mapping[str, Any]]] = {}

    def _request_json(self, endpoint: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        request_params = {
            "db": params["db"],
            "retmode": "json",
            "tool": "fatofake",
            **dict(params),
        }
        if self.email:
            request_params["email"] = self.email
        if self.api_key:
            request_params["api_key"] = self.api_key
        request = Request(
            f"{EUTILS_URL}/{endpoint}?{urlencode(request_params)}",
            headers={"User-Agent": "FatoOuFake/0.1"},
        )
        for attempt in range(3):
            wait_for_ncbi_slot(bool(self.api_key))
            try:
                with urlopen(request, timeout=self.timeout, context=self._ssl_context) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise StructuredSourceError("O NCBI retornou JSON inesperado.")
                return payload
            except HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise StructuredSourceError(f"Falha ao consultar o NCBI: {error}") from error
            except (URLError, TimeoutError, json.JSONDecodeError) as error:
                if attempt == 2:
                    raise StructuredSourceError(f"Falha ao consultar o NCBI: {error}") from error
            time.sleep(1.0 * (2**attempt))
        raise StructuredSourceError("Falha inesperada ao consultar o NCBI.")

    def _fetch(self, endpoint: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        key = (endpoint, tuple(sorted(params.items())))
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self.cache_ttl:
            return cached[1]
        payload = self._fetch_json(endpoint, params)
        self._cache[key] = (time.monotonic(), payload)
        return payload

    def _search_ids(self, database: str, term: str, limit: int) -> tuple[int, tuple[str, ...]]:
        payload = self._fetch(
            "esearch.fcgi",
            {"db": database, "term": term, "retmax": str(limit), "sort": "relevance"},
        )
        try:
            result = payload["esearchresult"]
            return int(result["count"]), tuple(str(item) for item in result.get("idlist", ()))
        except (KeyError, TypeError, ValueError) as error:
            raise StructuredSourceError(f"Resposta ESearch inválida para {database}.") from error

    def _summaries(self, database: str, identifiers: tuple[str, ...]) -> tuple[Mapping[str, Any], ...]:
        if not identifiers:
            return ()
        payload = self._fetch(
            "esummary.fcgi",
            {"db": database, "id": ",".join(identifiers)},
        )
        try:
            result = payload["result"]
        except (KeyError, TypeError) as error:
            raise StructuredSourceError(f"Resposta ESummary inválida para {database}.") from error
        records = []
        for identifier in identifiers:
            document = result.get(identifier)
            if isinstance(document, dict):
                records.append(document)
        return tuple(records)

    def search(self, claim: str, *, limit: int = 5) -> StructuredSearchResult:
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError("A alegação deve ser um texto não vazio.")
        if not 1 <= limit <= 20:
            raise ValueError("limit deve estar entre 1 e 20.")
        entities = extract_biomedical_entities(claim)
        failures: list[Mapping[str, str]] = []
        gene_records: list[Mapping[str, Any]] = []
        clinvar_records: list[Mapping[str, Any]] = []

        for gene in entities["genes"]:
            try:
                _count, ids = self._search_ids("gene", f"{gene}[All Fields]", limit)
                gene_records.extend(self._summaries("gene", ids))
            except StructuredSourceError as error:
                failures.append({"source": "NCBI Gene", "query": gene, "reason": str(error)})

        search_terms = tuple(dict.fromkeys((*entities["variants"], *entities["genes"])))
        for term in search_terms:
            try:
                _count, ids = self._search_ids("clinvar", f"{term}[All Fields]", limit)
                clinvar_records.extend(self._summaries("clinvar", ids))
            except StructuredSourceError as error:
                failures.append({"source": "ClinVar", "query": term, "reason": str(error)})

        return StructuredSearchResult(
            claim=claim,
            entities=entities,
            gene_records=tuple(gene_records),
            clinvar_records=tuple(clinvar_records),
            failures=tuple(failures),
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
