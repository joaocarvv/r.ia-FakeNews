"""Persistência vetorial opcional, com proveniência e escopo científico explícito."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import logging
import math
import re
import threading
from time import perf_counter
from typing import Any, Iterator, Sequence
import uuid

from .chunking import EvidenceChunk
from .retrieval import RetrievalError
from .semantic_retrieval import (
    DEFAULT_EMBEDDING_MODEL, EmbeddingEncoder, SemanticRetrievedChunk,
    ValidatedEmbeddingProvider,
)
from .structured_logging import log_event
from .vector_store import (
    PAYLOAD_VERSION, ChunkScope, CollectionMetadata, VectorStoreError,
    chunk_to_payload, payload_to_chunk,
)

logger = logging.getLogger(__name__)


class QdrantChunkStore:
    """Uma collection por modelo/revisão/schema; dimensão validada antes da escrita."""

    backend = "qdrant"

    def __init__(
        self, *, path: str | None = None, url: str | None = None,
        api_key: str | None = None, encoder: EmbeddingEncoder | None = None,
        model_name: str | None = None, revision: str = "v1",
        collection_prefix: str = "fatofake_chunks", timeout: float = 20,
        client: Any = None,
    ) -> None:
        if path and url:
            raise VectorStoreError("Configure QDRANT_PATH ou QDRANT_URL, não ambos.")
        if client is None and not (path or url):
            raise VectorStoreError("Configure QDRANT_URL ou QDRANT_PATH para habilitar Qdrant.")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", collection_prefix):
            raise VectorStoreError("QDRANT_COLLECTION_PREFIX aceita letras, números, _ e - (até 80).")
        if not math.isfinite(timeout) or timeout <= 0 or not revision.strip():
            raise VectorStoreError("QDRANT_TIMEOUT e EMBEDDING_REVISION devem ser válidos.")
        self._lock = threading.RLock()
        self._client = client
        self._connection = {"url": url, "api_key": api_key, "timeout": timeout} if url else {"path": path}
        self.model_name = model_name if model_name is not None else (encoder.name if encoder is not None else DEFAULT_EMBEDDING_MODEL)
        if encoder is not None and encoder.name != self.model_name:
            raise VectorStoreError("O encoder não corresponde a EMBEDDING_MODEL; nenhum modelo alternativo é permitido.")
        if not self.model_name.strip():
            raise VectorStoreError("EMBEDDING_MODEL não pode estar vazio.")
        self.revision = revision
        self.encoder = ValidatedEmbeddingProvider(self.model_name, encoder=encoder)
        namespace = json.dumps([self.model_name, revision, PAYLOAD_VERSION])
        digest = hashlib.sha256(namespace.encode()).hexdigest()[:24]
        self.collection = f"{collection_prefix}_{digest}"

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
            except ImportError:
                raise VectorStoreError("Instale requirements.txt para habilitar qdrant-client.") from None
            self._client = QdrantClient(**self._connection)
        return self._client

    @contextmanager
    def _operation(self, operation: str) -> Iterator[None]:
        with self._lock:
            try:
                yield
            except VectorStoreError as error:
                log_event(logger, logging.ERROR, "Validação da operação vetorial falhou",
                          event="vector.failure", operation=operation, backend="qdrant",
                          collection=self.collection, error_type=type(error).__name__)
                raise
            except RetrievalError as error:
                log_event(logger, logging.ERROR, "Falha no codificador de embeddings",
                          event="vector.failure", operation=operation, backend="qdrant",
                          collection=self.collection, error_type=type(error).__name__)
                raise VectorStoreError(
                    "Falha no codificador de embeddings. Instale requirements.txt e verifique "
                    "EMBEDDING_MODEL, a dimensão e EMBEDDING_REVISION. Nenhum modelo alternativo foi usado."
                ) from None
            except Exception as error:
                # Exceções HTTP podem incluir URL, chave ou conteúdo. Não propagá-las.
                log_event(logger, logging.ERROR, "Falha na operação vetorial", event="vector.failure",
                          operation=operation, backend="qdrant", collection=self.collection,
                          error_type=type(error).__name__)
                raise VectorStoreError(
                    f"Qdrant: falha em {operation}. Verifique QDRANT_URL/QDRANT_PATH, "
                    "a disponibilidade do serviço, o modelo e a configuração de acesso. "
                    "Nenhum backend alternativo foi usado."
                ) from None

    def health_check(self) -> bool:
        with self._operation("health_check"):
            self.client.get_collections()
            return True

    def metadata(self) -> CollectionMetadata:
        with self._operation("metadata"):
            if not self.client.collection_exists(self.collection):
                raise VectorStoreError("Collection ausente; indexe os trechos antes de consultar.")
            info = self.client.get_collection(self.collection)
            vectors = info.config.params.vectors
            if not hasattr(vectors, "size") or str(vectors.distance).lower() != "cosine":
                raise VectorStoreError("Collection incompatível: use um vetor denso com distância Cosine.")
            return CollectionMetadata(self.collection, self.model_name, self.revision,
                                      vectors.size, str(vectors.distance), info.points_count or 0)

    def ensure_collection(self, dimension: int) -> CollectionMetadata:
        if type(dimension) is not int or dimension < 1:
            raise VectorStoreError("Dimensão vetorial inválida.")
        with self._operation("ensure_collection"):
            from qdrant_client import models
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                    size=dimension, distance=models.Distance.COSINE))
            metadata = self.metadata()
            if metadata.embedding_dimension != dimension:
                raise VectorStoreError(
                    "Collection incompatível com a dimensão do modelo. "
                    "Configure uma nova EMBEDDING_REVISION e reindexe."
                )
            return metadata

    def _point_id(self, chunk: EvidenceChunk) -> str:
        # Texto original, URL, página e versões participam da identidade do cache.
        fingerprint = json.dumps(asdict(chunk), sort_keys=True, ensure_ascii=False)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, self.collection + fingerprint))

    def _validate_payload(self, payload: dict[str, Any], dimension: int) -> EvidenceChunk:
        if (payload.get("embedding_model") != self.model_name
                or payload.get("embedding_revision") != self.revision
                or payload.get("embedding_dimension") != dimension):
            raise VectorStoreError("Payload pertence a um modelo/dimensão/revisão incompatível; reindexe.")
        return payload_to_chunk(payload)

    def upsert(self, chunks: Sequence[EvidenceChunk]) -> int:
        """Reusa registros íntegros; retorna a quantidade de embeddings novos."""
        if not chunks:
            raise VectorStoreError("Ao menos um trecho é necessário para indexar.")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise VectorStoreError("O conjunto possui chunk_ids duplicados.")
        started = perf_counter()
        with self._operation("upsert"):
            from qdrant_client import models
            by_id = {self._point_id(chunk): chunk for chunk in chunks}
            ids = list(by_id)
            known: set[str] = set()
            dimension: int | None = None
            if self.client.collection_exists(self.collection):
                dimension = self.metadata().embedding_dimension
                for start in range(0, len(ids), 128):
                    records = self.client.retrieve(self.collection, ids=ids[start:start + 128],
                                                   with_payload=True, with_vectors=False)
                    for record in records:
                        if str(record.id) not in by_id:
                            raise VectorStoreError("O armazenamento retornou um registro não solicitado.")
                        restored = self._validate_payload(record.payload or {}, dimension)
                        if restored != by_id[str(record.id)]:
                            raise VectorStoreError("A proveniência persistida diverge do documento; reindexe.")
                        known.add(str(record.id))
            missing = [point_id for point_id in ids if point_id not in known]
            for start in range(0, len(missing), 64):
                batch = missing[start:start + 64]
                vectors = self.encoder.encode_documents([by_id[point_id].text for point_id in batch])
                dimension = len(vectors[0])
                self.ensure_collection(dimension)
                points = []
                for point_id, vector in zip(batch, vectors):
                    payload = chunk_to_payload(by_id[point_id], model=self.model_name,
                                               dimension=dimension, revision=self.revision)
                    payload_to_chunk(payload)  # Validação antes da escrita, inclusive Unicode/proveniência.
                    points.append(models.PointStruct(id=point_id, vector=list(vector), payload=payload))
                self.client.upsert(self.collection, wait=True, points=points)
            log_event(logger, logging.INFO, "Trechos vetoriais indexados", event="vector.index",
                      backend="qdrant", collection=self.collection, embedding_model=self.model_name,
                      embedding_revision=self.revision, embedding_dimension=dimension,
                      chunk_count=len(chunks), indexed_count=len(missing), reused_count=len(known),
                      chunker_versions=sorted({chunk.chunker_version for chunk in chunks}),
                      parser_versions=sorted({chunk.parser_version for chunk in chunks}),
                      duration_ms=round((perf_counter() - started) * 1000, 2))
            return len(missing)

    def _scope_filter(self, scope: ChunkScope, point_ids: Sequence[str] | None = None) -> Any:
        from qdrant_client import models
        if scope.collection is not None and scope.collection != self.collection:
            raise VectorStoreError("A collection solicitada está fora do escopo deste backend.")
        if not scope.restricted:
            raise VectorStoreError("A busca/invalidação exige um escopo científico explícito.")
        conditions = []
        for field, values in (
            ("pmid", scope.pmids), ("pmcid", scope.pmcids), ("doi", scope.dois),
            ("source_kind", scope.source_kinds), ("content_scope", scope.content_scopes),
            ("chunk_id", scope.chunk_ids),
        ):
            if values is not None:
                conditions.append(models.FieldCondition(key=field, match=models.MatchAny(any=list(values))))
        if point_ids is not None:
            conditions.append(models.HasIdCondition(has_id=list(point_ids)))
        return models.Filter(must=conditions)

    def _search(
        self, query: str, *, scope: ChunkScope, top_k: int, minimum_score: float,
        point_ids: Sequence[str] | None = None,
    ) -> tuple[SemanticRetrievedChunk, ...]:
        if not query.strip() or top_k < 1 or not math.isfinite(minimum_score) or not -1 <= minimum_score <= 1:
            raise VectorStoreError("Consulta, VECTOR_TOP_K ou VECTOR_MIN_SCORE inválido.")
        started = perf_counter()
        with self._operation("search"):
            query_filter = self._scope_filter(scope, point_ids)
            # A lista vazia é negação de acesso e nunca se transforma em consulta global.
            values = (scope.pmids, scope.pmcids, scope.dois, scope.source_kinds,
                      scope.content_scopes, scope.chunk_ids, point_ids)
            if any(value is not None and len(value) == 0 for value in values):
                return ()
            self.metadata()  # Busca não cria silenciosamente um índice vazio.
            vector = self.encoder.encode_queries([query])[0]
            metadata = self.ensure_collection(len(vector))
            found = self.client.query_points(
                self.collection, query=list(vector), query_filter=query_filter,
                limit=top_k, with_payload=True, with_vectors=False,
            ).points
            valid: list[tuple[float, EvidenceChunk]] = []
            discarded = 0
            for point in found:
                chunk = self._validate_payload(point.payload or {}, metadata.embedding_dimension)
                if (not scope.matches(chunk) or not math.isfinite(point.score)
                        or (point_ids is not None and str(point.id) not in point_ids)):
                    # Uma violação de autorização indica falha, não redução silenciosa do resultado.
                    log_event(logger, logging.ERROR, "Candidato vetorial fora do escopo ou inválido",
                              event="vector.scope_violation", backend="qdrant", collection=self.collection,
                              candidate_count=len(found), filtered_discard_count=1)
                    raise VectorStoreError("Qdrant retornou um candidato fora do escopo ou inválido.")
                # Qdrant aplica limiar estrito; o SemanticIndex existente aceita >=.
                # Aplicar aqui preserva a semântica inclusive no limite exato (ex.: 0).
                if point.score < minimum_score:
                    discarded += 1
                    continue
                valid.append((point.score, chunk))
            valid.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
            results = tuple(SemanticRetrievedChunk(rank, score, chunk)
                            for rank, (score, chunk) in enumerate(valid, 1))
            log_event(logger, logging.INFO, "Busca vetorial concluída", event="vector.search",
                      backend="qdrant", collection=self.collection, embedding_model=self.model_name,
                      embedding_dimension=metadata.embedding_dimension, top_k=top_k,
                      minimum_score=minimum_score, candidate_count=len(found),
                      filtered_discard_count=discarded, returned_chunk_ids=[item.chunk.chunk_id for item in results],
                      duration_ms=round((perf_counter() - started) * 1000, 2))
            return results

    def search(self, query: str, *, scope: ChunkScope, top_k: int = 5,
               minimum_score: float = 0.0) -> tuple[SemanticRetrievedChunk, ...]:
        return self._search(query, scope=scope, top_k=top_k, minimum_score=minimum_score)

    def index(self, chunks: Sequence[EvidenceChunk], *, scope: ChunkScope | None = None,
              minimum_score: float = 0.0) -> QdrantSemanticIndex:
        if not chunks:
            raise VectorStoreError("Ao menos um trecho é necessário para criar o índice.")
        return QdrantSemanticIndex(tuple(chunks), self, scope=scope, minimum_score=minimum_score)

    def invalidate(self, scope: ChunkScope) -> None:
        with self._operation("invalidate"):
            from qdrant_client import models
            query_filter = self._scope_filter(scope)
            if self.client.collection_exists(self.collection):
                self.client.delete(self.collection, points_selector=models.FilterSelector(filter=query_filter), wait=True)

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None


class QdrantSemanticIndex:
    """Adapter do contrato de HybridIndex; exige os chunks autorizados atuais."""

    def __init__(self, chunks: tuple[EvidenceChunk, ...], store: QdrantChunkStore, *,
                 scope: ChunkScope | None = None, minimum_score: float = 0.0) -> None:
        self.chunks, self.store = chunks, store
        self.scope = scope or ChunkScope(chunk_ids=tuple(chunk.chunk_id for chunk in chunks))
        self.minimum_score = minimum_score

    def search(self, query: str, *, top_k: int = 5,
               minimum_score: float | None = None) -> tuple[SemanticRetrievedChunk, ...]:
        self.store.upsert(self.chunks)
        results = self.store._search(
            query, scope=self.scope, top_k=top_k,
            minimum_score=self.minimum_score if minimum_score is None else minimum_score,
            point_ids=[self.store._point_id(chunk) for chunk in self.chunks],
        )
        expected = {chunk.chunk_id: chunk for chunk in self.chunks}
        if any(expected.get(item.chunk.chunk_id) != item.chunk for item in results):
            raise VectorStoreError("O texto recuperado diverge do conjunto de evidências autorizado.")
        return results
