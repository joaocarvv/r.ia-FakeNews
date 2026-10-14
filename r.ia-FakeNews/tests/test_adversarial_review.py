import sys
import unittest
from dataclasses import replace
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    AdversarialCritique,
    AdversarialReviewService,
    ArticleQualityProfile,
    ArticleSynthesis,
    CitedObservation,
    CorpusSynthesis,
    CritiqueIssue,
    EvidenceAssessment,
    EvidenceDirection,
    EvidenceReport,
    EvidenceStatement,
    EvidenceStrength,
    IssueSeverity,
    QualityLevel,
    RelationLabel,
    RelationProbabilities,
    ReportConclusion,
    ReportSource,
    ResearchDraft,
    RetrievalError,
    ReviewStatus,
)


CLAIM = "O consumo de café aumenta o risco de câncer de próstata."


def assessment(pmid, index, relation=RelationLabel.CONTRADICTS):
    evidence = EvidenceStatement(
        statement_id=f"statement-{pmid}-{index}",
        text=f"Controlled finding {index} from article {pmid}.",
        extraction_score=0.9,
        matched_claim_terms=("coffee", "prostate"),
        hybrid_rank=index,
        sentence_index=index,
        chunk_id=f"chunk-{pmid}",
        pmid=pmid,
        pmcid=f"PMC{pmid}",
        doi=f"10.1000/{pmid}",
        section="Results",
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    )
    probabilities = (
        RelationProbabilities(0.08, 0.84, 0.08)
        if relation is RelationLabel.CONTRADICTS
        else RelationProbabilities(0.84, 0.08, 0.08)
    )
    return EvidenceAssessment(
        pair_id=f"pair-{pmid}-{index}",
        relation=relation,
        model_relation=relation,
        confidence=0.84,
        margin=0.76,
        probabilities=probabilities,
        rationale="Controlled classification.",
        model_name="controlled-nli",
        claim=CLAIM,
        evidence=evidence,
    )


def report_for(assessments, conclusion=ReportConclusion.INCOMPATIBLE_WITH_EVIDENCE):
    direction = (
        EvidenceDirection.MIXED
        if conclusion is ReportConclusion.CONFLICTING_EVIDENCE
        else EvidenceDirection.CONTRADICTS
    )
    strength = (
        EvidenceStrength.INSUFFICIENT
        if conclusion is ReportConclusion.INSUFFICIENT_EVIDENCE
        else EvidenceStrength.MODERATE
    )
    articles = []
    for item in assessments:
        quality = ArticleQualityProfile(
            pmid=item.evidence.pmid,
            level=QualityLevel.MODERATE,
            study_design="Controlled example",
            rationale="Controlled quality profile.",
            source_url=item.evidence.source_url,
        )
        articles.append(
            ArticleSynthesis(
                pmid=item.evidence.pmid,
                direction=direction,
                support_probability=item.probabilities.support,
                contradiction_probability=item.probabilities.contradiction,
                neutral_probability=item.probabilities.neutral,
                assessment_count=1,
                relation_counts=((item.relation.value, 1),),
                has_internal_conflict=False,
                uncertain_count=int(item.relation is RelationLabel.UNCERTAIN),
                quality=quality,
            )
        )
    synthesis = CorpusSynthesis(
        direction=direction,
        strength=strength,
        support_probability=0.08,
        contradiction_probability=0.84,
        neutral_probability=0.08,
        article_count=len(articles),
        has_conflict=conclusion is ReportConclusion.CONFLICTING_EVIDENCE,
        rationale="Controlled synthesis.",
        articles=tuple(articles),
    )
    return EvidenceReport(
        claim=CLAIM,
        conclusion=conclusion,
        headline="Controlled report",
        summary="Controlled summary.",
        synthesis=synthesis,
        methodology=(),
        limitations=(),
        sources=tuple(
            ReportSource(
                label=f"PMID {item.evidence.pmid}",
                url=item.evidence.source_url,
                pmid=item.evidence.pmid,
            )
            for item in assessments
        ),
    )


def observation(item, index):
    return CitedObservation(
        observation_id=f"obs-{index}",
        statement_id=item.evidence.statement_id,
        pmid=item.evidence.pmid,
        quote=item.evidence.text,
        relation=item.relation,
        source_url=item.evidence.source_url,
        interpretation="A interpretação permanece limitada ao trecho citado.",
    )


class Researcher:
    def __init__(self, draft):
        self.draft = draft

    def research(self, claim, assessments, report):
        return self.draft


class Critic:
    def __init__(self, issues=()):
        self.issues = tuple(issues)

    def critique(self, claim, assessments, report, draft):
        return AdversarialCritique(
            summary="Controlled independent critique.",
            issues=self.issues,
            model_name="controlled-critic",
            prompt_version="critic-v1",
        )


def draft_for(items):
    return ResearchDraft(
        summary="Controlled grounded draft.",
        observations=tuple(observation(item, index) for index, item in enumerate(items, 1)),
        search_queries=("coffee prostate cancer",),
        limitations=("Controlled data only.",),
        model_name="controlled-researcher",
        prompt_version="research-v1",
    )


class AdversarialReviewTests(unittest.TestCase):
    def setUp(self):
        self.assessments = (assessment("1001", 1), assessment("1002", 1))
        self.report = report_for(self.assessments)

    def review(self, draft=None, critic=None, report=None):
        service = AdversarialReviewService(
            Researcher(draft or draft_for(self.assessments)),
            critic or Critic(),
        )
        return service.review(CLAIM, self.assessments, report or self.report)

    def test_corroborates_only_with_two_grounded_sources(self):
        result = self.review()

        self.assertEqual(result.status, ReviewStatus.CORROBORATED)
        self.assertEqual(result.cited_article_count, 2)
        self.assertFalse(result.provenance_problems)
        self.assertIn("não determina", result.disclaimer)

    def test_abstains_on_invented_statement_and_modified_quote(self):
        valid = draft_for(self.assessments)
        invented = replace(valid.observations[0], statement_id="invented")
        modified = replace(valid.observations[1], quote="A modified quotation.")
        result = self.review(replace(valid, observations=(invented, modified)))

        self.assertEqual(result.status, ReviewStatus.INSUFFICIENT)
        self.assertEqual(
            {problem.code for problem in result.provenance_problems},
            {"UNKNOWN_STATEMENT", "QUOTE_MISMATCH"},
        )

    def test_critical_critique_disputes_the_draft(self):
        issue = CritiqueIssue(
            code="POPULATION_MISMATCH",
            severity=IssueSeverity.CRITICAL,
            message="A população do estudo não representa a alegação.",
            observation_id="obs-1",
        )
        result = self.review(critic=Critic((issue,)))

        self.assertEqual(result.status, ReviewStatus.DISPUTED)

    def test_agents_cannot_promote_an_insufficient_base_report(self):
        result = self.review(
            report=report_for(
                self.assessments,
                ReportConclusion.INSUFFICIENT_EVIDENCE,
            )
        )

        self.assertEqual(result.status, ReviewStatus.INSUFFICIENT)
        self.assertIn("não pode aumentar", result.rationale)

    def test_conflicting_base_report_is_disputed(self):
        result = self.review(
            report=report_for(
                self.assessments,
                ReportConclusion.CONFLICTING_EVIDENCE,
            )
        )

        self.assertEqual(result.status, ReviewStatus.DISPUTED)

    def test_one_cited_article_is_insufficient(self):
        result = self.review(draft_for(self.assessments[:1]))

        self.assertEqual(result.status, ReviewStatus.INSUFFICIENT)
        self.assertEqual(result.cited_article_count, 1)

    def test_unknown_critique_target_forces_abstention(self):
        issue = CritiqueIssue(
            code="OTHER",
            severity=IssueSeverity.WARNING,
            message="Controlled issue.",
            observation_id="obs-that-does-not-exist",
        )
        result = self.review(critic=Critic((issue,)))

        self.assertEqual(result.status, ReviewStatus.INSUFFICIENT)
        self.assertIn(
            "UNKNOWN_CRITIQUE_TARGET",
            {problem.code for problem in result.provenance_problems},
        )

    def test_rejects_mismatched_claim_context(self):
        service = AdversarialReviewService(Researcher(draft_for(self.assessments)), Critic())

        with self.assertRaises(RetrievalError):
            service.review("Outra alegação.", self.assessments, self.report)


if __name__ == "__main__":
    unittest.main()
