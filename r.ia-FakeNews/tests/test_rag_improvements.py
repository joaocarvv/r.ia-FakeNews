import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from fatofake.retrieval_backend import MemoryChunkStore, RetrievalSettings
from fatofake.retrieval_comparison import compare_unlabelled
from fatofake.retrieval_evaluation import FixtureEncoder
from fatofake.scientific_search import expand_scientific_queries, biomedical_shadow_ranking
from fatofake.semantic_retrieval import SemanticIndex, ValidatedEmbeddingProvider
from fatofake.federated_search import uses_pubmed_syntax
from test_scientific_search import work
from test_vector_contracts import scientific_chunk


class RagImprovementsTests(unittest.TestCase):
    def test_mesh_uses_specific_concept_and_complete_field_clauses(self):
        queries = expand_scientific_queries('Coffee and prostate cancer', ['coffee prostate cancer'])
        query = next(q.query for q in queries if q.strategy == 'MESH_CANDIDATES')
        self.assertIn('"Prostatic Neoplasms"[MeSH Terms]', query)
        self.assertNotIn('"Neoplasms"[MeSH Terms]', query)
        self.assertEqual(query.count('('), query.count(')'))
        self.assertEqual(query.count('['), query.count(']'))
        self.assertTrue(uses_pubmed_syntax('coffee[Title/Abstract]'))
        self.assertFalse(any(q.strategy == 'MESH_CANDIDATES' for q in
                             expand_scientific_queries('coffeemaker', ['coffeemaker'])))

    def test_long_mesh_expression_is_not_cut_mid_clause(self):
        query = next(q.query for q in expand_scientific_queries(
            'coffee prostate cancer hypertension rhodopsin osmotic pressure hydrostatic pressure clinical trial', [])
                     if q.strategy == 'MESH_CANDIDATES')
        self.assertGreater(len(query), 300)
        self.assertEqual(query.count('('), query.count(')'))
        self.assertTrue(query.endswith(')'))

    def test_shadow_preserves_input_and_records_rank_change(self):
        works = (work('First', '1'), work('Second', '2'))
        reranker = Mock(name='reranker')
        reranker.name = 'controlled'
        reranker.score.return_value = [0.1, 0.9]
        result = biomedical_shadow_ranking('query', works, reranker)
        self.assertEqual([r['shadow_rank'] for r in result['ranking']], [2, 1])
        self.assertEqual([w.pmid for w in works], ['1', '2'])
        reranker.score.return_value = [float('nan'), 1]
        with self.assertRaises(RuntimeError):
            biomedical_shadow_ranking('query', works, reranker)

    def test_asymmetric_encoder_roles_are_used_and_documents_reused(self):
        encoder = Mock()
        encoder.name = 'dual-test'
        encoder.dimension = 2
        encoder.encode_documents.return_value = [[1, 0]]
        encoder.encode_queries.return_value = [[1, 0]]
        store = MemoryChunkStore(encoder=encoder)
        chunks = [scientific_chunk()]
        for query in ('claim one', 'claim two'):
            store.index(chunks).search(query)
        encoder.encode_documents.assert_called_once()
        self.assertEqual(encoder.encode_queries.call_count, 2)
        encoder.encode.assert_not_called()

    def test_unlabelled_comparison_has_no_relevance_metrics_and_reuses_after_restart(self):
        fixture = json.loads(Path('tests/fixtures/retrieval/golden.json').read_text())
        for case in fixture['cases']:
            case.pop('relevant_pmids')
        with tempfile.TemporaryDirectory() as path:
            report = compare_unlabelled(fixture, FixtureEncoder(fixture), path=path, k=2)
        self.assertIsNone(report['relevance_metrics'])
        self.assertEqual(report['initial_new_document_embeddings'], 2)
        self.assertEqual(report['restart_new_document_embeddings'], 0)
        self.assertEqual(report['document_encodes'], 2)
        runs = [r for r in report['runs'] if 'method' in r]
        self.assertEqual(len(runs), 27)
        self.assertTrue(all(r['same_order_as_cold'] for r in runs))

    def test_runner_shadow_success_and_failure_leave_baseline_articles_unchanged(self):
        from fatofake.federated_search import FederatedSearchEngine
        from fatofake.retrieval_preview import RetrievalPreviewRunner
        from test_retrieval_preview import ProviderStub
        def run(enabled, fail=False):
            scorer = Mock()
            scorer.name = 'controlled'
            scorer.score.side_effect = (RuntimeError('private detail') if fail else
                                        lambda query, documents: list(range(len(documents))))
            runner = RetrievalPreviewRunner(FederatedSearchEngine((ProviderStub('PubMed'),)),
                retrieval_settings=RetrievalSettings(medcpt_shadow_enabled=enabled), shadow_reranker=scorer)
            return runner.analyze('Water affects rhodopsin activation.')
        baseline = run(False)
        shadow = run(True)
        failed = run(True, True)
        self.assertEqual(baseline['articles'], shadow['articles'])
        self.assertEqual(baseline['articles'], failed['articles'])
        self.assertEqual(shadow['search']['medcpt_shadow']['status'], 'available')
        self.assertEqual(failed['search']['medcpt_shadow']['status'], 'unavailable')
        self.assertNotIn('private detail', json.dumps(failed))

    def test_library_manual_claims_and_vectors_survive_application_restart(self):
        from fatofake.api import AnalysisJobService, SQLiteAnalysisJobStore, create_app
        from fatofake.article_ingestion import ArticleFirstAnalysisRunner
        from fatofake.gemini_evidence import GeminiEvidenceAnalyzer
        from fatofake.qdrant_retrieval import QdrantChunkStore
        from fatofake.retrieval_preview import RetrievalPreviewRunner
        from test_api import ImmediateExecutor, RunnerStub
        from test_claim_selection import prepared_article
        from test_library_workflow import submission, document
        from test_qdrant_retrieval import Encoder
        def post(_url, payload):
            prompt = payload['contents'][0]['parts'][0]['text']
            docs = json.loads(prompt.split('BEGIN_UNTRUSTED_EVIDENCE_JSON\n', 1)[1].split('\nEND_UNTRUSTED_EVIDENCE_JSON', 1)[0])
            return {'candidates':[{'content':{'parts':[{'text':json.dumps({'assessments':[
                {'pmid':doc['pmid'], 'relation':'SUPPORTS', 'confidence':.8,
                 'passage_id':doc['passages'][0]['passage_id'],
                 'evidence_quote':doc['passages'][0]['text']} for doc in docs]})}]}}]}
        with tempfile.TemporaryDirectory() as path:
            def start():
                encoder = Encoder()
                vectors = QdrantChunkStore(path=str(Path(path)/'vectors'), encoder=encoder)
                evidence = RetrievalPreviewRunner(Mock(providers=[]), vector_store=vectors,
                    retrieval_settings=RetrievalSettings(backend='qdrant', hybrid_enabled=True),
                    evidence_analyzer=GeminiEvidenceAnalyzer('controlled', post_json=post, assess_methodology=False))
                extractor = Mock(gateway=evidence.evidence_analyzer)
                extractor.extract.return_value = prepared_article().extracted
                resolver = Mock()
                resolver.resolve.return_value = prepared_article().resolved
                runner = ArticleFirstAnalysisRunner(extractor, evidence, resolver, pubmed_only=True)
                service = AnalysisJobService(RunnerStub(), article_runner=runner,
                    store=SQLiteAnalysisJobStore(Path(path)/'jobs.sqlite3'), executor=ImmediateExecutor(),
                    result_serializer=lambda result:result)
                return service, create_app(service).test_client(), vectors, encoder, resolver
            service, client, vectors, encoder, resolver = start()
            try:
                analysis_id = client.post('/api/v1/article-analyses', json={'article_reference':'10.1000/example'}).json['analysis_id']
                ids = [service.library.save(submission(), document(pmid))['article_id'] for pmid in ('456','789')]
                def select(client, claim_id):
                    return client.post(f'/api/v1/article-analyses/{analysis_id}/claims', json={
                        'claims':[{'claim_id':claim_id, 'text':'Treatment reduces pain.'}],
                        'comparison':{'mode':'MANUAL','article_ids':ids}})
                response = select(client, 'claim-01')
                self.assertEqual(response.status_code, 202, response.json)
                self.assertEqual(vectors.metadata().point_count, 2)
            finally:
                service.close()
                vectors.close()
            restored, client, vectors, encoder, resolver = start()
            try:
                self.assertEqual(select(client, 'claim-02').status_code, 202)
                result = client.get(f'/api/v1/analyses/{analysis_id}').json['result']
                self.assertEqual(len(result['claim_analyses']), 2)
                for item in result['claim_analyses']:
                    self.assertEqual(item['status'], 'SUCCEEDED')
                    self.assertEqual(len(item['result']['articles']), 2)
                self.assertEqual(vectors.metadata().point_count, 2)
                self.assertTrue(all(call == ['Treatment reduces pain.'] for call in encoder.calls))
                self.assertEqual(len(encoder.calls), 2)
                resolver.resolve.assert_not_called()
            finally:
                restored.close()
                vectors.close()

    def test_shadow_config_is_opt_in_and_validated(self):
        self.assertFalse(RetrievalSettings.from_mapping({}).medcpt_shadow_enabled)
        self.assertTrue(RetrievalSettings.from_mapping({'MEDCPT_SHADOW_ENABLED':'true'}).medcpt_shadow_enabled)
        for mapping in ({'MEDCPT_SHADOW_ENABLED':'yes'}, {'MEDCPT_SHADOW_TOP_N':'0'}):
            with self.assertRaises(ValueError):
                RetrievalSettings.from_mapping(mapping)
