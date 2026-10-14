"""Source preview preserves the document alongside its page/section metadata."""
import unittest
from concurrent.futures import ThreadPoolExecutor

from fatofake.api import AnalysisJobService, AnalysisJobStatus, InMemoryAnalysisJobStore, create_app
from fatofake.input_validation import AnalysisInput


class ArticleReaderTests(unittest.TestCase):
    def test_source_keeps_full_canonical_text_and_claim_locations(self):
        store = InMemoryAnalysisJobStore()
        job = store.create(AnalysisInput(claim="Treatment improved outcomes."))
        text = "Introduction\n\nFull source text.\n\nFinal paragraph."
        claim = {"claim_id": "c1", "text": "Improved outcomes.",
                 "quote": "Full source text.", "page": 2, "section": "Results"}
        store.transition(job.analysis_id, status=AnalysisJobStatus.RUNNING, progress=1,
                         workflow={"resolved": {"text": text, "pages": [{"page_number": 2, "text": "Full source text."}],
                                                 "sections": [["Results", "Full source text."]], "content_scope": "FULL_TEXT"},
                                   "extracted": {"claims": [claim]}})
        with ThreadPoolExecutor(max_workers=1) as executor:
            service = AnalysisJobService(object(), store=store, executor=executor)
            response = create_app(service).test_client().get(f"/api/v1/analyses/{job.analysis_id}/source")
        self.assertEqual(response.status_code, 200)
        source = response.get_json()
        self.assertEqual(source["text"], text)
        self.assertEqual(source["claims"], [claim])
        self.assertEqual(source["sections"], [{"title": "Results", "text": "Full source text."}])
        self.assertEqual(source["pages"][0]["page_number"], 2)
