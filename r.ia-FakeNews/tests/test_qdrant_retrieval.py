import tempfile
import unittest
from dataclasses import replace
from unittest.mock import Mock

from fatofake.chunking import EvidenceChunk
from fatofake.qdrant_retrieval import QdrantChunkStore
from fatofake.retrieval import RetrievalError
from fatofake.vector_store import ChunkScope, VectorStoreError
from test_vector_contracts import scientific_chunk
from fatofake.pmc import ArticleContent, ContentSection
from fatofake.retrieval_preview import select_evidence_passages


class Encoder:
    name = 'test-encoder'
    def __init__(self):
        self.calls = []
    def encode(self, texts):
        self.calls.append(list(texts))
        return [[1.0, float('beta' in text)] for text in texts]


def chunk(text='alpha', pmid='1', page=3):
    return EvidenceChunk(f'{pmid}:{text}', pmid, None, None, 'PDF',
                         f'https://example.org/{pmid}', 'Resultados', 0, 0,
                         0, 1, text, page)


class QdrantPersistenceTests(unittest.TestCase):
    def test_restart_reuses_vectors_and_retains_provenance(self):
        with tempfile.TemporaryDirectory() as path:
            original = chunk()
            encoder = Encoder()
            store = QdrantChunkStore(path=path, encoder=encoder)
            result = store.index([original]).search('consulta')
            self.assertEqual(result[0].chunk, original)
            points, _ = store.client.scroll(store.collection, with_payload=True)
            self.assertEqual(points[0].payload['page_number'], 3)
            self.assertEqual(points[0].payload['source_url'], original.source_url)
            self.assertCountEqual(encoder.calls, [['consulta'], ['alpha']])
            store.close()
            restarted_encoder = Encoder()
            restarted = QdrantChunkStore(path=path, encoder=restarted_encoder)
            try:
                self.assertEqual(restarted.index([original]).search('outra')[0].chunk, original)
                self.assertEqual(restarted_encoder.calls, [['outra']])
            finally:
                restarted.close()

    def test_only_authorized_chunks_are_returned(self):
        with tempfile.TemporaryDirectory() as path:
            store = QdrantChunkStore(path=path, encoder=Encoder())
            try:
                store.index([chunk('beta', '2')]).search('beta')
                allowed = chunk('alpha', '1')
                results = store.index([allowed]).search('beta', top_k=10)
                self.assertEqual([item.chunk for item in results], [allowed])
            finally:
                store.close()

    def test_provenance_and_model_revision_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as path:
            encoder = Encoder()
            store = QdrantChunkStore(path=path, encoder=encoder)
            try:
                store.index([chunk()]).search('q')
                changed = replace(chunk(), page_number=7)
                self.assertEqual(store.index([changed]).search('q')[0].chunk.page_number, 7)
                self.assertEqual(store.client.count(store.collection).count, 2)
                revised = QdrantChunkStore(client=store.client, encoder=encoder, revision='v2')
                revised.index([chunk()]).search('q')
                self.assertNotEqual(revised.collection, store.collection)
                self.assertEqual(encoder.calls.count(['alpha']), 3)
            finally:
                store.close()

    def test_dimension_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as path:
            store = QdrantChunkStore(path=path, encoder=Encoder())
            try:
                store.index([chunk()]).search('q')
                store.encoder._encoder.encode = lambda texts: [[1, 2, 3] for text in texts]
                with self.assertRaises(RetrievalError):
                    store.index([chunk()]).search('q')
            finally:
                store.close()

    def test_pipeline_reports_vector_failure_unless_fallback_is_explicit(self):
        content = ArticleContent('1', None, None, None, 'alpha beta',
                                 (ContentSection('Resultados', 'alpha beta'),),
                                 'FULL_TEXT', 'https://example.org/1', 'https://example.org/1')
        failing = Mock()
        failing.index.side_effect = RuntimeError('unavailable')
        lexical = select_evidence_passages(content, 'alpha', '1')
        with self.assertRaises(VectorStoreError):
            select_evidence_passages(content, 'alpha', '1', vector_store=failing)
        recovered = select_evidence_passages(content, 'alpha', '1', vector_store=failing, failure_mode='bm25')
        self.assertEqual([p.text for p in recovered], [p.text for p in lexical])
        self.assertIn('VECTOR_STORE_FAILURE_MODE=bm25', recovered[0].retrieval_notice)

    def test_real_hybrid_path_preserves_source_passages(self):
        with tempfile.TemporaryDirectory() as path:
            store = QdrantChunkStore(path=path, encoder=Encoder())
            content = ArticleContent('1', None, None, None, 'alpha beta',
                                     (ContentSection('Resultados', 'alpha beta', 4),),
                                     'FULL_TEXT', 'https://example.org/1', 'https://example.org/1')
            try:
                passages = select_evidence_passages(content, 'beta', '1', vector_store=store)
                self.assertEqual(passages[0].text, 'alpha beta')
                self.assertEqual(passages[0].page_number, 4)
                self.assertEqual(store.client.count(store.collection).count, 1)
            finally:
                store.close()


class QdrantBackendContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.encoder = Encoder()
        self.store = QdrantChunkStore(path=self.directory.name, encoder=self.encoder)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.store.close)

    def test_upsert_idempotence_and_metadata(self):
        original = scientific_chunk()
        self.assertEqual(self.store.upsert([original]), 1)
        self.assertEqual(self.store.upsert([original]), 0)
        metadata = self.store.metadata()
        self.assertEqual(metadata.point_count, 1)
        self.assertEqual(metadata.embedding_dimension, 2)
        self.assertEqual(metadata.embedding_model, 'test-encoder')
        self.assertTrue(self.store.health_check())
        result = self.store.search('consulta', scope=ChunkScope(chunk_ids=(original.chunk_id,)))
        self.assertEqual(result[0].chunk, original)
        self.assertIn('β-catenina', result[0].chunk.text)

    def test_scientific_filters_are_intersections(self):
        original = scientific_chunk()
        other = replace(original, chunk_id='another', pmid='999', pmcid='PMC999', doi='10.1000/other')
        self.store.upsert([original, other])
        for scope in (ChunkScope(pmids=('123',)), ChunkScope(pmcids=('PMC123',)),
                      ChunkScope(dois=('10.1000/test',)), ChunkScope(chunk_ids=(original.chunk_id,)),
                      ChunkScope(pmids=('123',), pmcids=('PMC123',), dois=('10.1000/test',),
                                 source_kinds=('PMC_FULL_TEXT',), content_scopes=('PMC_FULL_TEXT',),
                                 collection=self.store.collection)):
            with self.subTest(scope=scope):
                result = self.store.search('consulta', scope=scope)
                self.assertEqual([item.chunk for item in result], [original])
        self.assertEqual(self.store.search('consulta', scope=ChunkScope(pmids=('123',), dois=('invalid',))), ())
        self.assertEqual(self.store.search('consulta', scope=ChunkScope(chunk_ids=())), ())
        with self.assertRaises(VectorStoreError):
            self.store.search('consulta', scope=ChunkScope())
        with self.assertRaises(VectorStoreError):
            self.store.search('consulta', scope=ChunkScope(pmids=('123',), collection='foreign'))

    def test_scoped_invalidation_retains_other_article(self):
        original = scientific_chunk()
        other = replace(original, pmid='999', chunk_id='other')
        self.store.upsert([original, other])
        self.store.invalidate(ChunkScope(pmids=('123',)))
        self.assertEqual(self.store.metadata().point_count, 1)
        self.assertEqual(self.store.search('consulta', scope=ChunkScope(pmids=('999',)))[0].chunk, other)
        self.assertEqual(self.store.upsert([original]), 1)

    def test_corrupt_payload_is_explicitly_rejected(self):
        original = scientific_chunk()
        self.store.upsert([original])
        self.store.client.set_payload(self.store.collection, payload={'embedding_model': 'foreign'},
                                      points=[self.store._point_id(original)])
        with self.assertRaises(VectorStoreError):
            self.store.upsert([original])
        with self.assertRaises(VectorStoreError):
            self.store.search('q', scope=ChunkScope(pmids=('123',)))

    def test_bad_vectors_never_get_persisted(self):
        for bad in ([0, 0], [float('inf'), 1], [float('nan'), 1]):
            with self.subTest(bad=bad):
                encoder = Encoder()
                encoder.encode = lambda texts: [bad for _ in texts]
                store = QdrantChunkStore(client=self.store.client, encoder=encoder, revision=str(bad))
                with self.assertRaises(VectorStoreError):
                    store.upsert([scientific_chunk()])
                self.assertFalse(self.store.client.collection_exists(store.collection))

    def test_changed_model_uses_another_collection(self):
        self.store.upsert([scientific_chunk()])
        encoder = Encoder()
        encoder.name = 'another-model'
        different = QdrantChunkStore(client=self.store.client, encoder=encoder)
        self.assertNotEqual(different.collection, self.store.collection)
        self.assertEqual(different.upsert([scientific_chunk()]), 1)

    def test_unavailable_client_is_explicit_and_secret_safe(self):
        failing = Mock()
        failing.get_collections.side_effect = RuntimeError('sensitive-test-token')
        store = QdrantChunkStore(client=failing, encoder=Encoder())
        with self.assertLogs('fatofake.qdrant_retrieval', level='ERROR') as logs:
            with self.assertRaisesRegex(VectorStoreError, 'QDRANT_URL/QDRANT_PATH') as caught:
                store.health_check()
        self.assertNotIn('sensitive-test-token', str(caught.exception))
        self.assertNotIn('sensitive-test-token', '\n'.join(logs.output))

    def test_out_of_scope_server_response_is_rejected(self):
        from types import SimpleNamespace
        from fatofake.vector_store import chunk_to_payload
        original = scientific_chunk()
        other = replace(original, chunk_id='other', pmid='999')
        self.store.upsert([original])
        result = SimpleNamespace(points=[SimpleNamespace(id=self.store._point_id(other), score=1.0,
            payload=chunk_to_payload(other, model='test-encoder', dimension=2, revision='v1'))])
        with unittest.mock.patch.object(self.store.client, 'query_points', return_value=result):
            with self.assertRaisesRegex(VectorStoreError, 'fora do escopo'):
                self.store.index([original]).search('q')

    def test_structured_logs_include_ids_and_counts_without_document_text(self):
        original = scientific_chunk()
        with self.assertLogs('fatofake.qdrant_retrieval', level='INFO') as captured:
            self.store.index([original]).search('consulta')
        fields = [record.structured_fields for record in captured.records]
        self.assertTrue(any(item.get('indexed_count') == 1 for item in fields))
        search = next(item for item in fields if item['event'] == 'vector.search')
        self.assertEqual(search['returned_chunk_ids'], [original.chunk_id])
        self.assertEqual(search['embedding_dimension'], 2)
        self.assertNotIn(original.text, str(fields))

    def test_explicit_model_mismatch_is_not_overridden(self):
        with self.assertRaisesRegex(VectorStoreError, 'EMBEDDING_MODEL'):
            QdrantChunkStore(client=self.store.client, encoder=Encoder(), model_name='configured-model')

    def test_search_before_indexing_is_explicitly_rejected(self):
        with self.assertRaisesRegex(VectorStoreError, 'Collection ausente'):
            self.store.search('q', scope=ChunkScope(pmids=('123',)))
        self.assertFalse(self.store.client.collection_exists(self.store.collection))

    def test_concurrent_claims_upsert_document_once(self):
        from concurrent.futures import ThreadPoolExecutor
        original = scientific_chunk()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: self.store.index([original]).search('q'), range(3)))
        self.assertEqual(self.store.metadata().point_count, 1)
        self.assertEqual(self.encoder.calls.count([original.text]), 1)
        self.assertTrue(all(result[0].chunk == original for result in results))

    def test_min_score_boundary_matches_memory_inclusive_threshold(self):
        original = scientific_chunk()
        self.store.upsert([original])
        self.encoder.encode = lambda texts: [[0, 1] for _ in texts]
        self.assertEqual(len(self.store.index([original]).search('q', minimum_score=0)), 1)
        self.assertEqual(self.store.index([original]).search('q', minimum_score=.1), ())
