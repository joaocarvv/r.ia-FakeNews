import unittest

from fatofake.chunking import chunk_article_content
from fatofake.pmc import ArticleContent, ContentSection
from fatofake.semantic_retrieval import ValidatedEmbeddingProvider, _validated_vectors
from fatofake.vector_store import ChunkScope, VectorStoreError, chunk_to_payload, payload_to_chunk
from fatofake.retrieval import RetrievalError


def scientific_chunk():
    return chunk_article_content(ArticleContent(
        '123', 'PMC123', '10.1000/test', None, 'A intervenção reduziu inflamação e β-catenina.',
        (ContentSection('Resultados', 'A intervenção reduziu inflamação e β-catenina.', 4),),
        'PMC_FULL_TEXT', 'https://pubmed.ncbi.nlm.nih.gov/123/',
        'https://pmc.ncbi.nlm.nih.gov/articles/PMC123/', parser_version='jats-v1'))[0]


class VectorContractTests(unittest.TestCase):
    def test_payload_roundtrip_preserves_unicode_and_all_provenance(self):
        original = scientific_chunk()
        payload = chunk_to_payload(original, model='test-model', dimension=2, revision='v1')
        self.assertEqual(payload_to_chunk(payload), original)
        self.assertIn('β-catenina', payload['text'])
        self.assertEqual(payload['content_scope'], 'PMC_FULL_TEXT')
        self.assertEqual(payload['parser_version'], 'jats-v1')
        self.assertEqual(payload['page_number'], 4)

    def test_incomplete_or_malformed_payload_is_rejected(self):
        payload = chunk_to_payload(scientific_chunk(), model='test', dimension=2, revision='v1')
        for field, value in [('text', None), ('page_number', -1), ('word_start', '0'),
                             ('payload_version', 999)]:
            with self.subTest(field=field), self.assertRaises(VectorStoreError):
                payload_to_chunk({**payload, field: value})
        del payload['parser_version']
        with self.assertRaises(VectorStoreError):
            payload_to_chunk(payload)

    def test_invalid_vectors_are_rejected(self):
        for vectors, count, dim in [([[0, 0]], 1, 2), ([[float('nan'), 1]], 1, 2),
                                    ([[float('inf'), 1]], 1, 2), ([[1, 2, 3]], 1, 2),
                                    ([[1, 2]], 2, 2), ([[]], 1, None)]:
            with self.subTest(vectors=vectors), self.assertRaises(RetrievalError):
                _validated_vectors(vectors, expected_count=count, expected_dimension=dim)

    def test_provider_rejects_silent_model_or_dimension_changes(self):
        class Encoder:
            name = 'model'
            dimension = 2
            def encode(self, texts):
                return [[1, 2] for _ in texts]
        encoder = Encoder()
        provider = ValidatedEmbeddingProvider('model', encoder=encoder)
        self.assertEqual(provider.encode(['texto']), ((1.0, 2.0),))
        self.assertEqual(provider.dimension, 2)
        encoder.name = 'another'
        with self.assertRaises(RetrievalError):
            provider.encode(['texto'])
        encoder.name, encoder.dimension = 'model', 3
        with self.assertRaises(RetrievalError):
            provider.encode(['texto'])

    def test_scope_intersection_and_empty_allowlist(self):
        chunk = scientific_chunk()
        self.assertTrue(ChunkScope(pmids=('123',), pmcids=('PMC123',),
                                  dois=('10.1000/test',), chunk_ids=(chunk.chunk_id,)).matches(chunk))
        self.assertFalse(ChunkScope(pmids=('999',)).matches(chunk))
        self.assertFalse(ChunkScope(chunk_ids=()).matches(chunk))
        self.assertFalse(ChunkScope(content_scopes=('PUBMED_ABSTRACT',)).matches(chunk))

    def test_chunking_is_deterministic_and_user_full_text_is_identified(self):
        a = scientific_chunk()
        self.assertEqual(a, scientific_chunk())
        doc = ArticleContent('user:1', None, None, None, 'Texto científico português.', (),
                             'USER_PROVIDED_FULL_TEXT', 'https://example.org/a', 'https://example.org/a')
        self.assertEqual(chunk_article_content(doc)[0].source_kind, 'USER_PROVIDED_FULL_TEXT')
        from dataclasses import replace
        self.assertEqual(chunk_article_content(replace(doc, access_level='LOCAL_PDF_FULL_TEXT'))[0].source_kind,
                         'USER_PROVIDED_FULL_TEXT')


    def test_passage_cannot_change_persisted_chunk_text_or_provenance(self):
        from fatofake.gemini_evidence import EvidencePassage
        original = scientific_chunk()
        with self.assertRaisesRegex(ValueError, 'chunk original'):
            EvidencePassage(original.chunk_id, 'Uma conclusão inventada.', original.section,
                            original.source_url, page_number=original.page_number,
                            content_scope=original.content_scope, source_chunk=original)
