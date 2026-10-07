"""Comparação operacional sem rótulos; não estima qualidade de relevância."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tempfile
from time import perf_counter

from .hybrid_retrieval import HybridIndex
from .qdrant_retrieval import QdrantChunkStore
from .retrieval import Bm25Index
from .retrieval_evaluation import FixtureEncoder, fixture_chunks
from .semantic_retrieval import DEFAULT_EMBEDDING_MODEL, ValidatedEmbeddingProvider


class CountingEncoder:
    def __init__(self, encoder):
        self.encoder = encoder
        self.name = encoder.name
        self.documents = 0
        self.queries = 0

    def encode_documents(self, texts):
        self.documents += len(texts)
        method = getattr(self.encoder, 'encode_documents', self.encoder.encode)
        return method(texts)

    def encode_queries(self, texts):
        self.queries += len(texts)
        method = getattr(self.encoder, 'encode_queries', self.encoder.encode)
        return method(texts)

    def encode(self, texts):
        return self.encode_documents(texts)


def compare_unlabelled(fixture, encoder, *, path, k=5, minimum_score=0.0, reranker=None):
    """Mesmo corpus, várias consultas, repetição quente e reabertura do Qdrant."""
    if not fixture.get('documents') or not fixture.get('cases') or k < 1:
        raise ValueError('Informe documentos, alegações e k positivo.')
    chunks = fixture_chunks(fixture)
    counter = CountingEncoder(encoder)
    started = perf_counter()
    lexical = Bm25Index(chunks)
    lexical_build_ms = (perf_counter() - started) * 1000
    store = QdrantChunkStore(path=str(path), encoder=counter, collection_prefix='operational')
    reports = []
    baseline = {}
    initial_embeddings = None
    restart_embeddings = None
    for phase in ('cold', 'warm', 'restart'):
        if phase == 'restart':
            store = QdrantChunkStore(path=str(path), encoder=counter, collection_prefix='operational')
        try:
            started = perf_counter()
            new_embeddings = store.upsert(chunks)
            index_ms = (perf_counter() - started) * 1000
            if phase == 'cold':
                initial_embeddings = new_embeddings
            if phase == 'restart':
                restart_embeddings = new_embeddings
            semantic = store.index(chunks, minimum_score=minimum_score)
            methods = {'bm25': lexical, 'semantic': semantic, 'hybrid': HybridIndex(lexical, semantic)}
            before = counter.documents
            for case in fixture['cases']:
                for method, index in methods.items():
                    started = perf_counter()
                    results = index.search(case['claim'], top_k=k)
                    duration_ms = (perf_counter() - started) * 1000
                    ranking = [item.chunk.chunk_id for item in results]
                    key = (case['case_id'], method)
                    if phase == 'cold':
                        baseline[key] = ranking
                    bm25 = baseline[(case['case_id'], 'bm25')]
                    union = set(ranking) | set(bm25)
                    overlap = len(set(ranking) & set(bm25)) / len(union) if union else 1.0
                    record = {'phase': phase, 'case_id': case['case_id'], 'method': method,
                              'duration_ms': round(duration_ms, 3), 'ranking': ranking,
                              'pmids': [item.chunk.pmid for item in results],
                              'scores': [item.score for item in results],
                              'jaccard_against_bm25': overlap,
                              'same_order_as_bm25': ranking == bm25,
                              'same_order_as_cold': ranking == baseline[key]}
                    if reranker is not None and method == 'hybrid' and results:
                        started = perf_counter()
                        scores = list(reranker.score(case['claim'], [item.chunk.text for item in results]))
                        import math
                        if len(scores) != len(results) or not all(math.isfinite(float(v)) for v in scores):
                            raise ValueError('Scores inválidos do reranker.')
                        order = sorted(range(len(results)), key=lambda i: (-scores[i], i))
                        record['shadow'] = {'model': reranker.name, 'scope': 'chunk_text',
                                            'duration_ms': round((perf_counter() - started) * 1000, 3),
                                            'ranking': [ranking[i] for i in order], 'scores': scores}
                    reports.append(record)
            reports.append({'phase': phase, 'index_duration_ms': round(index_ms, 3),
                            'new_document_embeddings': new_embeddings,
                            'document_embeddings_during_search': counter.documents - before})
        except Exception:
            store.close()
            raise
        finally:
            if phase != 'cold':
                store.close()
    packages = {}
    for package in ('torch', 'transformers', 'sentence-transformers', 'qdrant-client'):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {'environment': {'python': platform.python_version(), 'machine': platform.machine(),
                            'system': platform.system(), 'packages': packages},
            'executed_at': datetime.now(timezone.utc).isoformat(), 'embedding_model': encoder.name,
            'annotation_status': 'unlabelled', 'relevance_metrics': None,
            'controlled_embeddings': isinstance(encoder, FixtureEncoder),
            'document_count': len(chunks), 'claim_count': len(fixture['cases']), 'k': k,
            'minimum_score': minimum_score, 'bm25_build_ms': round(lexical_build_ms, 3),
            'initial_new_document_embeddings': initial_embeddings,
            'restart_new_document_embeddings': restart_embeddings,
            'document_encodes': counter.documents, 'query_encodes': counter.queries,
            'runs': reports,
            'limitations': ['Sem conjunto ouro: concordância e mudança de ranking não medem relevância.',
                            'Tempos incluem overhead local; a primeira indexação inclui carga do modelo.',
                            'Reabertura do armazenamento no mesmo processo; reinício da aplicação é testado separadamente.',
                            'MedCPT usa trechos e cosseno neste experimento, adaptados do uso oficial com títulos/resumos.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--model', default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument('--k', type=int, default=5)
    parser.add_argument('--minimum-score', type=float, default=0.0)
    parser.add_argument('--shadow', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('artifacts/retrieval-comparison.json'))
    args = parser.parse_args()
    raw = args.input.read_bytes()
    fixture = json.loads(raw)
    reranker = None
    if args.shadow:
        from .scientific_search import MedCptCrossEncoderReranker
        reranker = MedCptCrossEncoderReranker()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='unlabelled-retrieval-') as folder:
        report = compare_unlabelled(fixture, ValidatedEmbeddingProvider(args.model), path=folder,
                                   k=args.k, minimum_score=args.minimum_score, reranker=reranker)
    report['input_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'embedding_model': report['embedding_model'],
                      'restart_new_document_embeddings': report['restart_new_document_embeddings']}))


if __name__ == '__main__':
    main()
