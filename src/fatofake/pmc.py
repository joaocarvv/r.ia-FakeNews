"""Recupera resumo no PubMed e texto completo disponível no PubMed Central."""

from __future__ import annotations

import json
import ssl
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .pubmed import Publication
from .transport import default_ssl_context


PMC_ID_CONVERTER_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
JsonFetcher = Callable[[str, Mapping[str, str]], Mapping[str, Any]]
XmlFetcher = Callable[[str, Mapping[str, str]], bytes]


class ContentRetrievalError(RuntimeError):
    """Falha de comunicação ou de formato ao recuperar conteúdo científico."""


@dataclass(frozen=True)
class ContentSection:
    """Seção principal extraída do XML do PMC."""

    title: str
    text: str


@dataclass(frozen=True)
class ArticleContent:
    """Conteúdo textual recuperado com seu nível de disponibilidade."""

    pmid: str
    pmcid: str | None
    doi: str | None
    abstract: str | None
    full_text: str | None
    sections: tuple[ContentSection, ...]
    access_level: str
    pubmed_url: str
    pmc_url: str | None


def _element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


class PmcClient:
    """Cliente limitado ao ID Converter e ao EFetch do NCBI."""

    def __init__(
        self,
        *,
        email: str | None = None,
        api_key: str | None = None,
        timeout: float = 20.0,
        fetch_json: JsonFetcher | None = None,
        fetch_xml: XmlFetcher | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.email = email
        self.api_key = api_key
        self.timeout = timeout
        self._last_request_at: float | None = None
        self._ssl_context = ssl_context or default_ssl_context()
        self._fetch_json = fetch_json or self._request_json
        self._fetch_xml = fetch_xml or self._request_xml

    def _wait_for_rate_limit(self) -> None:
        minimum_interval = 0.11 if self.api_key else 0.34
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)

    def _request_bytes(self, url: str, params: Mapping[str, str]) -> bytes:
        self._wait_for_rate_limit()
        request_url = f"{url}?{urlencode(params)}"
        request = Request(request_url, headers={"User-Agent": "FatoOuFake/0.1"})
        try:
            with urlopen(
                request,
                timeout=self.timeout,
                context=self._ssl_context,
            ) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            raise ContentRetrievalError(f"Falha ao consultar o NCBI: {error}") from error
        finally:
            self._last_request_at = time.monotonic()

    def _request_json(self, url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        try:
            payload = json.loads(self._request_bytes(url, params))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ContentRetrievalError("O NCBI retornou JSON inválido.") from error
        if not isinstance(payload, dict):
            raise ContentRetrievalError("O NCBI retornou uma resposta JSON inesperada.")
        return payload

    def _request_xml(self, url: str, params: Mapping[str, str]) -> bytes:
        return self._request_bytes(url, params)

    def _identification_params(self, *, include_api_key: bool = True) -> dict[str, str]:
        params = {"tool": "fatofake"}
        if self.email:
            params["email"] = self.email
        if include_api_key and self.api_key:
            params["api_key"] = self.api_key
        return params

    def resolve_pmcid(self, pmid: str) -> str | None:
        params = self._identification_params(include_api_key=False)
        params.update({"ids": pmid, "format": "json", "idtype": "pmid"})
        payload = self._fetch_json(PMC_ID_CONVERTER_URL, params)
        try:
            records = payload["records"]
        except (KeyError, TypeError) as error:
            raise ContentRetrievalError("Resposta inválida do PMC ID Converter.") from error
        if not records:
            return None
        pmcid = records[0].get("pmcid")
        return str(pmcid).strip() if pmcid else None

    def fetch_pubmed_abstract(self, pmid: str) -> str | None:
        params = self._identification_params()
        params.update({"db": "pubmed", "id": pmid, "retmode": "xml"})
        raw_xml = self._fetch_xml(NCBI_EFETCH_URL, params)
        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as error:
            raise ContentRetrievalError("O PubMed retornou XML inválido.") from error

        parts: list[str] = []
        for abstract_part in root.findall(".//Abstract/AbstractText"):
            text = _element_text(abstract_part)
            if not text:
                continue
            label = abstract_part.attrib.get("Label")
            parts.append(f"{label}: {text}" if label else text)
        return "\n\n".join(parts) or None

    def fetch_pmc_full_text(
        self,
        pmcid: str,
    ) -> tuple[str | None, tuple[ContentSection, ...]]:
        params = self._identification_params()
        params.update({"db": "pmc", "id": pmcid.removeprefix("PMC"), "retmode": "xml"})
        raw_xml = self._fetch_xml(NCBI_EFETCH_URL, params)
        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as error:
            raise ContentRetrievalError("O PMC retornou XML inválido.") from error

        body = root.find(".//body")
        full_text = _element_text(body) or None
        sections: list[ContentSection] = []
        if body is not None:
            for index, section in enumerate(body.findall("./sec"), start=1):
                title = _element_text(section.find("./title")) or f"Seção {index}"
                paragraphs = [
                    _element_text(paragraph) for paragraph in section.findall(".//p")
                ]
                section_text = "\n\n".join(text for text in paragraphs if text)
                if section_text:
                    sections.append(ContentSection(title=title, text=section_text))
        return full_text, tuple(sections)


def retrieve_article_content(publication: Publication, client: PmcClient) -> ArticleContent:
    """Recupera resumo e enriquece com texto completo quando o artigo está no PMC."""

    abstract = client.fetch_pubmed_abstract(publication.pmid)
    pmcid = client.resolve_pmcid(publication.pmid)
    full_text: str | None = None
    sections: tuple[ContentSection, ...] = ()
    if pmcid:
        full_text, sections = client.fetch_pmc_full_text(pmcid)

    return ArticleContent(
        pmid=publication.pmid,
        pmcid=pmcid,
        doi=publication.doi,
        abstract=abstract,
        full_text=full_text,
        sections=sections,
        access_level="FULL_TEXT" if full_text else "ABSTRACT_ONLY",
        pubmed_url=publication.url,
        pmc_url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else None,
    )
