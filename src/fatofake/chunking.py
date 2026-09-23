"""Divide conteúdo científico em trechos rastreáveis por seção."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .pmc import ArticleContent, ContentSection


class ChunkingError(ValueError):
    """Configuração inválida ou conteúdo insuficiente para criar trechos."""


@dataclass(frozen=True)
class ChunkingConfig:
    """Parâmetros do recorte por quantidade aproximada de palavras."""

    max_words: int = 120
    overlap_words: int = 20

    def __post_init__(self) -> None:
        if self.max_words < 1:
            raise ChunkingError("max_words deve ser maior que zero.")
        if self.overlap_words < 0:
            raise ChunkingError("overlap_words não pode ser negativo.")
        if self.overlap_words >= self.max_words:
            raise ChunkingError("overlap_words deve ser menor que max_words.")


@dataclass(frozen=True)
class EvidenceChunk:
    """Trecho textual com proveniência suficiente para auditoria."""

    chunk_id: str
    pmid: str
    pmcid: str | None
    doi: str | None
    source_kind: str
    source_url: str
    section: str
    section_index: int
    chunk_index: int
    word_start: int
    word_end: int
    text: str


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _content_sections(content: ArticleContent) -> tuple[tuple[str, str], ...]:
    if content.full_text and content.sections:
        return tuple((section.title, section.text) for section in content.sections)
    if content.full_text:
        return (("Texto completo", content.full_text),)
    if content.abstract:
        return (("Resumo", content.abstract),)
    raise ChunkingError("O artigo não possui resumo nem texto completo para recorte.")


def _chunk_id(
    content: ArticleContent,
    source_kind: str,
    section_index: int,
    chunk_index: int,
    text: str,
) -> str:
    payload = "|".join(
        [content.pmid, source_kind, str(section_index), str(chunk_index), text]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{content.pmid}:{section_index}:{chunk_index}:{digest}"


def chunk_article_content(
    content: ArticleContent,
    config: ChunkingConfig | None = None,
) -> tuple[EvidenceChunk, ...]:
    """Recorta seções sem misturá-las e preserva intervalos de palavras."""

    active_config = config or ChunkingConfig()
    source_kind = "PMC_FULL_TEXT" if content.full_text else "PUBMED_ABSTRACT"
    source_url = content.pmc_url if content.full_text else content.pubmed_url
    if not source_url:
        raise ChunkingError("O conteúdo não possui URL de origem.")

    chunks: list[EvidenceChunk] = []
    for section_index, (section_title, section_text) in enumerate(
        _content_sections(content),
        start=1,
    ):
        normalized_text = _normalize_text(section_text)
        if not normalized_text:
            continue
        words = normalized_text.split(" ")
        start = 0
        chunk_index = 1
        while start < len(words):
            end = min(start + active_config.max_words, len(words))
            chunk_text = " ".join(words[start:end])
            chunks.append(
                EvidenceChunk(
                    chunk_id=_chunk_id(
                        content,
                        source_kind,
                        section_index,
                        chunk_index,
                        chunk_text,
                    ),
                    pmid=content.pmid,
                    pmcid=content.pmcid,
                    doi=content.doi,
                    source_kind=source_kind,
                    source_url=source_url,
                    section=section_title,
                    section_index=section_index,
                    chunk_index=chunk_index,
                    word_start=start,
                    word_end=end,
                    text=chunk_text,
                )
            )
            if end == len(words):
                break
            start = end - active_config.overlap_words
            chunk_index += 1

    if not chunks:
        raise ChunkingError("Nenhum trecho textual foi produzido.")
    return tuple(chunks)
