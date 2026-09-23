"""Recupera trechos por similaridade semântica entre embeddings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Sequence

from .chunking import EvidenceChunk
from .retrieval import RetrievalError


DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)


class EmbeddingEncoder(Protocol):
    """Contrato mínimo para codificadores locais ou remotos de texto."""

    @property
    def name(self) -> str:
        """Identificador auditável do modelo usado."""

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Transforma textos em vetores numéricos de mesma dimensão."""


class SentenceTransformerEncoder:
    """Adaptador para um modelo multilíngue da biblioteca sentence-transformers."""

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RetrievalError(
                "sentence-transformers não está instalado; instale requirements.txt."
            ) from error

        self._name = model_name
        try:
            self._model = SentenceTransformer(model_name)
        except Exception as error:
            raise RetrievalError(
                f"Não foi possível carregar o modelo de embeddings {model_name!r}."
            ) from error

    @property
    def name(self) -> str:
        return self._name

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()


@dataclass(frozen=True)
class SemanticRetrievedChunk:
    """Trecho recuperado com posição e similaridade de cosseno."""

    rank: int
    score: float
    chunk: EvidenceChunk


def _validated_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
) -> tuple[tuple[float, ...], ...]:
    normalized_vectors = tuple(tuple(float(value) for value in vector) for vector in vectors)
    if len(normalized_vectors) != expected_count:
        raise RetrievalError("O codificador retornou uma quantidade inesperada de vetores.")
    if not normalized_vectors or not normalized_vectors[0]:
        raise RetrievalError("O codificador retornou vetores vazios.")

    dimension = len(normalized_vectors[0])
    for vector in normalized_vectors:
        if len(vector) != dimension:
            raise RetrievalError("Os embeddings possuem dimensões diferentes.")
        if not all(math.isfinite(value) for value in vector):
            raise RetrievalError("Os embeddings possuem valores não finitos.")
        if math.sqrt(sum(value * value for value in vector)) == 0:
            raise RetrievalError("O codificador retornou um vetor nulo.")
    return normalized_vectors


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)


class SemanticIndex:
    """Índice vetorial em memória com ordenação determinística."""

    def __init__(
        self,
        chunks: tuple[EvidenceChunk, ...] | list[EvidenceChunk],
        encoder: EmbeddingEncoder,
    ) -> None:
        if not chunks:
            raise RetrievalError("Ao menos um trecho é necessário para criar o índice.")
        self.chunks = tuple(chunks)
        self.encoder = encoder
        self.model_name = encoder.name
        self._vectors = _validated_vectors(
            encoder.encode([chunk.text for chunk in self.chunks]),
            expected_count=len(self.chunks),
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        minimum_score: float = 0.0,
    ) -> tuple[SemanticRetrievedChunk, ...]:
        """Ordena trechos por cosseno e mantém somente scores acima do limite."""

        if not query.strip():
            raise RetrievalError("A consulta semântica não pode estar vazia.")
        if top_k < 1:
            raise RetrievalError("top_k deve ser maior que zero.")
        if not -1 <= minimum_score <= 1:
            raise RetrievalError("minimum_score deve estar entre -1 e 1.")

        query_vector = _validated_vectors(
            self.encoder.encode([query]),
            expected_count=1,
        )[0]
        if len(query_vector) != len(self._vectors[0]):
            raise RetrievalError("A consulta e os trechos possuem dimensões diferentes.")

        scored = [
            (_cosine_similarity(query_vector, vector), chunk)
            for vector, chunk in zip(self._vectors, self.chunks)
        ]
        scored = [item for item in scored if item[0] >= minimum_score]
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return tuple(
            SemanticRetrievedChunk(rank=rank, score=score, chunk=chunk)
            for rank, (score, chunk) in enumerate(scored[:top_k], start=1)
        )
