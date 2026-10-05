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
from .transport import default_ssl_context, wait_for_ncbi_slot


PMC_ID_CONVERTER_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PMC_BIOC_URL = (
    "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/"
    "BioC_xml/{pmcid}/unicode"
)
JsonFetcher = Callable[[str, Mapping[str, str]], Mapping[str, Any]]
XmlFetcher = Callable[[str, Mapping[str, str]], bytes]
TRANSIENT_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})


class ContentRetrievalError(RuntimeError):
    """Falha de comunicação ou de formato ao recuperar conteúdo científico."""


@dataclass(frozen=True)
class ContentSection:
    """Seção principal extraída do XML do PMC."""

    title: str
    text: str
    page_number: int | None = None


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


def _declarations_text(root: ET.Element) -> str:
    """Financiamento, agradecimentos e conflitos de interesse do JATS."""

    blocks: list[str] = []
    for path in (
        ".//funding-group",
        ".//back/ack",
        ".//author-notes/fn",
        ".//back/fn-group/fn",
        ".//back/notes",
    ):
        for element in root.findall(path):
            text = _element_text(element)
            if text and len(text) >= 20:
                blocks.append(text)
    return "\n\n".join(dict.fromkeys(blocks))[:6000]


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
        max_attempts: int = 3,
        retry_delay: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts deve ser maior ou igual a 1.")
        if retry_delay < 0:
            raise ValueError("retry_delay não pode ser negativo.")
        self.email = email
        self.api_key = api_key
        self.timeout = timeout
        self._last_request_at: float | None = None
        self._ssl_context = ssl_context or default_ssl_context()
        self._fetch_json = fetch_json or self._request_json
        self._fetch_xml = fetch_xml or self._request_xml
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self._sleep = sleep

    def _wait_for_rate_limit(self) -> None:
        wait_for_ncbi_slot(bool(self.api_key))

    def _request_bytes(self, url: str, params: Mapping[str, str]) -> bytes:
        request_url = f"{url}?{urlencode(params)}"
        request = Request(request_url, headers={"User-Agent": "FatoOuFake/0.1"})
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            self._wait_for_rate_limit()
            try:
                with urlopen(
                    request,
                    timeout=self.timeout,
                    context=self._ssl_context,
                ) as response:
                    return response.read()
            except HTTPError as error:
                last_error = error
                if error.code not in TRANSIENT_HTTP_STATUS or attempt + 1 == self.max_attempts:
                    break
            except (URLError, TimeoutError) as error:
                last_error = error
                if attempt + 1 == self.max_attempts:
                    break
            finally:
                self._last_request_at = time.monotonic()
            self._sleep(min(30.0, self.retry_delay * (2**attempt)))
        raise ContentRetrievalError(f"Falha ao consultar o NCBI: {last_error}") from last_error

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
                blocks: list[str] = []
                for child in section.iter():
                    if child.tag == "p":
                        text = _element_text(child)
                        if text:
                            blocks.append(text)
                    elif child.tag == "table-wrap":
                        label = _element_text(child.find("./label")) or "Tabela"
                        caption = _element_text(child.find("./caption"))
                        table = _element_text(child.find(".//table"))
                        rendered = " — ".join(part for part in (label, caption, table) if part)
                        if rendered:
                            blocks.append(rendered)
                section_text = "\n\n".join(dict.fromkeys(blocks))
                if section_text:
                    sections.append(ContentSection(title=title, text=section_text))
        declarations = _declarations_text(root)
        if declarations:
            sections.append(ContentSection(title="Financiamento e declarações", text=declarations))
            full_text = f"{full_text}\n\n{declarations}" if full_text else full_text
        return full_text, tuple(sections)

    def fetch_pmc_bioc_full_text(
        self,
        pmcid: str,
    ) -> tuple[str | None, tuple[ContentSection, ...]]:
        """Recupera o subconjunto reutilizável do PMC pela API oficial BioC."""

        raw_xml = self._fetch_xml(PMC_BIOC_URL.format(pmcid=pmcid), {})
        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as error:
            raise ContentRetrievalError("A API BioC do PMC retornou XML inválido.") from error

        grouped: dict[str, list[str]] = {}
        for passage in root.findall(".//passage"):
            text = _element_text(passage.find("./text"))
            if not text:
                continue
            infons = {
                str(infon.attrib.get("key") or ""): _element_text(infon)
                for infon in passage.findall("./infon")
            }
            raw_section = infons.get("section_type") or infons.get("type") or "Texto completo"
            section = raw_section.replace("_", " ").strip().title()
            grouped.setdefault(section, []).append(text)

        sections = tuple(
            ContentSection(title=title, text="\n\n".join(dict.fromkeys(parts)))
            for title, parts in grouped.items()
            if parts
        )
        full_text = "\n\n".join(section.text for section in sections) or None
        return full_text, sections


def retrieve_article_content(publication: Publication, client: PmcClient) -> ArticleContent:
    """Recupera resumo e enriquece com texto completo quando o artigo está no PMC."""

    abstract = client.fetch_pubmed_abstract(publication.pmid)
    pmcid = client.resolve_pmcid(publication.pmid)
    full_text: str | None = None
    sections: tuple[ContentSection, ...] = ()
    if pmcid:
        full_text, sections = client.fetch_pmc_full_text(pmcid)
        if not full_text and hasattr(client, "fetch_pmc_bioc_full_text"):
            try:
                full_text, sections = client.fetch_pmc_bioc_full_text(pmcid)
            except ContentRetrievalError:
                # Nem todo registro do PMC pertence ao subconjunto reutilizável.
                # Nesse caso, outros caminhos abertos ainda podem ser tentados.
                full_text, sections = None, ()

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
