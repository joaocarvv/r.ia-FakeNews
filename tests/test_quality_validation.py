import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    ArticleContent,
    ClinicalTrialsClient,
    CrossrefClient,
    DataCiteClient,
    Publication,
    QualityLevel,
    StudyDesign,
    ValidationStatus,
    detect_study_design,
    validate_article_quality,
)


def publication(title="Coffee consumption: a systematic review and meta-analysis."):
    return Publication(
        pmid="33431520",
        title=title,
        authors=("Chen X",),
        journal="BMJ Open",
        publication_date="2021",
        doi="10.1136/bmjopen-2020-038902",
        url="https://pubmed.ncbi.nlm.nih.gov/33431520/",
        matched_queries=("33431520[pmid]",),
    )


def content(abstract="This systematic review and meta-analysis evaluated coffee."):
    return ArticleContent(
        pmid="33431520",
        pmcid="PMC7805365",
        doi="10.1136/bmjopen-2020-038902",
        abstract=abstract,
        full_text="Full article text.",
        sections=(),
        access_level="FULL_TEXT",
        pubmed_url="https://pubmed.ncbi.nlm.nih.gov/33431520/",
        pmc_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC7805365/",
    )


def crossref_response(*, retracted=False):
    message = {
        "DOI": "10.1136/bmjopen-2020-038902",
        "title": ["Coffee consumption: a systematic review and meta-analysis."],
        "container-title": ["BMJ Open"],
        "publisher": "BMJ",
        "type": "journal-article",
        "URL": "https://doi.org/10.1136/bmjopen-2020-038902",
    }
    if retracted:
        message["updated-by"] = [
            {"type": "retraction", "source": "retraction-watch", "record-id": 1}
        ]
    return {"message": message}


class StaticFetcher:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.payload


class QualityValidationTests(unittest.TestCase):
    def test_detects_supported_study_designs_conservatively(self):
        self.assertEqual(
            detect_study_design("A systematic review and meta-analysis", None),
            StudyDesign.SYSTEMATIC_REVIEW_META_ANALYSIS,
        )
        self.assertEqual(
            detect_study_design("A randomized controlled trial", None),
            StudyDesign.RANDOMIZED_CLINICAL_TRIAL,
        )
        self.assertEqual(detect_study_design("General health article", None), StudyDesign.UNKNOWN)

    def test_datacite_keeps_only_qualifying_dataset_relations(self):
        fetcher = StaticFetcher(
            {
                "data": [
                    {
                        "id": "10.1000/data",
                        "attributes": {
                            "doi": "10.1000/data",
                            "titles": [{"title": "Original dataset"}],
                            "relatedIdentifiers": [
                                {
                                    "relatedIdentifier": "10.1136/bmjopen-2020-038902",
                                    "relationType": "IsSupplementTo",
                                }
                            ],
                        },
                    },
                    {
                        "id": "10.1000/citation",
                        "attributes": {
                            "titles": [{"title": "Unrelated citation dataset"}],
                            "relatedIdentifiers": [
                                {
                                    "relatedIdentifier": "10.1136/bmjopen-2020-038902",
                                    "relationType": "References",
                                }
                            ],
                        },
                    },
                ]
            }
        )

        records = DataCiteClient(fetch_json=fetcher).find_related_datasets(
            "10.1136/bmjopen-2020-038902"
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].doi, "10.1000/data")
        self.assertEqual(fetcher.calls[0][1]["resource-type-id"], "dataset")

    def test_fetches_explicit_clinical_trial_registration(self):
        fetcher = StaticFetcher(
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT00000001"},
                    "statusModule": {"overallStatus": "COMPLETED"},
                },
                "hasResults": True,
            }
        )

        record = ClinicalTrialsClient(fetch_json=fetcher).fetch_registration("nct00000001")

        self.assertEqual(record.nct_id, "NCT00000001")
        self.assertTrue(record.has_results)

    def test_builds_conservative_report_for_review(self):
        report = validate_article_quality(
            publication(),
            content(),
            CrossrefClient(fetch_json=StaticFetcher(crossref_response())),
            DataCiteClient(fetch_json=StaticFetcher({"data": []})),
            ClinicalTrialsClient(fetch_json=StaticFetcher({})),
        )
        statuses = {item.name: item.status for item in report.checks}

        self.assertEqual(statuses["identity"], ValidationStatus.CONFIRMED)
        self.assertEqual(statuses["retraction"], ValidationStatus.NOT_FOUND)
        self.assertEqual(statuses["data_availability"], ValidationStatus.NOT_FOUND)
        self.assertEqual(statuses["trial_registration"], ValidationStatus.NOT_APPLICABLE)
        self.assertEqual(report.quality_level, QualityLevel.UNCLEAR)
        self.assertEqual(report.to_quality_profile(publication()).level, QualityLevel.UNCLEAR)

    def test_retraction_forces_low_quality(self):
        report = validate_article_quality(
            publication(),
            content(),
            CrossrefClient(fetch_json=StaticFetcher(crossref_response(retracted=True))),
            DataCiteClient(fetch_json=StaticFetcher({"data": []})),
            ClinicalTrialsClient(fetch_json=StaticFetcher({})),
        )

        self.assertEqual(report.quality_level, QualityLevel.LOW)
        self.assertEqual(
            next(item.status for item in report.checks if item.name == "retraction"),
            ValidationStatus.CONFIRMED,
        )

    def test_retraction_is_unknown_when_article_has_no_doi(self):
        item = publication()
        item = Publication(
            pmid=item.pmid,
            title=item.title,
            authors=item.authors,
            journal=item.journal,
            publication_date=item.publication_date,
            doi=None,
            url=item.url,
            matched_queries=item.matched_queries,
        )
        report = validate_article_quality(
            item,
            content(),
            CrossrefClient(fetch_json=StaticFetcher({})),
            DataCiteClient(fetch_json=StaticFetcher({})),
            ClinicalTrialsClient(fetch_json=StaticFetcher({})),
        )

        statuses = {check.name: check.status for check in report.checks}
        self.assertEqual(statuses["retraction"], ValidationStatus.UNKNOWN)
        self.assertEqual(statuses["data_availability"], ValidationStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
