"""Combina rankings lexical e semântico sem misturar seus scores brutos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .chunking import EvidenceChunk
from .retrieval import RetrievalError


class RankedResult(Protocol):
    """Resultado mínimo necessário para participar da fusão."""

    rank: int
    chunk: EvidenceChunk


class RetrievalIndex(Protocol):
    """Contrato comum implementado pelos índices BM25 e semântico."""

    chunks: tuple[EvidenceChunk, ...]

    def search(self, query: str, *, top_k: int) -> Sequence[RankedResult]: ...


@dataclass(frozen=True)
class HybridConfig:
    """Pesos e profundidade usados na Reciprocal Rank Fusion."""

    lexical_weight: float = 1.0
    semantic_weight: float = 1.0
    rrf_k: int = 60
    candidate_multiplier: int = 4

    def __post_init__(self) -> None:
        if self.lexical_weight < 0 or self.semantic_weight < 0:
            raise RetrievalError("Os pesos da fusão não podem ser negativos.")
        if self.lexical_weight == 0 and self.semantic_weight == 0:
            raise RetrievalError("Ao menos um peso da fusão deve ser maior que zero.")
        if self.rrf_k < 1:
            raise RetrievalError("rrf_k deve ser maior que zero.")
        if self.candidate_multiplier < 1:
            raise RetrievalError("candidate_multiplier deve ser maior que zero.")


@dataclass(frozen=True)
class HybridRetrievedChunk:
    """Trecho híbrido com posições e contribuições auditáveis."""

    rank: int
    score: float
    lexical_rank: int | None
    semantic_rank: int | None
    lexical_contribution: float
    semantic_contribution: float
    chunk: EvidenceChunk


class HybridIndex:
    """Funde BM25 e embeddings com Weighted Reciprocal Rank Fusion."""

    def __init__(
        self,
        lexical_index: RetrievalIndex,
        semantic_index: RetrievalIndex,
        config: HybridConfig | None = None,
    ) -> None:
        self.lexical_index = lexical_index
        self.semantic_index = semantic_index
        self.config = config or HybridConfig()

        lexical_ids = [chunk.chunk_id for chunk in lexical_index.chunks]
        semantic_ids = [chunk.chunk_id for chunk in semantic_index.chunks]
        if len(lexical_ids) != len(set(lexical_ids)):
            raise RetrievalError("O índice lexical possui identificadores duplicados.")
        if len(semantic_ids) != len(set(semantic_ids)):
            raise RetrievalError("O índice semântico possui identificadores duplicados.")
        if set(lexical_ids) != set(semantic_ids):
            raise RetrievalError("Os índices devem representar a mesma coleção de trechos.")

        self.chunks = tuple(lexical_index.chunks)
        self._chunks_by_id = {chunk.chunk_id: chunk for chunk in self.chunks}

    def search(self, query: str, *, top_k: int = 5) -> tuple[HybridRetrievedChunk, ...]:
        """Recupera candidatos dos dois métodos e funde suas posições."""

        if not query.strip():
            raise RetrievalError("A consulta híbrida não pode estar vazia.")
        if top_k < 1:
            raise RetrievalError("top_k deve ser maior que zero.")

        candidate_limit = min(
            len(self.chunks),
            top_k * self.config.candidate_multiplier,
        )
        lexical_results = self.lexical_index.search(query, top_k=candidate_limit)
        semantic_results = self.semantic_index.search(query, top_k=candidate_limit)

        lexical_ranks = {
            result.chunk.chunk_id: result.rank for result in lexical_results
        }
        semantic_ranks = {
            result.chunk.chunk_id: result.rank for result in semantic_results
        }
        candidate_ids = set(lexical_ranks) | set(semantic_ranks)

        scored: list[
            tuple[float, str, int | None, int | None, float, float]
        ] = []
        for chunk_id in candidate_ids:
            lexical_rank = lexical_ranks.get(chunk_id)
            semantic_rank = semantic_ranks.get(chunk_id)
            lexical_contribution = (
                self.config.lexical_weight / (self.config.rrf_k + lexical_rank)
                if lexical_rank is not None
                else 0.0
            )
            semantic_contribution = (
                self.config.semantic_weight / (self.config.rrf_k + semantic_rank)
                if semantic_rank is not None
                else 0.0
            )
            scored.append(
                (
                    lexical_contribution + semantic_contribution,
                    chunk_id,
                    lexical_rank,
                    semantic_rank,
                    lexical_contribution,
                    semantic_contribution,
                )
            )

        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            HybridRetrievedChunk(
                rank=rank,
                score=score,
                lexical_rank=lexical_rank,
                semantic_rank=semantic_rank,
                lexical_contribution=lexical_contribution,
                semantic_contribution=semantic_contribution,
                chunk=self._chunks_by_id[chunk_id],
            )
            for rank, (
                score,
                chunk_id,
                lexical_rank,
                semantic_rank,
                lexical_contribution,
                semantic_contribution,
            ) in enumerate(scored[:top_k], start=1)
        )
