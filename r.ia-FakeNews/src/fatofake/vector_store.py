"""Contratos científicos independentes do cliente de armazenamento vetorial."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping, Protocol, Sequence

from .chunking import EvidenceChunk
from .retrieval import RetrievalError
from .semantic_retrieval import SemanticRetrievedChunk

PAYLOAD_VERSION = 1


class VectorStoreError(RetrievalError):
    """Falha explícita de configuração, persistência ou recuperação."""


@dataclass(frozen=True)
class ChunkScope:
    """Listas vazias negam acesso; None não acrescenta restrição nesse campo."""

    pmids: tuple[str, ...] | None = None
    pmcids: tuple[str, ...] | None = None
    dois: tuple[str, ...] | None = None
    source_kinds: tuple[str, ...] | None = None
    content_scopes: tuple[str, ...] | None = None
    chunk_ids: tuple[str, ...] | None = None
    collection: str | None = None

    def matches(self, chunk: EvidenceChunk) -> bool:
        return all(allowed is None or value in allowed for allowed, value in (
            (self.pmids, chunk.pmid), (self.pmcids, chunk.pmcid), (self.dois, chunk.doi),
            (self.source_kinds, chunk.source_kind), (self.content_scopes, chunk.content_scope),
            (self.chunk_ids, chunk.chunk_id),
        ))

    @property
    def restricted(self) -> bool:
        return any(value is not None for value in (self.pmids, self.pmcids, self.dois,
                   self.source_kinds, self.content_scopes, self.chunk_ids))


@dataclass(frozen=True)
class CollectionMetadata:
    collection: str
    embedding_model: str
    embedding_revision: str
    embedding_dimension: int
    distance: str
    point_count: int


class ChunkSearchIndex(Protocol):
    chunks: tuple[EvidenceChunk, ...]

    def search(self, query: str, *, top_k: int = 5) -> Sequence[SemanticRetrievedChunk]: ...


class PersistentVectorStore(Protocol):
    model_name: str
    collection: str

    def ensure_collection(self, dimension: int) -> CollectionMetadata: ...
    def metadata(self) -> CollectionMetadata: ...
    def upsert(self, chunks: Sequence[EvidenceChunk]) -> int: ...
    def search(self, query: str, *, scope: ChunkScope, top_k: int = 5,
               minimum_score: float = 0.0) -> tuple[SemanticRetrievedChunk, ...]: ...
    def index(self, chunks: Sequence[EvidenceChunk], *, scope: ChunkScope | None = None,
              minimum_score: float = 0.0) -> ChunkSearchIndex: ...
    def invalidate(self, scope: ChunkScope) -> None: ...
    def health_check(self) -> bool: ...
    def close(self) -> None: ...


def chunk_to_payload(chunk: EvidenceChunk, *, model: str, dimension: int,
                     revision: str) -> dict[str, Any]:
    if not model.strip() or not revision.strip() or dimension < 1:
        raise VectorStoreError("Metadata do modelo vetorial inválida.")
    return {**asdict(chunk), "embedding_model": model, "embedding_dimension": dimension,
            "embedding_revision": revision, "payload_version": PAYLOAD_VERSION}


def payload_to_chunk(payload: Mapping[str, Any]) -> EvidenceChunk:
    """Falha em registros incompletos; não inventa proveniência ausente."""
    if payload.get("payload_version") != PAYLOAD_VERSION:
        raise VectorStoreError("Versão do payload incompatível; reindexe os documentos.")
    names = {field.name for field in fields(EvidenceChunk)}
    if not names.issubset(payload):
        raise VectorStoreError("Payload vetorial sem proveniência completa; reindexe.")
    values = {name: payload[name] for name in names}
    optional_strings = {"pmcid", "doi"}
    integers = {"section_index", "chunk_index", "word_start", "word_end"}
    for name, value in values.items():
        if name in integers:
            if type(value) is not int or value < 0:
                raise VectorStoreError("Intervalos do payload vetorial inválidos.")
        elif name == "page_number":
            if value is not None and (type(value) is not int or value < 1):
                raise VectorStoreError("Página do payload vetorial inválida.")
        elif name in optional_strings and value is None:
            continue
        elif not isinstance(value, str) or (name not in optional_strings and not value.strip()):
            raise VectorStoreError("Texto ou proveniência do payload vetorial inválidos.")
    if values["word_end"] < values["word_start"]:
        raise VectorStoreError("Intervalo de palavras inválido.")
    return EvidenceChunk(**values)
