import json
from pathlib import Path
import tempfile
import unittest

from fatofake.retrieval_evaluation import (
    FixtureEncoder, evaluate_fixture, evaluate_grounding, ndcg_at_k,
    precision_at_k, recall_at_k, reciprocal_rank,
)


class RetrievalEvaluationTests(unittest.TestCase):
    def test_known_metric_values_and_duplicate_ranking(self):
        ranking = ['other', 'relevant', 'relevant', 'second']
        relevant = {'relevant', 'second'}
        self.assertEqual(precision_at_k(ranking, relevant, 3), 2 / 3)
        self.assertEqual(recall_at_k(ranking, relevant, 3), 1)
        self.assertEqual(reciprocal_rank(ranking, relevant), .5)
        self.assertEqual(ndcg_at_k(['relevant', 'second'], relevant, 2), 1)
        self.assertEqual(recall_at_k([], relevant, 2), 0)
        self.assertIsNone(recall_at_k([], set(), 2))
        self.assertIsNone(reciprocal_rank([], set()))
        with self.assertRaises(ValueError):
            precision_at_k([], set(), 0)

    def test_structural_grounding_requires_ids_and_literal_quotes(self):
        passages = {'a': 'A intervenção reduziu inflamação.', 'b': 'Nenhuma diferença.'}
        answers = [
            {'relation': 'SUPPORTS', 'citations': [{'passage_id': 'a', 'quote': 'reduziu inflamação'}]},
            {'relation': 'CONTRADICTS', 'citations': [{'passage_id': 'b', 'quote': 'Inventado'}]},
            {'relation': 'NEUTRAL', 'citations': [{'passage_id': 'unknown', 'quote': 'Nenhuma diferença.'}]},
            {'relation': 'UNCERTAIN', 'citations': []},
        ]
        metrics = evaluate_grounding(answers, passages)
        self.assertEqual(metrics.abstention_rate, .25)
        self.assertEqual(metrics.citation_validity, 1 / 3)
        self.assertEqual(metrics.passage_id_coverage, 2 / 3)
        self.assertEqual(metrics.structural_groundedness, 1 / 3)
        self.assertEqual(metrics.evidence_passage_coverage, 1)
        empty = evaluate_grounding([], {})
        self.assertIsNone(empty.abstention_rate)
        self.assertIsNone(empty.citation_validity)
        self.assertIsNone(empty.structural_groundedness)

    def test_five_methods_run_offline_and_qdrant_matches_memory(self):
        path = Path(__file__).parent / 'fixtures/retrieval/golden.json'
        fixture = json.loads(path.read_text())
        with tempfile.TemporaryDirectory() as directory:
            report = evaluate_fixture(fixture, FixtureEncoder(fixture), qdrant_path=directory)
        self.assertEqual(len(report['methods']), 5)
        self.assertEqual(report['restart_new_chunk_embeddings'], 0)
        self.assertTrue(report['controlled_embeddings'])
        self.assertIsNone(report['answer_metrics'])
        for memory, persistent in [('semantic_memory', 'semantic_qdrant'), ('hybrid_memory', 'hybrid_qdrant')]:
            left, right = report['methods'][memory], report['methods'][persistent]
            self.assertEqual(left['summary'], right['summary'])
            for left_case, right_case in zip(left['cases'], right['cases']):
                if left_case['relevant_chunk_ids']:
                    self.assertEqual([item['chunk_id'] for item in left_case['ranking']],
                                     [item['chunk_id'] for item in right_case['ranking']])
                # Empates entre distractores podem ter ordem diferente no ANN, sem ganho de relevância.

    def test_min_score_abstention_is_distinct_from_scientific_answer_abstention(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/retrieval/golden.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            report = evaluate_fixture(fixture, FixtureEncoder(fixture), minimum_score=.1, qdrant_path=directory)
        for method in report['methods'].values():
            self.assertTrue(method['cases'][-1]['retrieval_abstained'])
        self.assertIsNone(report['answer_metrics'])
