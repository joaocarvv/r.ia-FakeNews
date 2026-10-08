import unittest
import json
from unittest.mock import Mock

from fatofake.api import AnalysisJobService, create_app
from fatofake.input_validation import InputValidationError
from fatofake.topic_clustering import PubMedTopicClusterer, TopicClusteringError


class Encoder:
    name = 'controlled'
    def __init__(self):
        self.calls = []
    def encode(self, texts):
        self.calls.append(list(texts))
        return [[1, i + 1, (i + 1) ** 2] for i, _ in enumerate(texts)]


class Gateway:
    model_name = 'controlled-gemini'
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
    def _post_json(self, url, payload):
        self.calls.append((url, payload))
        return json.dumps(self.payload)
    @staticmethod
    def _response_text(response):
        return response


def articles(count=5):
    return [{'pmid': str(i + 1), 'title': f'Biomedical title number {i}'} for i in range(count)]


class TopicClusteringTests(unittest.TestCase):
    def clusterer(self):
        self.encoder = Encoder()
        self.model = Mock()
        self.model.fit_transform.return_value = ([0, 0, 1, 1, -1], None)
        self.model.get_topic.side_effect = lambda topic: [('exercise' if topic == 0 else 'diabetes', .5)]
        return PubMedTopicClusterer(encoder=self.encoder, model_factory=lambda n, d: self.model)

    def test_membership_outliers_projection_and_cache(self):
        clusterer = self.clusterer()
        first = clusterer.cluster(articles())
        self.assertFalse(first['llm_available'])
        self.assertEqual(first['topic_count'], 2)
        self.assertEqual(first['outlier_count'], 1)
        self.assertEqual(first['clusters'][0]['pmids'], ['1', '2'])
        self.assertEqual(first['clusters'][-1]['label'], 'Sem grupo definido')
        self.assertEqual({point['pmid'] for point in first['points']}, {'1','2','3','4','5'})
        first['clusters'].clear()
        second = clusterer.cluster(articles())
        self.assertEqual(len(second['clusters']), 3)
        self.assertTrue(second['cache_hit'])
        self.assertEqual(second['new_document_embeddings'], 0)
        self.assertEqual(len(self.encoder.calls), 1)
        self.model.fit_transform.assert_called_once()
        self.assertTrue(first['edges'])

    def test_prepare_embeds_batches_without_fitting_and_cluster_reuses_them(self):
        clusterer = self.clusterer()
        prepared = clusterer.prepare(articles(2))
        self.assertEqual(prepared['status'], 'prepared')
        self.assertEqual(prepared['new_document_embeddings'], 2)
        self.model.fit_transform.assert_not_called()
        report = clusterer.cluster(articles())
        self.assertEqual(report['new_document_embeddings'], 3)
        self.assertEqual([len(call) for call in self.encoder.calls], [2, 3])

    def test_prepare_accepts_configured_limit_of_one_hundred_articles(self):
        clusterer = self.clusterer()
        prepared = clusterer.prepare(articles(100))
        self.assertEqual(prepared['document_count'], 100)
        self.assertEqual(prepared['new_document_embeddings'], 100)

    def test_all_outliers_use_adaptive_partition(self):
        density = Mock()
        density.fit_transform.return_value = ([-1, -1, -1, -1, -1], None)
        partition = Mock()
        partition.fit_transform.return_value = ([0, 0, 1, 1, 1], None)
        partition.get_topic.side_effect = lambda topic: [('exercise' if topic == 0 else 'diabetes', .5)]
        clusterer = PubMedTopicClusterer(
            encoder=Encoder(),
            model_factory=lambda _count, _dimension, strategy: partition if strategy == 'partition' else density,
        )
        report = clusterer.cluster(articles())
        self.assertTrue(report['fallback_used'])
        self.assertEqual(report['clustering'], 'KMeans adaptive fallback')
        self.assertEqual(report['topic_count'], 2)
        self.assertEqual(report['outlier_count'], 0)
        density.fit_transform.assert_called_once()
        partition.fit_transform.assert_called_once()

    def test_graph_does_not_connect_unrelated_embeddings(self):
        import numpy as np
        documents = (('1', 'First title'), ('2', 'Second title'), ('3', 'Third title'))
        embeddings = np.asarray([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
        self.assertEqual(PubMedTopicClusterer._graph_edges(documents, embeddings, [0, 0, 1]), [])

    def test_llm_summarizes_topics_and_reassigns_outlier(self):
        gateway = Gateway({
            'topics': [
                {'topic_id': 0, 'label': 'Exercício clínico', 'summary': 'Estudos sobre intervenções de exercício em contextos clínicos.'},
                {'topic_id': 1, 'label': 'Diabetes', 'summary': 'Artigos que investigam aspectos relacionados ao diabetes.'},
            ],
            'outlier_assignments': [{'pmid': '5', 'target': '1'}],
            'other_summary': 'Artigos que não apresentaram compatibilidade temática suficiente.',
        })
        clusterer = self.clusterer()
        clusterer.gateway = gateway
        report = clusterer.enrich(articles())
        self.assertTrue(report['llm_enriched'])
        self.assertTrue(report['llm_available'])
        self.assertEqual(report['llm_reassigned_count'], 1)
        self.assertEqual(report['outlier_count'], 0)
        self.assertEqual(report['clusters'][0]['summary'], 'Artigos que investigam aspectos relacionados ao diabetes.')
        self.assertEqual(next(point for point in report['points'] if point['pmid'] == '5')['topic_id'], 1)
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(clusterer.enrich(articles())['enrichment_status'], 'available')
        self.assertEqual(len(gateway.calls), 1)

    def test_llm_can_create_other_group_and_failure_keeps_clusters(self):
        gateway = Gateway({
            'topics': [
                {'topic_id': 0, 'label': 'Tema A', 'summary': 'Artigos biomédicos relacionados ao primeiro tema identificado.'},
                {'topic_id': 1, 'label': 'Tema B', 'summary': 'Artigos biomédicos relacionados ao segundo tema identificado.'},
            ],
            'outlier_assignments': [{'pmid': '5', 'target': 'OTHER'}],
            'other_summary': 'Artigos diversos sem compatibilidade clara com os demais temas.',
        })
        clusterer = self.clusterer()
        clusterer.gateway = gateway
        report = clusterer.enrich(articles())
        other = next(cluster for cluster in report['clusters'] if cluster['label'] == 'Outros')
        self.assertEqual(other['pmids'], ['5'])
        self.assertEqual(report['llm_other_count'], 1)

        broken = self.clusterer()
        broken.gateway = Gateway({'unexpected': True})
        fallback = broken.enrich(articles())
        self.assertEqual(fallback['enrichment_status'], 'unavailable')
        self.assertFalse(fallback['llm_enriched'])
        self.assertEqual(fallback['outlier_count'], 1)

    def test_small_corpus_does_not_load_models(self):
        clusterer = self.clusterer()
        self.assertEqual(clusterer.cluster(articles(3))['status'], 'insufficient_documents')
        self.assertEqual(clusterer.cluster([])['document_count'], 0)
        self.assertEqual(self.encoder.calls, [])

    def test_validation_before_encoding(self):
        clusterer = self.clusterer()
        for payload in (None, {}, articles(101), [{'pmid': 'bad','title': 'title'}],
                        [{'pmid':'1','title': '<'}], [articles()[0],articles()[0]]):
            with self.subTest(payload=str(payload)[:50]), self.assertRaises(InputValidationError):
                clusterer.cluster(payload)
        self.assertEqual(self.encoder.calls, [])

    def test_model_failure_is_sanitized(self):
        clusterer = self.clusterer()
        self.model.fit_transform.side_effect = RuntimeError('sensitive internals')
        with self.assertRaises(TopicClusteringError) as raised:
            clusterer.cluster(articles())
        self.assertNotIn('sensitive internals', str(raised.exception))

    def test_api_contract(self):
        service = AnalysisJobService(Mock())
        self.addCleanup(service.close)
        client = create_app(service, topic_clusterer=self.clusterer()).test_client()
        self.assertEqual(client.post('/api/v1/pubmed-clusters', json={'articles':articles()}).status_code, 200)
        self.assertEqual(client.post('/api/v1/pubmed-clusters', json={'mode':'prepare', 'articles':articles(2)}).status_code, 200)
        self.assertEqual(client.post('/api/v1/pubmed-clusters', json={'mode':'enrich', 'articles':articles()}).status_code, 200)
        self.assertEqual(client.post('/api/v1/pubmed-clusters', json={'mode':'invalid', 'articles':articles()}).status_code, 400)
        self.assertEqual(client.post('/api/v1/pubmed-clusters', json={}).status_code, 400)
        self.assertEqual(client.post('/api/v1/pubmed-clusters', data='x').status_code, 415)
        self.model.fit_transform.side_effect = RuntimeError('failure')
        changed = articles(); changed[0]['title'] = 'Different title'
        self.assertEqual(client.post('/api/v1/pubmed-clusters', json={'articles':changed}).status_code, 503)
        unavailable = create_app(service).test_client()
        self.assertEqual(unavailable.post('/api/v1/pubmed-clusters', json={'articles':articles()}).status_code, 503)
