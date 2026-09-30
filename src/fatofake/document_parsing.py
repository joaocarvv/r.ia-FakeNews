"""Parsing local de documentos enviados, com proveniência básica por página."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class DocumentParsingError(RuntimeError):
    """O documento não pôde ser convertido em texto utilizável."""


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    page_count: int
    parser_name: str
    used_ocr: bool
    pages: tuple[ParsedPage, ...] = ()


ParserFactory = Callable[..., Any]


class LiteParseDocumentParser:
    """Adaptador opcional para parsing local de PDFs com LiteParse."""

    def __init__(
        self,
        *,
        parser_factory: ParserFactory | None = None,
        max_pages: int = 100,
        parse_timeout: float = 45.0,
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages deve ser maior ou igual a 1.")
        if parse_timeout <= 0:
            raise ValueError("parse_timeout deve ser positivo.")
        if parser_factory is None:
            try:
                from liteparse import LiteParse
            except ImportError as error:
                raise DocumentParsingError(
                    "LiteParse não está instalado. Execute: pip install liteparse"
                ) from error
            parser_factory = LiteParse
        self._factory = parser_factory
        self.max_pages = max_pages
        self.parse_timeout = parse_timeout

    def parse_pdf(self, content: bytes) -> ParsedDocument:
        if not content:
            raise DocumentParsingError("O PDF está vazio.")
        try:
            parser = self._factory(
                output_format="markdown",
                image_mode="off",
                extract_links=True,
                max_pages=self.max_pages,
                pool_size=1,
                parse_timeout=self.parse_timeout,
                quiet=True,
            )
            try:
                result = parser.parse(content)
            finally:
                close = getattr(parser, "close", None)
                if callable(close):
                    close()
        except Exception as error:
            raise DocumentParsingError(f"Falha ao interpretar o PDF: {error}") from error

        text = str(getattr(result, "text", "") or "").strip()
        if len(text) < 80:
            raise DocumentParsingError(
                "O LiteParse não encontrou texto suficiente no PDF. "
                "O arquivo pode ser uma digitalização ou exigir OCR mais avançado."
            )
        page_count = int(getattr(result, "total_pages", 0) or 0)
        pages = tuple(
            ParsedPage(
                page_number=int(getattr(page, "page_num", index) or index),
                text=str(getattr(page, "markdown", None) or getattr(page, "text", "") or "").strip(),
            )
            for index, page in enumerate(getattr(result, "pages", ()) or (), start=1)
            if str(getattr(page, "markdown", None) or getattr(page, "text", "") or "").strip()
        )
        return ParsedDocument(
            text=text,
            page_count=page_count,
            parser_name="liteparse",
            used_ocr=True,
            pages=pages,
        )
