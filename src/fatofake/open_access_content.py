"""Recupera conteúdo aberto de editoras com limites e respeito a robots.txt."""

from __future__ import annotations

import re
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from .document_parsing import DocumentParsingError, LiteParseDocumentParser
from .pmc import ArticleContent, ContentSection
from .transport import default_ssl_context


class OpenAccessContentError(RuntimeError):
    """Uma página aberta não pôde ser recuperada com segurança."""


class Crawl4AiFetcher:
    """Renderiza páginas que dependem de JavaScript com navegador headless.

    Opcional: só é usado quando o pacote ``crawl4ai`` está instalado e o HTML
    simples não trouxe texto científico suficiente. O robots.txt continua sendo
    conferido antes, pelo cliente de acesso aberto.
    """

    def __init__(self, *, timeout: float = 45.0) -> None:
        import crawl4ai  # noqa: F401  - falha cedo se o pacote não existir

        self.timeout = timeout

    def fetch_markdown(self, url: str) -> str:
        import asyncio

        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        async def crawl() -> str:
            config = CrawlerRunConfig(
                check_robots_txt=True,
                page_timeout=int(self.timeout * 1000),
            )
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=config)
            if not getattr(result, "success", False):
                raise OpenAccessContentError(
                    f"O navegador headless não conseguiu abrir a página: {getattr(result, 'error_message', '')}"
                )
            markdown = getattr(result, "markdown", "") or ""
            return str(getattr(markdown, "raw_markdown", markdown))

        return asyncio.run(crawl())


def sections_from_markdown(markdown: str) -> tuple[ContentSection, ...]:
    sections: list[ContentSection] = []
    title = "Texto completo"
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if len(text) >= 100:
            sections.append(ContentSection(title=title, text=text))

    for line in markdown.splitlines():
        heading = re.match(r"^#{1,4}\s+(.+)$", line.strip())
        if heading:
            flush()
            title, buffer = heading.group(1).strip()[:120], []
        else:
            buffer.append(line)
    flush()
    return tuple(sections)


@dataclass(frozen=True)
class HttpDocument:
    final_url: str
    content_type: str
    body: bytes


DocumentFetcher = Callable[[str], HttpDocument]


class _ArticleHtmlParser(HTMLParser):
    _IGNORED = {"script", "style", "nav", "footer", "header", "form", "aside"}
    _BLOCKS = {"article", "section", "h1", "h2", "h3", "h4", "p", "li", "td", "th", "caption"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._current_heading = "Texto completo"
        self._buffer: list[str] = []
        self.sections: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._IGNORED:
            self._ignored_depth += 1
        if not self._ignored_depth and tag in self._BLOCKS and self._buffer:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if not self._ignored_depth and tag in self._BLOCKS:
            self._flush(is_heading=tag in {"h1", "h2", "h3", "h4"})

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self._buffer.append(data.strip())

    def _flush(self, *, is_heading: bool = False) -> None:
        text = " ".join(" ".join(self._buffer).split())
        self._buffer.clear()
        if not text:
            return
        if is_heading:
            self._current_heading = text[:200]
        elif len(text) >= 30:
            self.sections.append((self._current_heading, text))


class OpenAccessContentClient:
    """Converte PDF ou HTML de acesso aberto em ``ArticleContent``."""

    def __init__(
        self,
        document_parser: LiteParseDocumentParser,
        *,
        timeout: float = 25.0,
        max_bytes: int = 20 * 1024 * 1024,
        fetch_document: DocumentFetcher | None = None,
        ssl_context: ssl.SSLContext | None = None,
        browser_fetcher: Crawl4AiFetcher | None = None,
    ) -> None:
        self.document_parser = document_parser
        self.browser_fetcher = browser_fetcher
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._ssl_context = ssl_context or default_ssl_context()
        self._fetch_document = fetch_document or self._request_document

    def _check_robots(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise OpenAccessContentError("A fonte aberta precisa usar HTTPS.")
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        robots = RobotFileParser(robots_url)
        try:
            robots_request = Request(
                robots_url,
                headers={"User-Agent": "FatoOuFake/0.1"},
            )
            with urlopen(
                robots_request,
                timeout=self.timeout,
                context=self._ssl_context,
            ) as response:
                robots.parse(
                    response.read(512_000).decode("utf-8", errors="replace").splitlines()
                )
        except HTTPError as error:
            # RFC 9309: robots.txt ausente ou inacessível (4xx, exceto 429) permite o
            # acesso; erro do servidor (5xx) ou 429 deve ser tratado como bloqueio.
            if 400 <= error.code < 500 and error.code != 429:
                return
            raise OpenAccessContentError("Não foi possível conferir o robots.txt da fonte.")
        except (OSError, URLError, TimeoutError):
            raise OpenAccessContentError("Não foi possível conferir o robots.txt da fonte.")
        if not robots.can_fetch("FatoOuFake/0.1", url):
            raise OpenAccessContentError("A fonte não permite recuperação automatizada.")

    def _request_document(self, url: str) -> HttpDocument:
        self._check_robots(url)
        request = Request(url, headers={"User-Agent": "FatoOuFake/0.1"})
        try:
            with urlopen(request, timeout=self.timeout, context=self._ssl_context) as response:
                content_type = response.headers.get_content_type()
                body = response.read(self.max_bytes + 1)
                final_url = response.geturl()
        except (HTTPError, URLError, TimeoutError) as error:
            raise OpenAccessContentError(f"Falha ao abrir a fonte: {error}") from error
        if len(body) > self.max_bytes:
            raise OpenAccessContentError("O documento aberto excede o limite de tamanho.")
        return HttpDocument(final_url=final_url, content_type=content_type, body=body)

    def retrieve(
        self,
        *,
        pmid: str,
        pmcid: str | None = None,
        doi: str | None,
        pubmed_url: str,
        full_text_url: str,
        abstract: str | None,
    ) -> ArticleContent:
        document = self._fetch_document(full_text_url)
        if document.content_type == "application/pdf" or document.body.startswith(b"%PDF"):
            try:
                parsed = self.document_parser.parse_pdf(document.body)
            except DocumentParsingError as error:
                raise OpenAccessContentError(str(error)) from error
            sections = tuple(
                ContentSection(
                    title="Página do PDF",
                    text=page.text,
                    page_number=page.page_number,
                )
                for page in parsed.pages
            ) or (ContentSection("Texto completo", parsed.text),)
            return ArticleContent(
                pmid=pmid,
                pmcid=pmcid,
                doi=doi,
                abstract=abstract,
                full_text=parsed.text,
                sections=sections,
                access_level="FULL_TEXT" if pmcid else "OPEN_ACCESS_FULL_TEXT",
                pubmed_url=pubmed_url,
                pmc_url=document.final_url,
            )
        if document.content_type not in {"text/html", "application/xhtml+xml"}:
            raise OpenAccessContentError(
                f"Formato de conteúdo aberto não suportado: {document.content_type}."
            )
        parser = _ArticleHtmlParser()
        parser.feed(document.body.decode("utf-8", errors="replace"))
        grouped: dict[str, list[str]] = {}
        for title, text in parser.sections:
            grouped.setdefault(title, []).append(text)
        sections = tuple(
            ContentSection(title=title, text="\n\n".join(texts))
            for title, texts in grouped.items()
            if sum(len(text) for text in texts) >= 100
        )
        full_text = "\n\n".join(section.text for section in sections)
        full_text = re.sub(r"\n{3,}", "\n\n", full_text).strip()
        if len(full_text) < 500 and self.browser_fetcher is not None:
            # Páginas montadas por JavaScript chegam quase vazias no HTML bruto.
            markdown = self.browser_fetcher.fetch_markdown(document.final_url)
            sections = sections_from_markdown(markdown)
            full_text = "\n\n".join(section.text for section in sections).strip()
        if len(full_text) < 500:
            raise OpenAccessContentError(
                "A página aberta não forneceu texto científico suficiente."
            )
        return ArticleContent(
            pmid=pmid,
            pmcid=pmcid,
            doi=doi,
            abstract=abstract,
            full_text=full_text,
            sections=sections,
            access_level="FULL_TEXT" if pmcid else "OPEN_ACCESS_FULL_TEXT",
            pubmed_url=pubmed_url,
            pmc_url=document.final_url,
        )
