"""Avaliação offline de recuperação. Não consulta Gemini nem mede verdade científica."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from .chunking import EvidenceChunk, chunk_article_content
from .hybrid_retrieval import HybridIndex
from .pmc import ArticleContent, ContentSection
from .retrieval import Bm25Index, RetrievalError
from .semantic_retrieval import EmbeddingEncoder, SemanticIndex, SentenceTransformerEncoder


def _unique_ranking(ranking: Sequence[str], k: int) -> list[str]:
    if k < 1:
        raise ValueError("k deve ser positivo.")
    return list(dict.fromkeys(ranking))[:k]


def precision_at_k(ranking: Sequence[str], relevant: set[str], k: int) -> float:
    return sum(item in relevant for item in _unique_ranking(ranking, k)) / k


def recall_at_k(ranking: Sequence[str], relevant: set[str], k: int) -> float | None:
    selected = _unique_ranking(ranking, k)
    return sum(item in relevant for item in selected) / len(relevant) if relevant else None


def reciprocal_rank(ranking: Sequence[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    return next((1 / rank for rank, item in enumerate(dict.fromkeys(ranking), 1)
                 if item in relevant), 0.0)


def ndcg_at_k(ranking: Sequence[str], relevant: set[str], k: int) -> float | None:
    selected = _unique_ranking(ranking, k)
    if not relevant:
        return None
    dcg = sum(1 / math.log2(rank + 1) for rank, item in enumerate(selected, 1) if item in relevant)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return dcg / ideal


def _mean(values: Sequence[float | None]) -> float | None:
    defined = [value for value in values if value is not None]
    return sum(defined) / len(defined) if defined else None


@dataclass(frozen=True)
class GroundingMetrics:
    abstention_rate: float | None
    citation_validity: float | None
    passage_id_coverage: float | None
    evidence_passage_coverage: float | None
    structural_groundedness: float | None


def evaluate_grounding(
    answers: Sequence[Mapping[str, Any]], passages: Mapping[str, str],
) -> GroundingMetrics:
    """Verifica IDs e quotes literais; não decide se a interpretação é correta."""
    citations = [citation for answer in answers for citation in answer.get("citations", [])]
    def known(citation: Mapping[str, Any]) -> bool:
        return citation.get("passage_id") in passages
    def valid(citation: Mapping[str, Any]) -> bool:
        quote = citation.get("quote")
        return bool(isinstance(quote, str) and quote.strip() and known(citation)
                    and " ".join(quote.split()) in " ".join(passages[citation["passage_id"]].split()))
    abstained = [answer for answer in answers if answer.get("relation") in {"UNCERTAIN", "ABSTAIN"}]
    answered = [answer for answer in answers if answer.get("relation") not in {"UNCERTAIN", "ABSTAIN"}]
    grounded = sum(bool(answer.get("citations")) and all(valid(citation) for citation in answer["citations"])
                   for answer in answered)
    return GroundingMetrics(
        len(abstained) / len(answers) if answers else None,
        sum(valid(citation) for citation in citations) / len(citations) if citations else None,
        sum(known(citation) for citation in citations) / len(citations) if citations else None,
        len({citation["passage_id"] for citation in citations if known(citation)}) / len(passages) if passages else None,
        grounded / len(answered) if answered else None,
    )


class FixtureEncoder:
    """Somente regressão: os vetores são declarados, não aprendidos."""
    name = model_name = "golden-controlled-v1"

    def __init__(self, fixture: Mapping[str, Any]) -> None:
        self.vectors = {document["text"]: document["fixture_vector"] for document in fixture["documents"]}
        self.vectors.update({case["claim"]: case["fixture_query_vector"] for case in fixture["cases"]})
        dimensions = {len(vector) for vector in self.vectors.values()}
        if len(dimensions) != 1:
            raise RetrievalError("Vetores de fixture possuem dimensões incompatíveis.")
        self.dimension = dimensions.pop()

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        try:
            return [self.vectors[text] for text in texts]
        except KeyError:
            raise RetrievalError("Texto sem vetor de fixture; use um encoder real explicitamente.") from None


def fixture_chunks(fixture: Mapping[str, Any]) -> tuple[EvidenceChunk, ...]:
    chunks = []
    for document in fixture["documents"]:
        chunks.extend(chunk_article_content(ArticleContent(
            pmid=document["pmid"], pmcid=document.get("pmcid"), doi=document.get("doi"),
            abstract=document["text"], full_text=None,
            sections=(ContentSection(document["section"], document["text"]),),
            access_level="ABSTRACT_ONLY", pubmed_url=document["source_url"], pmc_url=None,
            parser_version="curated-abstract-excerpt-v1",
        )))
    return tuple(chunks)


def evaluate_fixture(
    fixture: Mapping[str, Any], encoder: EmbeddingEncoder, *, k: int = 1,
    minimum_score: float = 0.0, qdrant_path: str | None = None,
) -> dict[str, Any]:
    """Executa cinco métodos no mesmo corpus/consultas, incluindo reinicialização."""
    from .qdrant_retrieval import QdrantChunkStore
    if qdrant_path is None:
        raise ValueError("Informe um diretório Qdrant efêmero para esta avaliação.")
    chunks = fixture_chunks(fixture)
    lexical = Bm25Index(chunks)
    memory = SemanticIndex(chunks, encoder)
    class ThresholdIndex:
        def __init__(self) -> None:
            self.chunks = chunks
        def search(self, query: str, *, top_k: int) -> Any:
            return memory.search(query, top_k=top_k, minimum_score=minimum_score)
    threshold = ThresholdIndex()
    store = QdrantChunkStore(path=qdrant_path, encoder=encoder, collection_prefix="evaluation_chunks")
    try:
        indexed_count = store.upsert(chunks)
        persistent = store.index(chunks, minimum_score=minimum_score)
        methods = {"bm25": lexical, "semantic_memory": threshold,
                   "hybrid_memory": HybridIndex(lexical, threshold),
                   "semantic_qdrant": persistent, "hybrid_qdrant": HybridIndex(lexical, persistent)}
        reports: dict[str, Any] = {}
        for name, index in methods.items():
            cases = []
            for case in fixture["cases"]:
                results = index.search(case["claim"], top_k=k)
                ranking = [item.chunk.chunk_id for item in results]
                relevant = {chunk.chunk_id for chunk in chunks if chunk.pmid in case["relevant_pmids"]}
                acceptable = case.get("acceptable_first_pmids", [])
                cases.append({
                    "case_id": case["case_id"], "relevant_chunk_ids": sorted(relevant),
                    "ranking": [{"chunk_id": item.chunk.chunk_id, "pmid": item.chunk.pmid,
                                 "score": item.score, "source_url": item.chunk.source_url,
                                 **({"lexical_rank": item.lexical_rank, "semantic_rank": item.semantic_rank,
                                     "lexical_contribution": item.lexical_contribution,
                                     "semantic_contribution": item.semantic_contribution}
                                    if hasattr(item, "lexical_rank") else {})} for item in results],
                    "precision_at_k": precision_at_k(ranking, relevant, k),
                    "recall_at_k": recall_at_k(ranking, relevant, k),
                    "reciprocal_rank": reciprocal_rank(ranking, relevant),
                    "ndcg_at_k": ndcg_at_k(ranking, relevant, k),
                    "acceptable_first": (results[0].chunk.pmid in acceptable if results else False) if acceptable else None,
                    "retrieval_abstained": not results,
                })
            reports[name] = {
                "cases": cases,
                "summary": {"precision_at_k": _mean([case["precision_at_k"] for case in cases]),
                            "recall_at_k": _mean([case["recall_at_k"] for case in cases]),
                            "mrr": _mean([case["reciprocal_rank"] for case in cases]),
                            "ndcg_at_k": _mean([case["ndcg_at_k"] for case in cases]),
                            "retrieval_abstention_rate": sum(case["retrieval_abstained"] for case in cases) / len(cases)},
            }
        collection = store.collection
    finally:
        store.close()
    restarted = QdrantChunkStore(path=qdrant_path, encoder=encoder, collection_prefix="evaluation_chunks")
    try:
        restart_new_embeddings = restarted.upsert(chunks)
    finally:
        restarted.close()
    baseline = reports["bm25"]["summary"]
    differences = {name: {metric: (value - baseline[metric] if value is not None and baseline[metric] is not None else None)
                          for metric, value in data["summary"].items()}
                   for name, data in reports.items() if name != "bm25"}
    return {"executed_at": datetime.now(timezone.utc).isoformat(), "embedding_model": encoder.name,
            "controlled_embeddings": isinstance(encoder, FixtureEncoder), "k": k,
            "minimum_score": minimum_score, "document_count": len(chunks),
            "case_count": len(fixture["cases"]), "annotation_status": fixture.get("annotation_status"),
            "collection": collection, "initial_new_chunk_embeddings": indexed_count,
            "restart_new_chunk_embeddings": restart_new_embeddings, "methods": reports,
            "delta_against_bm25": differences,
            "answer_metrics": None,
            "limitations": ["Conjunto pequeno, sem validação clínica externa ou classificador de fake news.",
                             "Gemini/NLI não executados; métricas de citações e abstinência de respostas não foram medidas.",
                             "Vetores controlados não medem qualidade de Sentence Transformers." if isinstance(encoder, FixtureEncoder)
                             else "Resultados limitados ao modelo e fixtures registrados."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/retrieval/golden.json"))
    parser.add_argument("--encoder", choices=("fixture", "sentence-transformers"), default="fixture")
    parser.add_argument("--model", default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--minimum-score", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=Path("artifacts/retrieval-evaluation.json"))
    args = parser.parse_args()
    raw = args.fixtures.read_bytes()
    fixture = json.loads(raw)
    encoder = FixtureEncoder(fixture) if args.encoder == "fixture" else SentenceTransformerEncoder(args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="qdrant-evaluation-", dir=args.output.parent) as directory:
        report = evaluate_fixture(fixture, encoder, k=args.k, minimum_score=args.minimum_score, qdrant_path=directory)
    report["fixture_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "controlled_embeddings": report["controlled_embeddings"],
                      "summary": {name: value["summary"] for name, value in report["methods"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
