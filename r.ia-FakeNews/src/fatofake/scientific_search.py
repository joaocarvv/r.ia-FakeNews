"""Expansão auditável de consultas e reranking conservador por alegação."""

from __future__ import annotations

import re
import math
import unicodedata
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol, Sequence

from .federated_search import ScientificWork


_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "de", "da", "das", "do", "dos",
    "e", "em", "for", "from", "in", "is", "na", "nas", "no", "nos", "of",
    "o", "os", "para", "por", "que", "the", "to", "um", "uma", "with",
    "affect", "affects", "associated", "change", "changes", "effect", "effects",
}

# Vocabulário inicial deliberadamente pequeno. Ele é rastreável e nunca é apresentado
# como uma tradução completa do MeSH.
_CONTROLLED_TERMS = {
    "cancer": ("neoplasm", "tumor", "carcinoma"),
    "coffee": ("caffeine",),
    "prostate": ("prostatic",),
    "kidney": ("renal",),
    "heart": ("cardiac", "cardiovascular"),
    "stroke": ("cerebrovascular",),
    "high blood pressure": ("hypertension",),
    "randomized": ("randomised", "controlled trial"),
}

_MESH_DESCRIPTORS = {
    "coffee": "Coffee",
    "cancer": "Neoplasms",
    "prostate cancer": "Prostatic Neoplasms",
    "hypertension": "Hypertension",
    "high blood pressure": "Hypertension",
    "rhodopsin": "Rhodopsin",
    "osmotic pressure": "Osmotic Pressure",
    "hydrostatic pressure": "Hydrostatic Pressure",
    "clinical trial": "Clinical Trials as Topic",
}


def _plain(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            token
            for token in re.findall(r"[a-z0-9]+", _plain(value))
            if len(token) >= 3 and token not in _STOPWORDS
        )
    )


@dataclass(frozen=True)
class ExpandedQuery:
    query: str
    strategy: str
    explanation: str


@dataclass(frozen=True)
class RerankedWork:
    work: ScientificWork
    score: float
    accepted: bool
    concept_matches: tuple[str, ...]
    reasons: tuple[str, ...]


def expand_scientific_queries(
    claim: str,
    base_queries: Sequence[str],
    *,
    seed_doi: str | None = None,
    seed_authors: Sequence[str] = (),
    max_queries: int = 6,
) -> tuple[ExpandedQuery, ...]:
    """Cria um plano limitado e explica a finalidade de cada consulta."""

    if not 1 <= max_queries <= 10:
        raise ValueError("max_queries deve estar entre 1 e 10.")
    compact_bases = [" ".join(item.split())[:300] for item in base_queries if item.strip()]
    thematic = compact_bases[0] if compact_bases else " ".join(claim.split())[:300]
    lowered = _plain(f"{claim} {thematic}")
    candidates: list[ExpandedQuery] = [
        ExpandedQuery(thematic, "THEMATIC", "Consulta temática principal da alegação."),
    ]

    synonyms: list[str] = []
    for concept, alternatives in _CONTROLLED_TERMS.items():
        if _contains_phrase(lowered, concept):
            synonyms.extend((concept, *alternatives))
    if synonyms:
        synonym_clause = " OR ".join(f'"{item}"' for item in dict.fromkeys(synonyms))
        candidates.append(
            ExpandedQuery(
                f"({thematic}) ({synonym_clause})",
                "SYNONYMS",
                "Expansão por sinônimos biomédicos do vocabulário local auditável.",
            )
        )

    mesh_concepts = [
        (phrase, descriptor)
        for phrase, descriptor in _MESH_DESCRIPTORS.items()
        if _contains_phrase(lowered, phrase)
    ]
    # A expressão específica já cobre a genérica (prostate cancer/cancer).
    mesh_concepts = [(phrase, descriptor) for phrase, descriptor in mesh_concepts
                     if not any(phrase != other and _contains_phrase(other, phrase)
                                for other, _ in mesh_concepts)]
    if mesh_concepts:
        clauses = []
        for phrase, descriptor in dict.fromkeys(mesh_concepts):
            entry_terms = (phrase, *_CONTROLLED_TERMS.get(phrase, ()))
            text_terms = " OR ".join(
                f'"{term}"[Title/Abstract]' for term in dict.fromkeys(entry_terms)
            )
            clauses.append(f'("{descriptor}"[MeSH Terms] OR {text_terms})')
        candidates.append(
            ExpandedQuery(
                " AND ".join(clauses),
                "MESH_CANDIDATES",
                "Descritores MeSH explícitos combinados a termos de título/resumo; "
                "a consulta temática separada preserva o Automatic Term Mapping.",
            )
        )

    candidates.append(
        ExpandedQuery(
            f"({thematic}) (systematic review OR meta-analysis)",
            "EVIDENCE_SYNTHESIS",
            "Busca direcionada a revisões sistemáticas e meta-análises.",
        )
    )
    if seed_doi:
        candidates.append(
            ExpandedQuery(
                seed_doi.strip(),
                "SEED_DOI",
                "Localização exata do artigo-semente pelo DOI.",
            )
        )
    if seed_authors:
        first_author = " ".join(seed_authors[0].split())
        # A alegação pode estar em português; a consulta temática já está em inglês.
        topic = " ".join(
            token for token in _tokens(thematic) if token not in {"and", "not"}
        )[:120] or " ".join(_tokens(claim)[:4])
        topic = " ".join(topic.split()[:4])
        candidates.append(
            ExpandedQuery(
                f'"{first_author}" {topic}'.strip()[:300],
                "SEED_AUTHOR",
                "Busca por primeiro autor combinada aos conceitos da alegação.",
            )
        )

    candidates.extend(
        ExpandedQuery(query, "LANGUAGE_VARIANT", "Variação temática produzida pelo planejador.")
        for query in compact_bases[1:]
    )
    unique: list[ExpandedQuery] = []
    seen: set[str] = set()
    for item in candidates:
        key = item.query.casefold()
        if item.query and key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) == max_queries:
            break
    return tuple(unique)


class ClaimRelevanceReranker:
    """Reordena metadados e abstém-se de promover coincidências de uma palavra."""

    _GRAPH_SOURCES = {
        "OpenAlex referências",
        "OpenAlex citações",
        "OpenAlex relacionados",
        "PubMed relacionados",
    }

    @staticmethod
    def _canonical_tokens(value: str) -> set[str]:
        normalized = _plain(value)
        concepts: set[str] = set()
        multiword_phrases = sorted(
            {
                phrase
                for phrase in (*_CONTROLLED_TERMS, *_MESH_DESCRIPTORS)
                if " " in phrase
            },
            key=len,
            reverse=True,
        )
        for phrase in multiword_phrases:
            if phrase in normalized:
                concepts.add(phrase.replace(" ", "_"))
                normalized = normalized.replace(phrase, " ")
        tokens = set(_tokens(normalized))
        for concept, alternatives in _CONTROLLED_TERMS.items():
            if " " in concept:
                continue
            alias_tokens = set(_tokens(" ".join((concept, *alternatives))))
            if tokens & alias_tokens:
                tokens.difference_update(alias_tokens)
                tokens.add(concept)
        return tokens | concepts

    def rank(
        self,
        claim: str,
        works: Sequence[ScientificWork],
    ) -> tuple[RerankedWork, ...]:
        claim_tokens = self._canonical_tokens(claim)
        required_matches = min(2, len(claim_tokens))
        maximum_rrf = max((item.retrieval_score for item in works), default=0.0) or 1.0
        ranked: list[RerankedWork] = []
        for work in works:
            title_tokens = self._canonical_tokens(work.title)
            matches = tuple(sorted(claim_tokens & title_tokens))
            coverage = len(matches) / max(len(claim_tokens), 1)
            graph_match = bool(set(work.sources) & self._GRAPH_SOURCES)
            source_support = min(len(work.sources) / 3, 1.0)
            normalized_rrf = min(work.retrieval_score / maximum_rrf, 1.0)
            accepted = len(matches) >= required_matches or (
                graph_match and len(matches) >= 1
            )
            score = round(
                0.65 * coverage
                + 0.15 * source_support
                + 0.15 * normalized_rrf
                + (0.05 if graph_match else 0.0),
                4,
            )
            reasons = [f"{len(matches)} conceito(s) da alegação no título"]
            if len(work.sources) > 1:
                reasons.append(f"recuperado por {len(work.sources)} fontes")
            if graph_match:
                reasons.append("ligação explícita com o artigo-semente")
            if not accepted:
                reasons.append("cobertura temática insuficiente para análise automática")
            ranked.append(RerankedWork(work, score, accepted, matches, tuple(reasons)))
        ranked.sort(
            key=lambda item: (
                not item.accepted,
                -item.score,
                item.work.title.casefold(),
            )
        )
        return tuple(ranked)


class BiomedicalReranker(Protocol):
    name: str

    def score(self, query: str, documents: Sequence[str]) -> Sequence[float]: ...


class MedCptCrossEncoderReranker:
    """Cross-encoder oficial do NCBI, carregado somente quando o shadow é executado."""

    name = "ncbi/MedCPT-Cross-Encoder"

    def __init__(self, model_name: str = name) -> None:
        self.name = model_name
        self._torch = self._tokenizer = self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as error:
            raise RuntimeError(
                "torch e transformers são necessários para o reranker MedCPT."
            ) from error
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(self.name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.name)
            self._model.eval()
            self._torch = torch
        except Exception as error:
            raise RuntimeError("Não foi possível carregar o reranker MedCPT.") from error

    def score(self, query: str, documents: Sequence[str]) -> tuple[float, ...]:
        if not query.strip() or not documents:
            return ()
        self._load()
        scores = []
        for start in range(0, len(documents), 16):
            pairs = [[query, document] for document in documents[start:start + 16]]
            encoded = self._tokenizer(
                pairs, truncation=True, padding=True, return_tensors="pt", max_length=512,
            )
            with self._torch.no_grad():
                logits = self._model(**encoded).logits.squeeze(dim=1)
            scores.extend(float(value) for value in logits.cpu().tolist())
        return tuple(scores)


def biomedical_shadow_ranking(
    query: str,
    works: Sequence[ScientificWork],
    reranker: BiomedicalReranker,
    *,
    top_n: int = 50,
) -> dict[str, object]:
    """Calcula um ranking alternativo sem alterar aceitação, ordem ou resposta ao usuário."""

    if top_n < 1:
        raise ValueError("top_n deve ser positivo.")
    candidates = tuple(works[:top_n])
    started = perf_counter()
    scores = tuple(float(value) for value in reranker.score(
        query, [work.title for work in candidates]
    ))
    if len(scores) != len(candidates) or not all(math.isfinite(score) for score in scores):
        raise RuntimeError("O reranker retornou quantidade inesperada de scores.")
    indexed = list(enumerate(zip(candidates, scores), start=1))
    ranked = sorted(indexed, key=lambda item: (-item[1][1], item[1][0].title.casefold()))
    new_rank = {old_rank: rank
                for rank, (old_rank, _) in enumerate(ranked, start=1)}
    return {
        "status": "available",
        "mode": "shadow",
        "model_name": reranker.name,
        "document_scope": "title_only",
        "evaluated_count": len(candidates),
        "duration_ms": round((perf_counter() - started) * 1000, 2),
        "ranking": [
            {
                "title": work.title,
                "doi": work.doi,
                "pmid": work.pmid,
                "baseline_rank": old_rank,
                "shadow_rank": new_rank[old_rank],
                "score": score,
            }
            for old_rank, (work, score) in indexed
        ],
    }
