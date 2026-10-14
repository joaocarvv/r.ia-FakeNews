"""Recupera trechos por similaridade semântica entre embeddings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from .chunking import EvidenceChunk
from .retrieval import RetrievalError


DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
MEDCPT_EMBEDDING_MODEL = "ncbi/MedCPT"
MEDCPT_QUERY_MODEL = "ncbi/MedCPT-Query-Encoder"
MEDCPT_ARTICLE_MODEL = "ncbi/MedCPT-Article-Encoder"


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

    @property
    def model_name(self) -> str:
        return self.name

    @property
    def dimension(self) -> int:
        dimension = self._model.get_sentence_embedding_dimension()
        if dimension is None or dimension < 1:
            raise RetrievalError("O modelo não informou uma dimensão válida.")
        return int(dimension)

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()


class MedCptDualEncoder:
    """Dual encoder oficial do MedCPT: consulta e documento não compartilham pesos."""

    name = model_name = MEDCPT_EMBEDDING_MODEL
    dimension = 768

    def __init__(self, *, query_model: str = MEDCPT_QUERY_MODEL,
                 article_model: str = MEDCPT_ARTICLE_MODEL) -> None:
        self.query_model_name = query_model
        self.article_model_name = article_model
        self._torch = None
        self._query_tokenizer = self._query_model = None
        self._article_tokenizer = self._article_model = None

    def _load(self) -> None:
        if self._query_model is not None:
            return
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:
            raise RetrievalError(
                "torch e transformers são necessários para usar o MedCPT."
            ) from error
        try:
            query_tokenizer = AutoTokenizer.from_pretrained(self.query_model_name)
            query_model = AutoModel.from_pretrained(self.query_model_name)
            article_tokenizer = AutoTokenizer.from_pretrained(self.article_model_name)
            article_model = AutoModel.from_pretrained(self.article_model_name)
            query_model.eval()
            article_model.eval()
            self._query_tokenizer, self._query_model = query_tokenizer, query_model
            self._article_tokenizer, self._article_model = article_tokenizer, article_model
            self._torch = torch
        except Exception as error:
            raise RetrievalError("Não foi possível carregar os encoders MedCPT.") from error

    def _encode(self, texts: Sequence[str], *, query: bool) -> list[list[float]]:
        self._load()
        tokenizer = self._query_tokenizer if query else self._article_tokenizer
        model = self._query_model if query else self._article_model
        max_length = 64 if query else 512
        result = []
        for start in range(0, len(texts), 32):
            batch = list(texts[start:start + 32])
            # Sem título disponível no contrato de chunks: segundo segmento é o trecho.
            inputs = batch if query else [["", text] for text in batch]
            encoded = tokenizer(
                inputs, truncation=True, padding=True, return_tensors="pt",
                max_length=max_length,
            )
            with self._torch.no_grad():
                vectors = model(**encoded).last_hidden_state[:, 0, :]
                vectors = self._torch.nn.functional.normalize(vectors, p=2, dim=1)
            result.extend(vectors.cpu().tolist())
        return result

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts, query=True)

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts, query=False)

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Compatibilidade: textos sem papel explícito são tratados como documentos."""
        return self.encode_documents(texts)


def _encode_documents(
    encoder: EmbeddingEncoder, texts: Sequence[str]
) -> Sequence[Sequence[float]]:
    method = getattr(encoder, "encode_documents", None)
    return method(texts) if callable(method) else encoder.encode(texts)


def _encode_queries(
    encoder: EmbeddingEncoder, texts: Sequence[str]
) -> Sequence[Sequence[float]]:
    method = getattr(encoder, "encode_queries", None)
    return method(texts) if callable(method) else encoder.encode(texts)


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
    expected_dimension: int | None = None,
) -> tuple[tuple[float, ...], ...]:
    try:
        normalized_vectors = tuple(tuple(float(value) for value in vector) for vector in vectors)
    except (TypeError, ValueError, OverflowError) as error:
        raise RetrievalError("O codificador retornou valores não numéricos.") from error
    if len(normalized_vectors) != expected_count:
        raise RetrievalError("O codificador retornou uma quantidade inesperada de vetores.")
    if not normalized_vectors or not normalized_vectors[0]:
        raise RetrievalError("O codificador retornou vetores vazios.")

    dimension = len(normalized_vectors[0])
    if expected_dimension is not None and dimension != expected_dimension:
        raise RetrievalError("A dimensão do embedding é incompatível com o modelo configurado.")
    for vector in normalized_vectors:
        if len(vector) != dimension:
            raise RetrievalError("Os embeddings possuem dimensões diferentes.")
        if not all(math.isfinite(value) for value in vector):
            raise RetrievalError("Os embeddings possuem valores não finitos.")
        if math.hypot(*vector) == 0:
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
            _encode_documents(encoder, [chunk.text for chunk in self.chunks]),
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
            _encode_queries(self.encoder, [query]),
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


class EmbeddingProvider(EmbeddingEncoder, Protocol):
    """Modelo explícito, dimensão auditável e nenhuma substituição automática."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...


class ValidatedEmbeddingProvider:
    """Adapta encoders antigos e carrega o modelo apenas no primeiro encode."""

    def __init__(self, model_name: str, *, encoder: EmbeddingEncoder | None = None,
                 factory: Callable[[], EmbeddingEncoder] | None = None) -> None:
        self.name = self.model_name = model_name
        self._encoder = encoder
        self._factory = factory or (
            (lambda: MedCptDualEncoder())
            if model_name == MEDCPT_EMBEDDING_MODEL
            else (lambda: SentenceTransformerEncoder(model_name))
        )
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            raise RetrievalError("A dimensão só está disponível após carregar o modelo.")
        return self._dimension

    def encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return self.encode_documents(texts)

    def encode_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return self._encode_role(texts, role="documents")

    def encode_queries(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return self._encode_role(texts, role="queries")

    def _encode_role(self, texts: Sequence[str], *, role: str) -> tuple[tuple[float, ...], ...]:
        if self._encoder is None:
            self._encoder = self._factory()
        if self._encoder.name != self.model_name:
            raise RetrievalError("O encoder não corresponde ao modelo configurado.")
        declared = getattr(self._encoder, "dimension", None)
        expected = self._dimension if self._dimension is not None else declared
        method = getattr(self._encoder, f"encode_{role}", None)
        raw = method(texts) if callable(method) else self._encoder.encode(texts)
        vectors = _validated_vectors(raw, expected_count=len(texts), expected_dimension=expected)
        if declared is not None and len(vectors[0]) != declared:
            raise RetrievalError("Dimensão declarada pelo modelo incompatível.")
        self._dimension = len(vectors[0])
        return vectors
