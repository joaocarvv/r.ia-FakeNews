import unittest
from dataclasses import replace
from unittest.mock import Mock

from fatofake.hybrid_retrieval import HybridRetrievedChunk
from fatofake.retrieval import Bm25Index
from fatofake.retrieval_backend import MemoryChunkStore, RetrievalSettings, retrieve_ranked_chunks
from fatofake.vector_store import ChunkScope, VectorStoreError
from test_vector_contracts import scientific_chunk
from test_qdrant_retrieval import Encoder


class RetrievalBackendTests(unittest.TestCase):
    def test_defaults_preserve_web_bm25(self):
        settings = RetrievalSettings.from_mapping({})
        self.assertEqual(settings.backend, 'memory')
        self.assertFalse(settings.hybrid_enabled)
        chunks = [scientific_chunk()]
        result = retrieve_ranked_chunks(chunks, 'intervenção')
        self.assertEqual(result.results, Bm25Index(chunks).search('intervenção', top_k=8))
        self.assertEqual(result.backend, 'BM25')

    def test_hybrid_memory_keeps_rrf_contributions(self):
        chunks = [scientific_chunk()]
        result = retrieve_ranked_chunks(chunks, 'intervenção', backend=MemoryChunkStore(encoder=Encoder()))
        first = result.results[0]
        self.assertIsInstance(first, HybridRetrievedChunk)
        self.assertEqual(first.lexical_rank, 1)
        self.assertEqual(first.semantic_rank, 1)
        self.assertAlmostEqual(first.score, first.lexical_contribution + first.semantic_contribution)
        self.assertEqual(first.chunk, chunks[0])

    def test_scope_applies_to_bm25_and_semantic(self):
        original = scientific_chunk()
        foreign = replace(original, pmid='999', chunk_id='foreign')
        for backend in (None, MemoryChunkStore(encoder=Encoder())):
            result = retrieve_ranked_chunks([original, foreign], 'intervenção', backend=backend,
                                             scope=ChunkScope(pmids=('123',)))
            self.assertEqual([item.chunk for item in result.results], [original])
            empty = retrieve_ranked_chunks([original, foreign], 'intervenção', backend=backend,
                                            scope=ChunkScope(chunk_ids=()))
            self.assertEqual(empty.results, ())

    def test_failure_is_explicit_by_default_and_fallback_is_marked(self):
        backend = Mock(backend='qdrant')
        backend.index.side_effect = RuntimeError('sensitive-test-token')
        with self.assertRaises(VectorStoreError) as raised:
            retrieve_ranked_chunks([scientific_chunk()], 'q', backend=backend)
        self.assertNotIn('sensitive-test-token', str(raised.exception))
        fallback = retrieve_ranked_chunks([scientific_chunk()], 'intervenção', backend=backend,
                                          failure_mode='bm25')
        self.assertEqual(fallback.backend, 'BM25')
        self.assertIn('VECTOR_STORE_FAILURE_MODE=bm25', fallback.notice)

    def test_configuration_validation(self):
        for mapping in ({'VECTOR_STORE_BACKEND': 'unknown'}, {'VECTOR_TOP_K': 'zero'},
                        {'VECTOR_TOP_K': '0'}, {'VECTOR_MIN_SCORE': 'nan'},
                        {'VECTOR_MIN_SCORE': '2'}, {'HYBRID_RETRIEVAL_ENABLED': 'yes'},
                        {'QDRANT_TIMEOUT': '-1'}, {'VECTOR_STORE_FAILURE_MODE': 'silent'}):
            with self.subTest(mapping=mapping), self.assertRaises(VectorStoreError):
                RetrievalSettings.from_mapping(mapping)
        chosen = RetrievalSettings.from_mapping({'VECTOR_STORE_BACKEND': 'qdrant',
                                                  'HYBRID_RETRIEVAL_ENABLED': 'true'})
        self.assertEqual(chosen.backend, 'qdrant')
        self.assertTrue(chosen.hybrid_enabled)

    def test_minimum_score_changes_only_semantic_candidates(self):
        class OppositeEncoder:
            name = 'opposite'
            def encode(self, texts):
                return [[-1, 0] if text == 'query' else [1, 0] for text in texts]
        result = retrieve_ranked_chunks([scientific_chunk()], 'query', minimum_score=0,
                                         backend=MemoryChunkStore(encoder=OppositeEncoder()))
        # Nenhuma contribuição semântica abaixo do limiar; BM25/RRF preserva seu ranking.
        self.assertTrue(all(item.semantic_rank is None for item in result.results))
