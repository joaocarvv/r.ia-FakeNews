import base64
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from fatofake.api import AnalysisJobService, AnalysisJobStatus, SQLiteAnalysisJobStore, create_app
from fatofake.article_ingestion import ArticleFirstAnalysisRunner, ArticleSubmission, ResolvedArticleDocument
from fatofake.document_parsing import ParsedDocument, ParsedPage
from fatofake.gemini_evidence import GeminiEvidenceAnalyzer
from fatofake.input_validation import InputValidationError
from fatofake.library import ArticleLibrary
from fatofake.manual_comparison import compare_documents
from test_api import ImmediateExecutor, RunnerStub
from test_claim_selection import PreparingArticleRunnerStub, prepared_article


def document(pmid='456', text='Participants reported lower pain after treatment.', scope='ABSTRACT_ONLY'):
    return ResolvedArticleDocument(title='Reference study', doi='10.1000/reference', pmid=pmid,
        text=text, sections=(('Results', text),), content_scope=scope,
        source_url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/', publication_types=('Journal Article',))


def submission():
    return ArticleSubmission('456', 'pmid', None, None, None)


class LibraryTests(unittest.TestCase):
    def test_persistence_search_annotations_and_deduplication(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'library.sqlite3'
            library = ArticleLibrary(path)
            first = library.save(submission(), document(), analysis_id='analysis-1')
            library.annotate(first['article_id'], 'Rever conclusão e diabetes', ['revisar'])
            second = library.save(submission(), document(), analysis_id='analysis-2')
            self.assertEqual(first['article_id'], second['article_id'])
            library.close()
            restored = ArticleLibrary(path)
            self.addCleanup(restored.close)
            self.assertEqual(restored.list('diabetes')[0]['notes'], 'Rever conclusão e diabetes')
            self.assertEqual(restored.list('participants')[0]['analysis_ids'], ['analysis-1', 'analysis-2'])
            self.assertEqual(restored.list('something absent'), [])
            self.assertEqual(restored.load(first['article_id'])[1].text, document().text)
            self.assertNotIn('document', restored.list()[0])

    def test_imports_existing_prepared_jobs_without_a_new_source_request(self):
        from fatofake.input_validation import AnalysisInput
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.sqlite3'
            store = SQLiteAnalysisJobStore(path)
            job = store.create(AnalysisInput(claim='Uma alegação válida.'))
            store.transition(job.analysis_id, status=AnalysisJobStatus.RUNNING, progress=10)
            store.transition(job.analysis_id, status=AnalysisJobStatus.AWAITING_CLAIM_SELECTION, progress=40,
                             workflow=prepared_article().to_workflow_payload())
            library = ArticleLibrary(path)
            self.addCleanup(library.close)
            self.assertEqual(library.import_prepared_analyses(), 1)
            self.assertEqual(library.list()[0]['analysis_ids'], [job.analysis_id])
            self.assertEqual(library.import_prepared_analyses(), 0)

    def test_abstract_does_not_overwrite_full_text(self):
        library = ArticleLibrary()
        self.addCleanup(library.close)
        full = document(text='Full article with methods and results.', scope='FULL_TEXT')
        saved = library.save(submission(), full)
        library.save(submission(), document())
        self.assertEqual(library.load(saved['article_id'])[1].text, full.text)

    def test_fts_query_cannot_inject_sql_or_fts_operators(self):
        library = ArticleLibrary()
        self.addCleanup(library.close)
        library.save(submission(), document())
        self.assertEqual(library.list('"; DROP TABLE library_articles; --'), [])
        self.assertEqual(len(library.list()), 1)


class MultiRoundTests(unittest.TestCase):
    def setup_service(self, runner=None, store=None):
        runner = runner or PreparingArticleRunnerStub()
        service = AnalysisJobService(RunnerStub(), article_runner=runner, store=store,
                                     executor=ImmediateExecutor(), result_serializer=lambda result: result)
        self.addCleanup(service.close)
        client = create_app(service).test_client()
        job = client.post('/api/v1/article-analyses', json={'article_reference':'10.1000/example'}).get_json()
        return client, service, job['analysis_id']

    def select(self, client, analysis_id, claim_id):
        return client.post(f'/api/v1/article-analyses/{analysis_id}/claims',
                           json={'claims':[{'claim_id':claim_id, 'text':'Texto válido da alegação.'}]})

    def test_second_round_keeps_first_result_without_reading_source_again(self):
        runner = PreparingArticleRunnerStub()
        client, service, analysis_id = self.setup_service(runner)
        self.assertEqual(self.select(client, analysis_id, 'claim-01').status_code, 202)
        self.assertEqual(self.select(client, analysis_id, 'claim-02').status_code, 202)
        job = service.get(analysis_id)
        self.assertEqual(job.status, AnalysisJobStatus.SUCCEEDED)
        self.assertEqual([item['claim_id'] for item in job.result['claim_analyses']], ['claim-01', 'claim-02'])
        self.assertTrue(all(item['status'] == 'SUCCEEDED' for item in job.result['claim_analyses']))
        light = client.get(f'/api/v1/analyses/{analysis_id}?view=status').get_json()
        self.assertEqual(len(light['claim_progress']), 2)
        self.assertNotIn('result', light)
        self.assertEqual(len(client.get('/api/v1/library/articles').get_json()['articles']), 1)

    def test_each_claim_has_progress_and_failure_does_not_discard_other_claim(self):
        class PartialRunner(PreparingArticleRunnerStub):
            def analyze_prepared(self, prepared, selected_claims=None, depth='QUICK'):
                states.append(service.get(analysis_id).result['claim_analyses'][len(states)]['status'])
                if selected_claims[0].claim_id == 'claim-02':
                    raise RuntimeError('Controlled failure')
                return super().analyze_prepared(prepared, selected_claims, depth)
        states = []
        client, service, analysis_id = self.setup_service(PartialRunner())
        response = client.post(f'/api/v1/article-analyses/{analysis_id}/claims', json={'claims':[
            {'claim_id':'claim-01', 'text':'Texto válido da primeira alegação.'},
            {'claim_id':'claim-02', 'text':'Texto válido da segunda alegação.'},
        ]})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(states, ['RUNNING','RUNNING'])
        job = service.get(analysis_id)
        self.assertEqual([item['status'] for item in job.result['claim_analyses']], ['SUCCEEDED','FAILED'])
        self.assertEqual(job.status, AnalysisJobStatus.SUCCEEDED)

    def test_round_can_resume_after_restart_and_library_links_remain(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.sqlite3'
            client, original, analysis_id = self.setup_service(store=SQLiteAnalysisJobStore(path))
            self.select(client, analysis_id, 'claim-01')
            client2, restored, unused_id = self.setup_service(store=SQLiteAnalysisJobStore(path))
            self.assertEqual(self.select(client2, analysis_id, 'claim-02').status_code, 202)
            self.assertEqual(len(restored.get(analysis_id).result['claim_analyses']), 2)
            saved = restored.library.list()[0]
            self.assertIn(analysis_id, saved['analysis_ids'])
            self.assertIn(unused_id, saved['analysis_ids'])

    def test_manual_references_are_cached_deduplicated_and_target_is_rejected(self):
        client, service, analysis_id = self.setup_service()
        saved = service.library.save(submission(), document())
        prepared = prepared_article()
        manual = service.comparison_documents({'mode':'MANUAL','article_ids':[saved['article_id'],saved['article_id']]}, prepared, 'http://localhost')
        self.assertEqual(len(manual), 1)
        target = service.library.save(prepared.submission, prepared.resolved)
        with self.assertRaisesRegex(InputValidationError, 'alvo'):
            service.comparison_documents({'mode':'MANUAL','article_ids':[target['article_id']]}, prepared, 'http://localhost')
        for payload in ({'mode':'MANUAL'}, {'mode':'WRONG'}, {'mode':'MANUAL','article_ids':'bad'}):
            with self.subTest(payload=payload), self.assertRaises(InputValidationError):
                service.comparison_documents(payload, prepared, 'http://localhost')

    def test_library_source_and_notes_routes(self):
        client, service, analysis_id = self.setup_service()
        saved = client.post('/api/v1/library/articles', json={'analysis_id':analysis_id}).get_json()
        article_id = saved['article_id']
        self.assertEqual(client.patch(f'/api/v1/library/articles/{article_id}', json={'notes':'Uma nota', 'tags':['tema']}).status_code, 200)
        detail = client.get(f'/api/v1/library/articles/{article_id}').get_json()
        self.assertIn('Texto integral', detail['document']['text'])
        self.assertEqual(client.get('/api/v1/library/articles?q=nota').get_json()['articles'][0]['article_id'], article_id)
        self.assertEqual(client.get('/api/v1/library/articles/missing').status_code, 404)
        self.assertEqual(client.post('/api/v1/library/articles', json={'analysis_id':analysis_id, 'article_reference':'456'}).status_code, 422)

    def test_library_accepts_multiple_pdf_documents_and_preserves_pages(self):
        client, service, _analysis_id = self.setup_service()
        parser = Mock()
        parser.parse_pdf.return_value = ParsedDocument(text='PDF sample text.', page_count=1,
            parser_name='stub', used_ocr=False, pages=(ParsedPage(1,'PDF sample text.'),))
        service.article_runner.document_parser = parser
        file = {'name':'sample.pdf', 'mime_type':'application/pdf', 'data_base64':base64.b64encode(b'%PDF-1.7 test').decode()}
        saved = client.post('/api/v1/library/articles', json={'article_file':file})
        self.assertEqual(saved.status_code, 201)
        doc = service.library.get(saved.get_json()['article_id'])['document']
        self.assertEqual(doc['pages'][0]['page_number'], 1)
        article_id = saved.get_json()['article_id']
        original = client.get(f'/api/v1/library/articles/{article_id}/file')
        self.assertEqual(original.status_code, 200)
        self.assertTrue(next(item for item in service.library.list() if item['article_id'] == article_id)['has_original_file'])
        self.assertEqual(original.data, b'%PDF-1.7 test')
        self.assertIn('attachment', original.headers['Content-Disposition'])
        cached_submission, cached_document = service.library.load(article_id)
        service.library.save(cached_submission, cached_document)
        self.assertEqual(service.library.original_file(article_id)[0], b'%PDF-1.7 test')


    def test_user_can_add_claims_and_revisit_them_in_later_rounds(self):
        client, service, analysis_id = self.setup_service()
        payload = {'claims':[{'claim_id':'user-example', 'text':'Uma alegação escrita pelo usuário.', 'source':'USER'}]}
        first = client.post(f'/api/v1/article-analyses/{analysis_id}/claims', json=payload)
        self.assertEqual(first.status_code, 202)
        prepared = service.get(analysis_id).workflow
        claim = next(item for item in prepared['extracted']['claims'] if item['claim_id'] == 'user-example')
        self.assertTrue(claim['user_supplied'])
        self.assertIsNone(claim['quote'])
        second = client.post(f'/api/v1/article-analyses/{analysis_id}/claims', json=payload)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(len(service.get(analysis_id).result['claim_analyses']), 1)

    def test_manual_route_compares_multiple_library_articles_for_multiple_claims(self):
        from fatofake.gemini_evidence import GeminiEvidenceAssessment
        analyzer = Mock(model_name='controlled', assess_methodology=False)
        def assess(claim, docs, **kwargs):
            return tuple(GeminiEvidenceAssessment(
                pmid=doc.pmid, relation='SUPPORTS', confidence=0.8, rationale='Trecho compatível.',
                evidence_quote=doc.passages[0].text, study_design='UNKNOWN', model_name='controlled',
                passage_id=doc.passages[0].passage_id, evidence_section=doc.passages[0].section,
                evidence_page=None, source_url=doc.source_url, content_scope=doc.passages[0].content_scope,
                study_row=None,
            ) for doc in docs)
        analyzer.analyze.side_effect = assess
        evidence = Mock(evidence_analyzer=analyzer, assess_methodology=False, retrieval_settings=None)
        extractor = Mock(gateway=analyzer)
        extractor.extract.return_value = prepared_article().extracted
        resolver = Mock()
        resolver.resolve.return_value = prepared_article().resolved
        runner = ArticleFirstAnalysisRunner(extractor, evidence, resolver, pubmed_only=True)
        client, service, analysis_id = self.setup_service(runner)
        client.application.config['TESTING'] = True
        ids = [service.library.save(submission(), document(pmid))['article_id'] for pmid in ('456','789')]
        response = client.post(f'/api/v1/article-analyses/{analysis_id}/claims', json={
            'claims':[{'claim_id':item.claim_id,'text':item.text} for item in prepared_article().extracted.claims],
            'comparison':{'mode':'MANUAL','article_ids':ids},
        })
        self.assertEqual(response.status_code, 202)
        evidence.analyze.assert_not_called()
        result = service.get(analysis_id).result
        self.assertEqual([item['status'] for item in result['claim_analyses']], ['SUCCEEDED','SUCCEEDED'])
        for item in result['claim_analyses']:
            self.assertEqual(len(item['result']['articles']), 2)
            self.assertEqual(item['result']['search']['mode'], 'MANUAL')
            self.assertIsNone(item['result']['weighted_evidence']['verdict']['certainty_label'])


class ManualComparisonTests(unittest.TestCase):
    def test_comparison_uses_only_chosen_documents_with_verified_citations(self):
        def post(_url, payload):
            results = []
            # Both supplied documents contain the same quoted sentence.
            for pmid in ('456','789'):
                results.append({'pmid':pmid,'relation':'SUPPORTS','confidence':0.8,
                    'rationale':'Trecho compatível.',
                    'evidence_quote':'Participants reported lower pain after treatment.',
                    'study_row':{'population':'Participants','sample_size':'999'}})
            return {'candidates':[{'content':{'parts':[{'text':json.dumps({'assessments':results})}]}}]}
        runner = Mock(retrieval_settings=None)
        runner.evidence_analyzer = GeminiEvidenceAnalyzer('test', post_json=post, assess_methodology=False)
        result = compare_documents(runner, 'Treatment reduces pain.', [('one',document()),('two',document('789'))])
        runner.search_engine.search.assert_not_called()
        self.assertEqual(result['search']['mode'], 'MANUAL')
        self.assertEqual(len(result['articles']), 2)
        self.assertTrue(all(item['assessments'][0]['evidence']['text'] for item in result['articles']))
        self.assertTrue(all(row['sample_size'] is None for row in result['weighted_evidence']['rows']))
        self.assertIsNone(result['weighted_evidence']['verdict']['certainty_label'])
        self.assertIn('escolhidos', result['user_summary']['reading']['summary'])
