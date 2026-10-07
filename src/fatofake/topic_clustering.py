"""BERTopic sobre títulos de uma página PubMed, sem alterar sua ordenação."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import logging
import re
from threading import RLock
from time import perf_counter
from typing import Callable

from .input_validation import InputValidationError
from .semantic_retrieval import DEFAULT_EMBEDDING_MODEL, ValidatedEmbeddingProvider

logger = logging.getLogger(__name__)


class TopicClusteringError(RuntimeError):
    pass


def validate_articles(articles):
    if not isinstance(articles, list) or len(articles) > 100:
        raise InputValidationError('Envie até 100 artigos para agrupar.')
    result = []
    seen = set()
    for article in articles:
        if not isinstance(article, dict):
            raise InputValidationError('Cada artigo deve conter PMID e título.')
        pmid, title = article.get('pmid'), article.get('title')
        if not isinstance(pmid, str) or not re.fullmatch(r'[0-9]{1,12}', pmid):
            raise InputValidationError('O PMID do artigo é inválido.')
        if not isinstance(title, str) or not 2 <= len(title.strip()) <= 1200:
            raise InputValidationError('O título deve ter entre 2 e 1200 caracteres.')
        if pmid in seen:
            raise InputValidationError('Não envie PMIDs duplicados.')
        seen.add(pmid)
        result.append((pmid, ' '.join(title.split())))
    return tuple(result)


class PubMedTopicClusterer:
    """Carga preguiçosa, cache limitado e isolamento entre conjuntos de resultados."""

    def __init__(self, *, model_name=DEFAULT_EMBEDDING_MODEL, encoder=None,
                 model_factory: Callable | None = None):
        self.encoder = encoder or ValidatedEmbeddingProvider(model_name)
        self.model_name = self.encoder.name
        self._model_factory = model_factory
        self._lock = RLock()
        self._embeddings = OrderedDict()
        self._reports = OrderedDict()

    def _new_model(self, count, dimension):
        if self._model_factory:
            return self._model_factory(count, dimension)
        from bertopic import BERTopic
        from hdbscan import HDBSCAN
        from sklearn.decomposition import PCA
        from sklearn.feature_extraction.text import CountVectorizer
        return BERTopic(
            embedding_model=None,
            umap_model=PCA(n_components=min(5, count - 1, dimension), svd_solver='full'),
            hdbscan_model=HDBSCAN(min_cluster_size=max(2, min(5, count // 5)),
                                 min_samples=1, prediction_data=False,
                                 metric='euclidean', core_dist_n_jobs=1),
            vectorizer_model=CountVectorizer(stop_words='english', ngram_range=(1, 2)),
            top_n_words=6, calculate_probabilities=False, verbose=False,
        )

    def cluster(self, articles):
        documents = validate_articles(articles)
        metadata = {'method': 'BERTopic', 'embedding_model': self.model_name,
                    'scope': 'current_page_titles', 'document_count': len(documents),
                    'projection': 'PCA', 'clustering': 'HDBSCAN',
                    'limitation': 'Grupos calculados apenas com os títulos desta página; não avaliam relevância, qualidade ou concordância científica.'}
        if len(documents) < 4:
            return {**metadata, 'status': 'insufficient_documents', 'clusters': [], 'points': [],
                    'message': 'São necessários pelo menos 4 artigos nesta página para identificar temas.'}
        started = perf_counter()
        with self._lock:
            if documents in self._reports:
                self._reports.move_to_end(documents)
                report = deepcopy(self._reports[documents])
                report.update(cache_hit=True, new_document_embeddings=0,
                              duration_ms=round((perf_counter() - started) * 1000, 2))
                return report
            try:
                import numpy as np
                from sklearn.decomposition import PCA
                texts = [title for _, title in documents]
                missing = list(dict.fromkeys(text for text in texts if text not in self._embeddings))
                if missing:
                    method = getattr(self.encoder, 'encode_documents', self.encoder.encode)
                    from .semantic_retrieval import _validated_vectors
                    vectors = _validated_vectors(method(missing), expected_count=len(missing))
                    for text, vector in zip(missing, vectors):
                        self._embeddings[text] = vector
                embeddings = np.asarray([self._embeddings[text] for text in texts], dtype=float)
                model = self._new_model(len(texts), embeddings.shape[1])
                topics, _ = model.fit_transform(texts, embeddings)
                if len(topics) != len(documents):
                    raise ValueError('Quantidade inválida de tópicos.')
                projection = PCA(n_components=min(2, embeddings.shape[1]), svd_solver='full').fit_transform(embeddings)
                groups = {}
                points = []
                for (pmid, _title), topic, coordinates in zip(documents, topics, projection):
                    topic = int(topic)
                    if topic < -1:
                        raise ValueError('Identificador de tópico inválido.')
                    groups.setdefault(topic, []).append(pmid)
                    points.append({'pmid': pmid, 'topic_id': topic,
                                   'x': round(float(coordinates[0]), 6),
                                   'y': round(float(coordinates[1]), 6) if len(coordinates) > 1 else 0})
                clusters = []
                for topic, pmids in sorted(groups.items(), key=lambda item: (item[0] == -1, -len(item[1]), item[0])):
                    terms = [word for word, weight in (model.get_topic(topic) or [])
                             if word and float(weight) > 0][:6] if topic != -1 else []
                    clusters.append({'topic_id': topic, 'label': ' · '.join(terms[:3]) or ('Sem grupo definido' if topic == -1 else f'Tema {topic + 1}'),
                                     'terms': terms, 'count': len(pmids), 'pmids': pmids,
                                     'is_outlier': topic == -1})
                report = {**metadata, 'status': 'available', 'clusters': clusters, 'points': points,
                          'topic_count': sum(topic != -1 for topic in groups),
                          'outlier_count': len(groups.get(-1, [])),
                          'new_document_embeddings': len(missing), 'cache_hit': False,
                          'duration_ms': round((perf_counter() - started) * 1000, 2)}
                self._reports[documents] = deepcopy(report)
                if len(self._reports) > 16:
                    self._reports.popitem(last=False)
                for text in texts:
                    self._embeddings.move_to_end(text)
                while len(self._embeddings) > 2000:
                    self._embeddings.popitem(last=False)
                return report
            except Exception as error:
                logger.warning('Falha no agrupamento BERTopic: %s', type(error).__name__)
                raise TopicClusteringError('Não foi possível calcular os grupos de temas. Os resultados do PubMed continuam disponíveis.') from None
