"""Extrai afirmações rastreáveis dos trechos recuperados para comparação posterior."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Sequence

from .hybrid_retrieval import HybridRetrievedChunk
from .retrieval import RetrievalError, tokenize


_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "be",
    "by",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "for",
    "in",
    "is",
    "o",
    "of",
    "on",
    "or",
    "os",
    "pode",
    "the",
    "to",
    "um",
    "uma",
}

_NON_EVIDENCE_PATTERNS = (
    "aim of this",
    "dose-response relationship of",
    "dose–response relationship of",
    "forest plot for",
    "if the association is further proved",
    "objective of this",
    "it was hypothesised",
    "it was hypothesized",
    "further research",
)

_SECTION_BONUSES = {
    "conclusion": 0.15,
    "conclusions": 0.15,
    "result": 0.12,
    "results": 0.12,
    "discussion": 0.08,
}


@dataclass(frozen=True)
class ExtractionConfig:
    """Limites para produzir uma seleção curta e auditável."""

    max_statements: int = 6
    max_per_chunk: int = 2
    min_words: int = 8
    max_words: int = 80

    def __post_init__(self) -> None:
        if self.max_statements < 1:
            raise RetrievalError("max_statements deve ser maior que zero.")
        if self.max_per_chunk < 1:
            raise RetrievalError("max_per_chunk deve ser maior que zero.")
        if self.min_words < 1:
            raise RetrievalError("min_words deve ser maior que zero.")
        if self.max_words < self.min_words:
            raise RetrievalError("max_words deve ser maior ou igual a min_words.")


@dataclass(frozen=True)
class EvidenceStatement:
    """Afirmação extraída com sua origem científica completa."""

    statement_id: str
    text: str
    extraction_score: float
    matched_claim_terms: tuple[str, ...]
    hybrid_rank: int
    sentence_index: int
    chunk_id: str
    pmid: str
    pmcid: str | None
    doi: str | None
    section: str
    source_url: str


@dataclass(frozen=True)
class ClaimEvidencePair:
    """Entrada preparada para a futura classificação de relação textual."""

    pair_id: str
    claim: str
    evidence: EvidenceStatement
    assessment_status: str = "PENDING"


def _split_sentences(text: str) -> tuple[str, ...]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ()
    normalized = re.sub(
        r"(?<=[A-Za-z)])([.!?])\d+(?:[–-]\d+)?(?:\s+\d+(?:[–-]\d+)?)*(?=\s+[A-Z])",
        r"\1",
        normalized,
    )
    return tuple(
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", normalized)
        if sentence.strip()
    )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def extract_evidence_statements(
    claim: str,
    ranked_chunks: Sequence[HybridRetrievedChunk],
    config: ExtractionConfig | None = None,
) -> tuple[EvidenceStatement, ...]:
    """Seleciona sentenças relacionadas sem inferir apoio ou contradição."""

    if not claim.strip():
        raise RetrievalError("A alegação não pode estar vazia.")
    if not ranked_chunks:
        raise RetrievalError("Ao menos um trecho ranqueado é necessário.")
    active_config = config or ExtractionConfig()
    claim_terms = tuple(
        dict.fromkeys(
            term for term in tokenize(claim) if term not in _STOPWORDS and len(term) > 1
        )
    )
    if not claim_terms:
        raise RetrievalError("A alegação não contém termos úteis para extração.")

    candidates: list[EvidenceStatement] = []
    for ranked_chunk in ranked_chunks:
        chunk = ranked_chunk.chunk
        for sentence_index, sentence in enumerate(
            _split_sentences(chunk.text),
            start=1,
        ):
            sentence_terms = set(tokenize(sentence))
            if not active_config.min_words <= len(sentence_terms) <= active_config.max_words:
                continue
            normalized_sentence = sentence.casefold()
            if any(pattern in normalized_sentence for pattern in _NON_EVIDENCE_PATTERNS):
                continue
            matched_terms = tuple(term for term in claim_terms if term in sentence_terms)
            if not matched_terms:
                continue
            coverage = len(matched_terms) / len(claim_terms)
            rank_bonus = 1 / (10 + ranked_chunk.rank)
            section_bonus = _SECTION_BONUSES.get(chunk.section.casefold(), 0.0)
            candidates.append(
                EvidenceStatement(
                    statement_id=_stable_id(
                        "statement",
                        chunk.chunk_id,
                        str(sentence_index),
                        sentence,
                    ),
                    text=sentence,
                    extraction_score=coverage + rank_bonus + section_bonus,
                    matched_claim_terms=matched_terms,
                    hybrid_rank=ranked_chunk.rank,
                    sentence_index=sentence_index,
                    chunk_id=chunk.chunk_id,
                    pmid=chunk.pmid,
                    pmcid=chunk.pmcid,
                    doi=chunk.doi,
                    section=chunk.section,
                    source_url=chunk.source_url,
                )
            )

    candidates.sort(
        key=lambda item: (
            -item.extraction_score,
            item.hybrid_rank,
            item.sentence_index,
            item.statement_id,
        )
    )
    selected: list[EvidenceStatement] = []
    selected_texts: set[str] = set()
    per_chunk: dict[str, int] = {}
    for candidate in candidates:
        normalized_text = " ".join(tokenize(candidate.text))
        if normalized_text in selected_texts:
            continue
        if per_chunk.get(candidate.chunk_id, 0) >= active_config.max_per_chunk:
            continue
        selected.append(candidate)
        selected_texts.add(normalized_text)
        per_chunk[candidate.chunk_id] = per_chunk.get(candidate.chunk_id, 0) + 1
        if len(selected) == active_config.max_statements:
            break

    if not selected:
        raise RetrievalError("Nenhuma afirmação relacionada foi extraída dos trechos.")
    return tuple(selected)


def build_claim_evidence_pairs(
    claim: str,
    statements: Sequence[EvidenceStatement],
) -> tuple[ClaimEvidencePair, ...]:
    """Cria pares pendentes sem atribuir uma relação ainda não avaliada."""

    if not claim.strip():
        raise RetrievalError("A alegação não pode estar vazia.")
    if not statements:
        raise RetrievalError("Ao menos uma afirmação científica é necessária.")
    return tuple(
        ClaimEvidencePair(
            pair_id=_stable_id("pair", claim.strip(), statement.statement_id),
            claim=claim.strip(),
            evidence=statement,
        )
        for statement in statements
    )
