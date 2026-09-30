import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    AnalysisServiceError,
    ArticleContent,
    ArticleEvidenceBundle,
    ArticleProcessingError,
    ArticleQualityReport,
    EvidenceAssessment,
    EvidenceDirection,
    EvidenceStatement,
    EvidenceStrength,
    MultiArticleAnalysisConfig,
    MultiArticleAnalysisService,
    Publication,
    QualityLevel,
    QualityCheck,
    RelationLabel,
    RelationProbabilities,
    ReportConclusion,
    ScientificArticleProcessor,
    StudyDesign,
    ValidationStatus,
)
from fatofake.pubmed import PubMedSearchResult, QueryResult


class Planner:
    def generate_queries(self, claim):
        return ["coffee AND prostate cancer"]


def publication(pmid):
    return Publication(
        pmid=pmid,
        title=f"Article {pmid}",
        authors=("Author",),
        journal="Journal",
        publication_date="2024",
        doi=f"10.1000/{pmid}",
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        matched_queries=("coffee AND prostate cancer",),
    )


class PubMedClientStub:
    def __init__(self, publications):
        self.publications = tuple(publications)

    def search_ids(self, query, *, max_results):
        identifiers = tuple(item.pmid for item in self.publications[:max_results])
        return len(self.publications), identifiers

    def fetch_summaries(self, identifiers, matched_queries):
        by_id = {item.pmid: item for item in self.publications}
        return tuple(by_id[identifier] for identifier in identifiers)


class SearchEngineStub:
    def __init__(self, publications):
        self.publications = tuple(publications)
        self.calls = []

    def search(self, search_plan, *, max_results_per_query):
        self.calls.append((search_plan, max_results_per_query))
        return PubMedSearchResult(
            query_results=(QueryResult(search_plan.queries[0], len(self.publications)),),
            publications=self.publications,
        )


def assessment(pmid, relation=RelationLabel.SUPPORTS):
    statement = EvidenceStatement(
        statement_id=f"statement:{pmid}",
        text="Coffee consumption was associated with prostate cancer risk.",
        extraction_score=1.0,
        matched_claim_terms=("coffee", "prostate"),
        hybrid_rank=1,
        sentence_index=1,
        chunk_id=f"chunk:{pmid}",
        pmid=pmid,
        pmcid=None,
        doi=f"10.1000/{pmid}",
        section="Abstract",
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    )
    probabilities = (
        RelationProbabilities(0.8, 0.1, 0.1)
        if relation is RelationLabel.SUPPORTS
        else RelationProbabilities(0.1, 0.8, 0.1)
    )
    return EvidenceAssessment(
        pair_id=f"pair:{pmid}",
        relation=relation,
        model_relation=relation,
        confidence=0.8,
        margin=0.7,
        probabilities=probabilities,
        rationale="Controlled result.",
        model_name="controlled-nli",
        claim="Beber café pode alterar o risco de câncer de próstata.",
        evidence=statement,
    )


def bundle(pmid, relation=RelationLabel.SUPPORTS, *, retracted=False):
    item = publication(pmid)
    content = ArticleContent(
        pmid=pmid,
        pmcid=None,
        doi=item.doi,
        abstract="Abstract.",
        full_text=None,
        sections=(),
        access_level="ABSTRACT_ONLY",
        pubmed_url=item.url,
        pmc_url=None,
    )
    quality = ArticleQualityReport(
        pmid=pmid,
        doi=item.doi,
        study_design=StudyDesign.OBSERVATIONAL,
        quality_level=QualityLevel.UNCLEAR,
        checks=(
            QualityCheck(
                name="retraction",
                status=(
                    ValidationStatus.CONFIRMED
                    if retracted
                    else ValidationStatus.NOT_FOUND
                ),
                summary=(
                    "Retratação confirmada."
                    if retracted
                    else "Nenhuma retratação localizada."
                ),
                source_url=f"https://doi.org/10.1000/{pmid}",
            ),
        ),
        datasets=(),
        trial_registrations=(),
        rationale="Preliminary external checks.",
    )
    return ArticleEvidenceBundle(item, content, (assessment(pmid, relation),), quality)


class ProcessorStub:
    def __init__(self, bundles, failures=()):
        self.bundles = {item.publication.pmid: item for item in bundles}
        self.failures = set(failures)
        self.calls = []

    def process(self, publication, claim):
        self.calls.append(publication.pmid)
        if publication.pmid in self.failures:
            raise ArticleProcessingError(publication.pmid, "content_retrieval", "Unavailable")
        return self.bundles[publication.pmid]


class ScientificArticleProcessorTests(unittest.TestCase):
    def test_wraps_missing_text_as_a_stage_aware_failure(self):
        item = publication("1")
        content_without_text = ArticleContent(
            pmid="1",
            pmcid=None,
            doi=item.doi,
            abstract=None,
            full_text=None,
            sections=(),
            access_level="METADATA_ONLY",
            pubmed_url=item.url,
            pmc_url=None,
        )
        processor = ScientificArticleProcessor(
            pmc_client=object(),
            embedding_encoder=object(),
            nli_classifier=object(),
            crossref_client=object(),
            datacite_client=object(),
            clinical_trials_client=object(),
        )

        with patch(
            "fatofake.analysis_service.retrieve_article_content",
            return_value=content_without_text,
        ):
            with self.assertRaises(ArticleProcessingError) as raised:
                processor.process(item, "Beber café altera o risco de câncer.")

        self.assertEqual(raised.exception.pmid, "1")
        self.assertEqual(raised.exception.stage, "chunking")


class MultiArticleAnalysisServiceTests(unittest.TestCase):
    def service(self, publications, processor, **config):
        return MultiArticleAnalysisService(
            query_planner=Planner(),
            pubmed_client=PubMedClientStub(publications),
            article_processor=processor,
            config=MultiArticleAnalysisConfig(**config),
        )

    def test_combines_two_independent_articles_and_escapes_insufficient(self):
        publications = [publication("1"), publication("2"), publication("3")]
        processor = ProcessorStub([bundle("1"), bundle("2"), bundle("3")])
        result = self.service(
            publications,
            processor,
            max_results_per_query=3,
            target_articles=2,
            minimum_successful_articles=2,
        ).analyze("Beber café pode alterar o risco de câncer de próstata.")

        self.assertEqual(result.synthesis.article_count, 2)
        self.assertEqual(result.synthesis.direction, EvidenceDirection.SUPPORTS)
        self.assertEqual(result.synthesis.strength, EvidenceStrength.LOW)
        self.assertEqual(result.report.conclusion, ReportConclusion.COMPATIBLE_WITH_EVIDENCE)
        self.assertEqual(processor.calls, ["1", "2"])
        self.assertEqual({source.pmid for source in result.report.sources if source.pmid}, {"1", "2"})

    def test_accepts_a_federated_search_engine_instead_of_a_pubmed_client(self):
        publications = [publication("1"), publication("2")]
        processor = ProcessorStub([bundle("1"), bundle("2")])
        engine = SearchEngineStub(publications)
        service = MultiArticleAnalysisService(
            query_planner=Planner(),
            search_engine=engine,
            article_processor=processor,
            config=MultiArticleAnalysisConfig(
                max_results_per_query=4,
                target_articles=2,
                minimum_successful_articles=2,
            ),
        )

        result = service.analyze(
            "Beber café pode alterar o risco de câncer de próstata."
        )

        self.assertEqual(result.synthesis.article_count, 2)
        self.assertEqual(engine.calls[0][1], 4)

    def test_skips_failure_and_continues_to_next_candidate(self):
        publications = [publication("1"), publication("2"), publication("3")]
        processor = ProcessorStub(
            [bundle("1"), bundle("2"), bundle("3")], failures={"1"}
        )
        result = self.service(
            publications,
            processor,
            max_results_per_query=3,
            target_articles=2,
            minimum_successful_articles=2,
        ).analyze("Beber café pode alterar o risco de câncer de próstata.")

        self.assertEqual([item.publication.pmid for item in result.articles], ["2", "3"])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].stage, "content_retrieval")
        self.assertTrue(
            any(
                "1 artigo(s) candidato(s) falharam" in limitation
                for limitation in result.report.limitations
            )
        )

    def test_excludes_retracted_article_and_continues_to_next_candidate(self):
        publications = [publication("1"), publication("2"), publication("3")]
        processor = ProcessorStub(
            [bundle("1", retracted=True), bundle("2"), bundle("3")]
        )
        result = self.service(
            publications,
            processor,
            max_results_per_query=3,
            target_articles=2,
            minimum_successful_articles=2,
        ).analyze("Beber café pode alterar o risco de câncer de próstata.")

        self.assertEqual(
            [item.publication.pmid for item in result.articles],
            ["2", "3"],
        )
        self.assertEqual(result.failures[0].stage, "eligibility")
        self.assertIn("retratação confirmada", result.failures[0].reason.lower())

    def test_rejects_when_minimum_cannot_be_reached(self):
        publications = [publication("1"), publication("2")]
        processor = ProcessorStub([bundle("1"), bundle("2")], failures={"2"})
        with self.assertRaisesRegex(AnalysisServiceError, "mínimo de 2"):
            self.service(
                publications,
                processor,
                max_results_per_query=2,
                target_articles=2,
                minimum_successful_articles=2,
            ).analyze("Beber café pode alterar o risco de câncer de próstata.")

    def test_validates_configuration(self):
        with self.assertRaises(Exception):
            MultiArticleAnalysisConfig(target_articles=1)
        with self.assertRaises(Exception):
            MultiArticleAnalysisConfig(target_articles=2, minimum_successful_articles=3)
        with self.assertRaises(Exception):
            MultiArticleAnalysisService(
                query_planner=Planner(),
                article_processor=ProcessorStub([]),
            )
        with self.assertRaises(Exception):
            MultiArticleAnalysisService(
                query_planner=Planner(),
                pubmed_client=PubMedClientStub([]),
                search_engine=SearchEngineStub([]),
                article_processor=ProcessorStub([]),
            )


if __name__ == "__main__":
    unittest.main()
