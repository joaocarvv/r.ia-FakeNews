import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    AMSTAR2_ITEMS,
    AmstarConfidence,
    AmstarJudgment,
    AmstarRating,
    RetrievalError,
    assess_amstar2,
)


def judgments(*, no=(), partial=()):
    return [
        AmstarJudgment(
            item_id=item.item_id,
            rating=(
                AmstarRating.NO
                if item.item_id in no
                else AmstarRating.PARTIAL_YES
                if item.item_id in partial
                else AmstarRating.YES
            ),
            evidence=f"Evidence for item {item.item_id}.",
            section="Methods",
            source_url="https://example.org/article",
        )
        for item in AMSTAR2_ITEMS
    ]


class Amstar2Tests(unittest.TestCase):
    def test_high_with_at_most_one_noncritical_weakness(self):
        result = assess_amstar2(judgments(no={1}), reviewer="Reviewer")
        self.assertEqual(result.confidence, AmstarConfidence.HIGH)
        self.assertEqual(result.noncritical_weaknesses, (1,))

    def test_moderate_with_multiple_noncritical_weaknesses(self):
        result = assess_amstar2(judgments(no={1, 3}), reviewer="Reviewer")
        self.assertEqual(result.confidence, AmstarConfidence.MODERATE)

    def test_low_with_one_critical_flaw(self):
        result = assess_amstar2(judgments(no={2}), reviewer="Reviewer")
        self.assertEqual(result.confidence, AmstarConfidence.LOW)
        self.assertEqual(result.critical_flaws, (2,))

    def test_critically_low_with_multiple_critical_flaws(self):
        result = assess_amstar2(judgments(no={2, 7}), reviewer="Reviewer")
        self.assertEqual(result.confidence, AmstarConfidence.CRITICALLY_LOW)
        self.assertEqual(result.critical_flaws, (2, 7))
        self.assertIn("não de uma soma", result.rationale)

    def test_partial_critical_item_is_a_critical_flaw(self):
        result = assess_amstar2(judgments(partial={4}), reviewer="Reviewer")
        self.assertEqual(result.confidence, AmstarConfidence.LOW)
        self.assertEqual(result.critical_flaws, (4,))
        self.assertEqual(result.noncritical_weaknesses, ())

    def test_requires_all_unique_items_and_reviewer(self):
        complete = judgments()
        with self.assertRaises(RetrievalError):
            assess_amstar2(complete[:-1], reviewer="Reviewer")
        with self.assertRaises(RetrievalError):
            assess_amstar2([*complete, complete[0]], reviewer="Reviewer")
        with self.assertRaises(RetrievalError):
            assess_amstar2(complete, reviewer="")


if __name__ == "__main__":
    unittest.main()
