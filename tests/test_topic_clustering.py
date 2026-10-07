import unittest
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
        self.assertEqual(client.post('/api/v1/pubmed-clusters', json={}).status_code, 400)
        self.assertEqual(client.post('/api/v1/pubmed-clusters', data='x').status_code, 415)
        self.model.fit_transform.side_effect = RuntimeError('failure')
        changed = articles(); changed[0]['title'] = 'Different title'
        self.assertEqual(client.post('/api/v1/pubmed-clusters', json={'articles':changed}).status_code, 503)
        unavailable = create_app(service).test_client()
        self.assertEqual(unavailable.post('/api/v1/pubmed-clusters', json={'articles':articles()}).status_code, 503)
