"""Configuração e seleção de recuperação; nenhuma dependência científica de Qdrant."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import logging
import math
import threading
from time import perf_counter
from typing import Mapping, Protocol, Sequence

from .chunking import EvidenceChunk
from .hybrid_retrieval import HybridIndex, HybridRetrievedChunk
from .retrieval import Bm25Index, RetrievedChunk
from .semantic_retrieval import (
    DEFAULT_EMBEDDING_MODEL, EmbeddingEncoder, SemanticIndex, SemanticRetrievedChunk,
    ValidatedEmbeddingProvider,
)
from .structured_logging import log_event
from .vector_store import ChunkScope, ChunkSearchIndex, VectorStoreError

logger = logging.getLogger(__name__)


class ChunkIndexFactory(Protocol):
    backend: str
    model_name: str

    def index(self, chunks: Sequence[EvidenceChunk], *, scope: ChunkScope | None = None,
              minimum_score: float = 0.0) -> ChunkSearchIndex: ...


@dataclass(frozen=True)
class RetrievalSettings:
    backend: str = "memory"
    hybrid_enabled: bool = False
    top_k: int = 8
    minimum_score: float = 0.0
    failure_mode: str = "error"
    model_name: str = DEFAULT_EMBEDDING_MODEL
    revision: str = "v1"
    collection_prefix: str = "fatofake_chunks"
    timeout: float = 20.0
    medcpt_shadow_enabled: bool = False
    medcpt_shadow_top_n: int = 50

    def __post_init__(self) -> None:
        if self.medcpt_shadow_top_n < 1 or self.medcpt_shadow_top_n > 200:
            raise VectorStoreError("MEDCPT_SHADOW_TOP_N deve estar entre 1 e 200.")
        if self.backend not in {"memory", "qdrant"}:
            raise VectorStoreError("VECTOR_STORE_BACKEND deve ser memory ou qdrant.")
        if self.failure_mode not in {"error", "bm25"}:
            raise VectorStoreError("VECTOR_STORE_FAILURE_MODE deve ser error ou bm25.")
        if self.top_k < 1 or not math.isfinite(self.minimum_score) or not -1 <= self.minimum_score <= 1:
            raise VectorStoreError("VECTOR_TOP_K deve ser positivo e VECTOR_MIN_SCORE estar entre -1 e 1.")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise VectorStoreError("QDRANT_TIMEOUT deve ser positivo e finito.")
        if not self.model_name.strip() or not self.revision.strip():
            raise VectorStoreError("EMBEDDING_MODEL e EMBEDDING_REVISION não podem estar vazios.")

    @classmethod
    def from_mapping(cls, environment: Mapping[str, str]) -> RetrievalSettings:
        legacy = environment.get("VECTOR_BACKEND", "none").strip().lower()
        backend = environment.get("VECTOR_STORE_BACKEND", "memory" if legacy == "none" else legacy)
        hybrid = environment.get("HYBRID_RETRIEVAL_ENABLED", "false").strip().lower()
        if hybrid not in {"true", "false", "1", "0"}:
            raise VectorStoreError("HYBRID_RETRIEVAL_ENABLED deve ser true ou false.")
        shadow = environment.get("MEDCPT_SHADOW_ENABLED", "false").strip().lower()
        if shadow not in {"true", "false", "1", "0"}:
            raise VectorStoreError("MEDCPT_SHADOW_ENABLED deve ser true ou false.")
        try:
            return cls(
                medcpt_shadow_enabled=shadow in {"true", "1"},
                medcpt_shadow_top_n=int(environment.get("MEDCPT_SHADOW_TOP_N", "50")),
                backend=backend.strip().lower(), hybrid_enabled=hybrid in {"true", "1"},
                top_k=int(environment.get("VECTOR_TOP_K", "8")),
                minimum_score=float(environment.get("VECTOR_MIN_SCORE", "0")),
                failure_mode=environment.get("VECTOR_STORE_FAILURE_MODE", "error").strip().lower(),
                model_name=environment.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
                revision=environment.get("EMBEDDING_REVISION", "v1"),
                collection_prefix=environment.get("QDRANT_COLLECTION_PREFIX", "fatofake_chunks"),
                timeout=float(environment.get("QDRANT_TIMEOUT", "20")),
            )
        except (ValueError, TypeError) as error:
            if isinstance(error, VectorStoreError):
                raise
            raise VectorStoreError("Configuração vetorial inválida; confira VECTOR_TOP_K, VECTOR_MIN_SCORE e QDRANT_TIMEOUT.") from None


class MemoryChunkStore:
    """Adapter opcional para o SemanticIndex existente, sem serviço externo."""
    backend = "memory"
    collection = "memory"

    def __init__(self, *, model_name: str | None = None,
                 encoder: EmbeddingEncoder | None = None) -> None:
        self.model_name = model_name if model_name is not None else (encoder.name if encoder is not None else DEFAULT_EMBEDDING_MODEL)
        if encoder is not None and encoder.name != self.model_name:
            raise VectorStoreError("O encoder não corresponde a EMBEDDING_MODEL.")
        if not self.model_name.strip():
            raise VectorStoreError("EMBEDDING_MODEL não pode estar vazio.")
        self.encoder = ValidatedEmbeddingProvider(self.model_name, encoder=encoder)
        self._lock = threading.RLock()
        self._indices = OrderedDict()

    def index(self, chunks: Sequence[EvidenceChunk], *, scope: ChunkScope | None = None,
              minimum_score: float = 0.0) -> MemorySemanticIndex:
        if scope is not None and scope.collection is not None and scope.collection != self.collection:
            raise VectorStoreError("A collection solicitada está fora do escopo deste backend.")
        allowed = tuple(chunk for chunk in chunks if scope is None or scope.matches(chunk))
        if not allowed:
            raise VectorStoreError("Nenhum chunk autorizado para o índice em memória.")
        return MemorySemanticIndex(allowed, self, minimum_score)


class MemorySemanticIndex:
    def __init__(self, chunks: tuple[EvidenceChunk, ...], store: MemoryChunkStore,
                 minimum_score: float) -> None:
        self.chunks, self.store, self.minimum_score = chunks, store, minimum_score

    def search(self, query: str, *, top_k: int = 5) -> tuple[SemanticRetrievedChunk, ...]:
        with self.store._lock:
            # A identidade inclui texto e proveniência; limita o cache a oito corpus.
            index = self.store._indices.get(self.chunks)
            if index is None:
                index = SemanticIndex(self.chunks, self.store.encoder)
                self.store._indices[self.chunks] = index
                if len(self.store._indices) > 8:
                    self.store._indices.popitem(last=False)
            self.store._indices.move_to_end(self.chunks)
            return index.search(query, top_k=top_k, minimum_score=self.minimum_score)


RankedChunk = RetrievedChunk | SemanticRetrievedChunk | HybridRetrievedChunk


@dataclass(frozen=True)
class RankedRetrieval:
    results: tuple[RankedChunk, ...]
    backend: str
    notice: str | None = None


def retrieve_ranked_chunks(
    chunks: Sequence[EvidenceChunk], query: str, *, backend: ChunkIndexFactory | None = None,
    top_k: int = 8, minimum_score: float = 0.0, scope: ChunkScope | None = None,
    failure_mode: str = "error",
) -> RankedRetrieval:
    """Filtra ambos os rankings antes de RRF; BM25 sozinho mantém o comportamento antigo."""
    if failure_mode not in {"error", "bm25"}:
        raise VectorStoreError("Política de falha vetorial inválida.")
    if scope is not None and scope.collection is not None:
        if backend is None or getattr(backend, "collection", None) != scope.collection:
            raise VectorStoreError("A collection solicitada está fora do escopo deste backend.")
    started = perf_counter()
    allowed = tuple(chunk for chunk in chunks if scope is None or scope.matches(chunk))
    if not allowed:
        return RankedRetrieval((), "BM25" if backend is None else f"BM25+{backend.backend}")
    log_event(logger, logging.INFO, "Escopo aplicado à recuperação", event="retrieval.scope",
              backend="BM25" if backend is None else backend.backend,
              chunk_count=len(chunks), authorized_count=len(allowed),
              filtered_discard_count=len(chunks) - len(allowed))
    lexical = Bm25Index(allowed)
    if backend is None:
        return RankedRetrieval(tuple(lexical.search(query, top_k=top_k)), "BM25")
    try:
        semantic = backend.index(allowed, scope=scope, minimum_score=minimum_score)
        results = HybridIndex(lexical, semantic).search(query, top_k=top_k)
        provider = getattr(backend, "encoder", None)
        dimension = getattr(provider, "dimension", None)
        log_event(logger, logging.INFO, "Rankings fundidos por RRF", event="retrieval.ranked",
                  backend=backend.backend, collection=getattr(backend, "collection", None),
                  embedding_model=backend.model_name,
                  embedding_dimension=dimension if type(dimension) is int else None,
                  returned_count=len(results), top_k=top_k, minimum_score=minimum_score,
                  returned_chunk_ids=[item.chunk.chunk_id for item in results],
                  duration_ms=round((perf_counter() - started) * 1000, 2))
        return RankedRetrieval(results, f"BM25+{backend.backend}+RRF")
    except Exception as error:
        log_event(logger, logging.ERROR, "Falha na recuperação configurada", event="retrieval.failure",
                  backend=backend.backend, error_type=type(error).__name__, failure_mode=failure_mode)
        if failure_mode == "error":
            if isinstance(error, VectorStoreError):
                raise
            raise VectorStoreError(
                "Falha na recuperação vetorial configurada. Verifique o modelo e o backend. "
                "Nenhum backend alternativo foi usado."
            ) from None
        notice = "Recuperação vetorial indisponível; BM25 usado conforme VECTOR_STORE_FAILURE_MODE=bm25."
        log_event(logger, logging.WARNING, notice, event="retrieval.fallback", backend="BM25")
        return RankedRetrieval(tuple(lexical.search(query, top_k=top_k)), "BM25", notice)
