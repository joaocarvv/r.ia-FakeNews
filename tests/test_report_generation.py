import sys
import unittest
from dataclasses import replace
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    ArticleQualityProfile,
    ArticleSynthesis,
    CorpusSynthesis,
    EvidenceDirection,
    EvidenceStrength,
    MethodologySummary,
    QualityLevel,
    ReportConclusion,
    ReportSource,
    RetrievalError,
    generate_evidence_report,
    render_evidence_report_markdown,
)


def corpus(
    direction=EvidenceDirection.SUPPORTS,
    strength=EvidenceStrength.INSUFFICIENT,
    *,
    conflict=False,
):
    quality = ArticleQualityProfile(
        pmid="1",
        level=QualityLevel.LOW,
        study_design="Systematic review",
        rationale="Controlled assessment.",
        source_url="https://pubmed.ncbi.nlm.nih.gov/1/",
    )
    article = ArticleSynthesis(
        pmid="1",
        direction=direction,
        support_probability=0.7,
        contradiction_probability=0.1,
        neutral_probability=0.2,
        assessment_count=2,
        relation_counts=(("SUPPORTS", 2),),
        has_internal_conflict=conflict,
        uncertain_count=0,
        quality=quality,
    )
    return CorpusSynthesis(
        direction=direction,
        strength=strength,
        support_probability=0.7,
        contradiction_probability=0.1,
        neutral_probability=0.2,
        article_count=1,
        has_conflict=conflict,
        rationale="Controlled synthesis.",
        articles=(article,),
    )


def methodology():
    return MethodologySummary(
        pmid="1",
        instrument="AMSTAR 2",
        confidence="CRITICALLY_LOW",
        quality_level=QualityLevel.LOW,
        critical_flaws=(2, 4),
        single_reviewer=True,
        rationale="Two critical flaws.",
        applicability_note="Aplicação aproximada para uma revisão de exposição.",
        source_url="https://www.bmj.com/content/358/bmj.j4008",
    )


def source():
    return ReportSource(
        label="Artigo no PubMed",
        url="https://pubmed.ncbi.nlm.nih.gov/1/",
        pmid="1",
    )


class ReportGenerationTests(unittest.TestCase):
    def test_insufficient_strength_overrides_supportive_direction(self):
        report = generate_evidence_report(
            "Health claim.", corpus(), [methodology()], [source()]
        )

        self.assertEqual(report.conclusion, ReportConclusion.INSUFFICIENT_EVIDENCE)
        self.assertIn("apenas 1 artigo", report.limitations[0])

    def test_maps_sufficient_directions_and_conflict(self):
        cases = (
            (EvidenceDirection.SUPPORTS, False, ReportConclusion.COMPATIBLE_WITH_EVIDENCE),
            (
                EvidenceDirection.CONTRADICTS,
                False,
                ReportConclusion.INCOMPATIBLE_WITH_EVIDENCE,
            ),
            (EvidenceDirection.NEUTRAL, False, ReportConclusion.INCONCLUSIVE),
            (EvidenceDirection.MIXED, True, ReportConclusion.CONFLICTING_EVIDENCE),
        )
        for direction, conflict, expected in cases:
            with self.subTest(direction=direction):
                item = corpus(direction, EvidenceStrength.LOW, conflict=conflict)
                report = generate_evidence_report(
                    "Health claim.", item, [methodology()], [source()]
                )
                self.assertEqual(report.conclusion, expected)

    def test_markdown_explains_classifier_and_exposes_sources(self):
        report = generate_evidence_report(
            "Health claim.",
            corpus(),
            [methodology()],
            [source()],
            ["Associação observacional não estabelece causalidade."],
        )
        rendered = render_evidence_report_markdown(report)

        self.assertIn("## Conclusão: Evidência insuficiente", rendered)
        self.assertIn("O que as evidências sugerem", rendered)
        self.assertIn("não representam a probabilidade", rendered)
        self.assertIn("Por que a confiança é limitada", rendered)
        self.assertIn("https://pubmed.ncbi.nlm.nih.gov/1/", rendered)
        self.assertNotIn("verdadeiro", rendered.lower())
        self.assertNotIn("falso", rendered.lower())

    def test_rejects_missing_or_inconsistent_provenance(self):
        with self.assertRaises(RetrievalError):
            generate_evidence_report("", corpus(), [], [source()])
        with self.assertRaises(RetrievalError):
            generate_evidence_report("Claim", corpus(), [], [])
        with self.assertRaises(RetrievalError):
            generate_evidence_report(
                "Claim",
                corpus(),
                [],
                [replace(source(), pmid="2")],
            )
        with self.assertRaises(RetrievalError):
            generate_evidence_report("Claim", corpus(), [], [source(), source()])


if __name__ == "__main__":
    unittest.main()
