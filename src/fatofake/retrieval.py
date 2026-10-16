"""Recupera trechos científicos relevantes com uma linha de base BM25."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from .chunking import EvidenceChunk


class RetrievalError(ValueError):
    """Consulta, configuração ou coleção inválida para recuperação."""


@dataclass(frozen=True)
class Bm25Config:
    """Parâmetros do BM25 usados para controlar frequência e tamanho."""

    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        if self.k1 <= 0:
            raise RetrievalError("k1 deve ser maior que zero.")
        if not 0 <= self.b <= 1:
            raise RetrievalError("b deve estar entre zero e um.")


@dataclass(frozen=True)
class RetrievedChunk:
    """Trecho recuperado com posição, pontuação e termos correspondentes."""

    rank: int
    score: float
    matched_terms: tuple[str, ...]
    chunk: EvidenceChunk


def tokenize(text: str) -> tuple[str, ...]:
    """Normaliza caixa e acentos antes de extrair termos alfanuméricos."""

    normalized = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return tuple(re.findall(r"[^\W_]+", without_accents, flags=re.UNICODE))


class Bm25Index:
    """Índice em memória para ordenar ``EvidenceChunk`` com Okapi BM25."""

    def __init__(
        self,
        chunks: tuple[EvidenceChunk, ...] | list[EvidenceChunk],
        config: Bm25Config | None = None,
    ) -> None:
        if not chunks:
            raise RetrievalError("Ao menos um trecho é necessário para criar o índice.")

        self.chunks = tuple(chunks)
        self.config = config or Bm25Config()
        self._tokens = tuple(tokenize(chunk.text) for chunk in self.chunks)
        self._term_frequencies = tuple(Counter(tokens) for tokens in self._tokens)
        self._document_lengths = tuple(len(tokens) for tokens in self._tokens)
        self._average_length = sum(self._document_lengths) / len(self.chunks)

        document_frequencies: Counter[str] = Counter()
        for tokens in self._tokens:
            document_frequencies.update(set(tokens))
        self._document_frequencies = document_frequencies

    def _idf(self, term: str) -> float:
        document_count = len(self.chunks)
        frequency = self._document_frequencies.get(term, 0)
        return math.log(1 + (document_count - frequency + 0.5) / (frequency + 0.5))

    def _score(self, document_index: int, query_terms: tuple[str, ...]) -> float:
        frequencies = self._term_frequencies[document_index]
        document_length = self._document_lengths[document_index]
        score = 0.0
        for term in query_terms:
            term_frequency = frequencies.get(term, 0)
            if not term_frequency:
                continue
            length_factor = 1 - self.config.b + self.config.b * (
                document_length / self._average_length
            )
            score += self._idf(term) * (
                term_frequency * (self.config.k1 + 1)
            ) / (term_frequency + self.config.k1 * length_factor)
        return score

    def search(self, query: str, *, top_k: int = 5) -> tuple[RetrievedChunk, ...]:
        """Retorna somente correspondências positivas, em ordem determinística."""

        if top_k < 1:
            raise RetrievalError("top_k deve ser maior que zero.")
        query_terms = tuple(dict.fromkeys(tokenize(query)))
        if not query_terms:
            raise RetrievalError("A consulta deve conter ao menos um termo válido.")

        scored: list[tuple[float, EvidenceChunk, tuple[str, ...]]] = []
        for document_index, chunk in enumerate(self.chunks):
            score = self._score(document_index, query_terms)
            if score <= 0:
                continue
            frequencies = self._term_frequencies[document_index]
            matched_terms = tuple(term for term in query_terms if term in frequencies)
            scored.append((score, chunk, matched_terms))

        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return tuple(
            RetrievedChunk(
                rank=rank,
                score=score,
                matched_terms=matched_terms,
                chunk=chunk,
            )
            for rank, (score, chunk, matched_terms) in enumerate(
                scored[:top_k],
                start=1,
            )
        )
