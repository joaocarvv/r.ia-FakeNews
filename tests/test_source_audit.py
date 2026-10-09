import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake import (
    AcademicSourceAuditor,
    RetrievalError,
    SourceAuditConfig,
    SourceProbeStatus,
    SourceRole,
)
from fatofake.source_audit import (
    CLINICAL_TRIALS_SEARCH_URL,
    CROSSREF_WORKS_URL,
    DATACITE_DOIS_URL,
    OPENALEX_WORKS_URL,
    PMC_ID_CONVERTER_URL,
    PUBMED_SEARCH_URL,
    SCIELO_ARTICLE_IDENTIFIERS_URL,
    SCIENCEDIRECT_SEARCH_URL,
    SPRINGER_META_URL,
    SPRINGER_OPENACCESS_URL,
)


class ControlledFetcher:
    def __init__(self, *, fail_url=None):
        self.fail_url = fail_url
        self.calls = []

    def __call__(self, url, params, headers):
        self.calls.append((url, dict(params), dict(headers)))
        if url == self.fail_url:
            raise RetrievalError("controlled failure")
        if url == PUBMED_SEARCH_URL:
            return {"esearchresult": {"count": "12", "idlist": ["1", "2"]}}
        if url == PMC_ID_CONVERTER_URL:
            return {"records": [{"pmid": "1", "pmcid": "PMC1"}, {"pmid": "2"}]}
        if url == CLINICAL_TRIALS_SEARCH_URL:
            return {"totalCount": 3, "studies": [{}, {}]}
        if url == CROSSREF_WORKS_URL and params.get("filter"):
            return {"message": {"total-results": 100, "items": [{}]}}
        if url == CROSSREF_WORKS_URL:
            return {"message": {"total-results": 25, "items": [{}, {}]}}
        if url == OPENALEX_WORKS_URL:
            return {"meta": {"count": 21}, "results": [{}, {}]}
        if url == DATACITE_DOIS_URL:
            return {"meta": {"total": 4}, "data": [{}, {}]}
        if url == SCIELO_ARTICLE_IDENTIFIERS_URL:
            return {"meta": {"total": 500}, "objects": [{}, {}]}
        if url == SPRINGER_META_URL:
            return {"result": [{"total": "9"}], "records": [{}, {}]}
        if url == SPRINGER_OPENACCESS_URL:
            return {"result": [{"total": "6"}], "records": [{}, {}]}
        if url == SCIENCEDIRECT_SEARCH_URL:
            return {
                "search-results": {
                    "opensearch:totalResults": "8",
                    "entry": [{}, {}],
                }
            }
        raise AssertionError(f"Unexpected URL: {url}")


class SourceAuditTests(unittest.TestCase):
    def test_audits_every_named_source_and_preserves_roles(self):
        fetcher = ControlledFetcher()
        report = AcademicSourceAuditor(fetch_json=fetcher).audit(
            SourceAuditConfig(
                query="coffee prostate cancer",
                limit=2,
                springer_meta_api_key="springer-meta-secret",
                springer_openaccess_api_key="springer-open-secret",
                elsevier_api_key="elsevier-secret",
            )
        )

        self.assertEqual(len(report.results), 13)
        by_source = {item.source: item for item in report.results}
        self.assertEqual(by_source["PubMed"].result_count, 12)
        self.assertEqual(by_source["PubMed"].role, SourceRole.DISCOVERY)
        self.assertEqual(by_source["PubMed Central (PMC)"].result_count, 1)
        self.assertEqual(by_source["OpenAlex"].result_count, 21)
        self.assertFalse(by_source["SciELO"].query_specific)
        self.assertEqual(
            by_source["Google Acadêmico"].status,
            SourceProbeStatus.MANUAL_ONLY,
        )
        self.assertEqual(
            by_source["Nature"].status,
            SourceProbeStatus.COVERED_BY_OTHER,
        )
        self.assertEqual(report.available_count, 11)
        self.assertEqual(report.error_count, 0)

    def test_does_not_call_publisher_apis_without_credentials(self):
        fetcher = ControlledFetcher()
        report = AcademicSourceAuditor(fetch_json=fetcher).audit(
            SourceAuditConfig(query="coffee prostate cancer", limit=2)
        )
        by_source = {item.source: item for item in report.results}

        self.assertEqual(
            by_source["Springer Nature Meta"].status,
            SourceProbeStatus.CREDENTIAL_REQUIRED,
        )
        self.assertEqual(
            by_source["Springer Nature Open Access"].status,
            SourceProbeStatus.CREDENTIAL_REQUIRED,
        )
        self.assertEqual(
            by_source["ScienceDirect"].status,
            SourceProbeStatus.CREDENTIAL_REQUIRED,
        )
        called_urls = {url for url, _, _ in fetcher.calls}
        self.assertNotIn(SPRINGER_META_URL, called_urls)
        self.assertNotIn(SPRINGER_OPENACCESS_URL, called_urls)
        self.assertNotIn(SCIENCEDIRECT_SEARCH_URL, called_urls)

    def test_keeps_one_source_failure_isolated(self):
        report = AcademicSourceAuditor(
            fetch_json=ControlledFetcher(fail_url=OPENALEX_WORKS_URL)
        ).audit(SourceAuditConfig(query="coffee prostate cancer"))
        by_source = {item.source: item for item in report.results}

        self.assertEqual(by_source["OpenAlex"].status, SourceProbeStatus.ERROR)
        self.assertEqual(by_source["PubMed"].status, SourceProbeStatus.AVAILABLE)
        self.assertEqual(report.error_count, 1)

    def test_validates_configuration(self):
        with self.assertRaises(RetrievalError):
            SourceAuditConfig(query="")
        with self.assertRaises(RetrievalError):
            SourceAuditConfig(query="valid", limit=0)
        with self.assertRaises(RetrievalError):
            AcademicSourceAuditor(timeout=0)


if __name__ == "__main__":
    unittest.main()
