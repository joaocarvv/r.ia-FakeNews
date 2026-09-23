import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    SearchPreparationError,
    prepare_search_plan,
    validate_analysis_input,
)


class FixedQueryPlanner:
    def __init__(self, queries: list[object]) -> None:
        self.queries = queries

    def generate_queries(self, claim: str) -> list[object]:
        return self.queries


class PrepareSearchPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis_input = validate_analysis_input(
            "Tomar café aumenta o risco de câncer.",
            "https://doi.org/10.1000/xyz123",
        )

    def test_creates_plan_and_preserves_context(self) -> None:
        planner = FixedQueryPlanner(["coffee cancer risk", "coffee neoplasms"])

        plan = prepare_search_plan(self.analysis_input, planner)

        self.assertEqual(plan.claim, self.analysis_input.claim)
        self.assertEqual(plan.article_reference, "10.1000/xyz123")
        self.assertEqual(plan.queries, ("coffee cancer risk", "coffee neoplasms"))

    def test_normalizes_and_deduplicates_queries(self) -> None:
        planner = FixedQueryPlanner(
            ["  coffee   cancer risk  ", "COFFEE CANCER RISK", "coffee neoplasms"]
        )

        plan = prepare_search_plan(self.analysis_input, planner)

        self.assertEqual(plan.queries, ("coffee cancer risk", "coffee neoplasms"))

    def test_rejects_plan_without_valid_queries(self) -> None:
        with self.assertRaises(SearchPreparationError):
            prepare_search_plan(self.analysis_input, FixedQueryPlanner(["", "   "]))

    def test_rejects_more_than_three_unique_queries(self) -> None:
        planner = FixedQueryPlanner(["query one", "query two", "query three", "query four"])

        with self.assertRaises(SearchPreparationError):
            prepare_search_plan(self.analysis_input, planner)

    def test_rejects_non_text_query(self) -> None:
        with self.assertRaises(SearchPreparationError):
            prepare_search_plan(self.analysis_input, FixedQueryPlanner(["valid query", 123]))


if __name__ == "__main__":
    unittest.main()
