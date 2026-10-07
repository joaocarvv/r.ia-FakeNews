import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fatofake.reference_comparison import (parse_pmc, parse_pubmed, compare_references,
                                          analysis_articles, ReferenceComparisonService)
from fatofake.pmc import PmcClient, ContentRetrievalError
from fatofake.api import AnalysisJobService, AnalysisJobStatus, SQLiteAnalysisJobStore, create_app
from fatofake.input_validation import validate_analysis_input

PUBMED = b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID></MedlineCitation><PubmedData>
<ArticleIdList><ArticleId IdType="pmc">PMC1</ArticleId></ArticleIdList>
<ReferenceList><Reference><Citation>Study two</Citation><ArticleIdList><ArticleId IdType="pubmed">2</ArticleId><ArticleId IdType="doi">10.1000/B</ArticleId></ArticleIdList></Reference></ReferenceList>
</PubmedData></PubmedArticle><PubmedArticle><MedlineCitation><PMID>2</PMID></MedlineCitation><PubmedData/></PubmedArticle></PubmedArticleSet>'''
PMC = b'''<pmc-articleset><article><front><article-meta><article-id pub-id-type="pmc">1</article-id></article-meta></front><body><p>Prior study <xref ref-type="bibr" rid="r1">1</xref> reported this.</p></body><back><ref-list><ref id="r1"><label>1</label><element-citation><article-title>Study two</article-title><pub-id pub-id-type="doi">https://doi.org/10.1000/b</pub-id><year>2024</year></element-citation></ref></ref-list></back></article></pmc-articleset>'''
ARTICLES = [{'node_id':'a','pmid':'1','title':'A'}, {'node_id':'b','pmid':'2','doi':'10.1000/B','title':'B'}]

class ReferenceTests(unittest.TestCase):
    def test_jats_direction_and_literal_context(self):
        pmc = parse_pmc(PMC)['PMC1']
        self.assertIn('Prior study', pmc['references'][0]['contexts'][0])
        result = compare_references(ARTICLES, {'a':pmc})
        self.assertEqual([(e['from'],e['to']) for e in result['edges']], [('a','b')])
        self.assertTrue(result['edges'][0]['has_in_text_context'])
        self.assertIsNone(result['pairs'][0]['shared_count'])
        self.assertEqual(result['status'], 'partial')

    def test_shared_identifiers_and_no_title_inference(self):
        ref = parse_pubmed(PUBMED)['1']
        alias = parse_pmc(PMC)['PMC1']
        report = compare_references(ARTICLES, {'a':ref,'b':alias})
        self.assertEqual(report['pairs'][0]['shared_count'],1)
        self.assertEqual(report['pairs'][0]['jaccard_identified'],1)
        self.assertEqual(len(report['edges']),1) # self reference excluded
        bare = {'status':'available','references':[{'identifiers':[], 'title':'B', 'contexts':[]}]}
        self.assertEqual(compare_references(ARTICLES, {'a':bare})['edges'],[])

    def test_available_empty_differs_from_missing(self):
        empty = {'status':'available','references':[]}
        report = compare_references(ARTICLES, {'a':empty,'b':empty})
        self.assertTrue(report['pairs'][0]['comparable'])
        self.assertEqual(report['pairs'][0]['shared_count'],0)
        self.assertIsNone(report['pairs'][0]['jaccard_identified'])
        self.assertEqual(parse_pubmed(PUBMED)['2']['status'],'unavailable')

    def test_batches_and_discovers_pmc_from_pubmed(self):
        calls=[]
        def fetch(url, params):
            calls.append(dict(params)); return PUBMED if params['db']=='pubmed' else PMC
        service = ReferenceComparisonService(PmcClient(fetch_xml=fetch))
        report = service.compare(ARTICLES)
        self.assertEqual([c['db'] for c in calls], ['pubmed','pmc'])
        self.assertEqual(calls[1]['id'],'PMC1')
        self.assertEqual(report['nodes'][0]['pmcid'],'PMC1')
        self.assertTrue(report['edges'][0]['has_in_text_context'])
        self.assertEqual(report['fingerprint'], service.fingerprint(ARTICLES))

    def test_doi_conversion_matches_explicit_identifier(self):
        client=PmcClient(fetch_xml=lambda u,p: PUBMED if p['db']=='pubmed' else PMC,
                         fetch_json=lambda u,p:{'records':[{'doi':'10.1000/a','pmid':'1','pmcid':'PMC1'}]})
        report=ReferenceComparisonService(client).compare([{'node_id':'a','doi':'10.1000/A','title':'A'}])
        self.assertEqual(report['nodes'][0]['pmid'],'1')
        self.assertEqual(report['available_bibliographies'],1)

    def test_network_failure_is_partial_not_no_references(self):
        client=PmcClient(fetch_xml=Mock(side_effect=ContentRetrievalError('secret')))
        report=ReferenceComparisonService(client).compare(ARTICLES)
        self.assertEqual(report['available_bibliographies'],0)
        self.assertIsNone(report['pairs'][0]['shared_count'])
        self.assertNotIn('secret', str(report))

    def test_api_selection_cache_and_sqlite_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SQLiteAnalysisJobStore(Path(directory)/'jobs.db')
            job=store.create(validate_analysis_input('Example claim'))
            store.transition(job.analysis_id,status=AnalysisJobStatus.RUNNING,progress=10)
            root={'claim_analyses':[{'claim_id':'c1','status':'SUCCEEDED','result':{'articles':ARTICLES}},
                                    {'claim_id':'c2','status':'SUCCEEDED','result':{'articles':[]}}]}
            store.transition(job.analysis_id,status=AnalysisJobStatus.SUCCEEDED,progress=100,result=root)
            runner=Mock()
            service=AnalysisJobService(runner,store=store)
            comparer=ReferenceComparisonService(PmcClient(fetch_xml=lambda u,p:PUBMED if p['db']=='pubmed' else PMC))
            comparer.compare=Mock(wraps=comparer.compare)
            client=create_app(service,reference_comparer=comparer).test_client()
            url=f'/api/v1/analyses/{job.analysis_id}/references'
            self.assertEqual(client.post(url,json={}).status_code,400)
            self.assertEqual(client.post(url,json={'claim_id':'foreign'}).status_code,400)
            self.assertEqual(client.post(url,json={'claim_id':[]}).status_code,400)
            first=client.post(url,json={'claim_id':'c1'})
            self.assertEqual(first.status_code,200,first.json)
            self.assertFalse(first.json['cache_hit'])
            self.assertTrue(client.post(url,json={'claim_id':'c1'}).json['cache_hit'])
            self.assertEqual(comparer.compare.call_count,1)
            self.assertEqual(client.post(url,json={'claim_id':'c1','refresh':True}).status_code,200)
            self.assertEqual(comparer.compare.call_count,2)
            runner.analyze.assert_not_called()
            self.assertEqual(client.post(url,data='invalid').status_code,415)
            self.assertEqual(client.post('/api/v1/analyses/unknown/references',json={}).status_code,404)
            reopened=SQLiteAnalysisJobStore(Path(directory)/'jobs.db').get(job.analysis_id)
            self.assertIn('reference_comparison',reopened.result['claim_analyses'][0]['result'])
            self.assertNotIn('reference_comparison',reopened.result['claim_analyses'][1]['result'])
            service.close()

if __name__ == '__main__': unittest.main()
