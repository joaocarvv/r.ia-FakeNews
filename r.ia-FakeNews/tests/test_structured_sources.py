import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.structured_sources import (  # noqa: E402
    NCBIStructuredSearch,
    extract_biomedical_entities,
)


class StructuredSourceTests(unittest.TestCase):
    def test_extracts_genes_and_variants_without_treating_common_words_as_genes(self):
        entities = extract_biomedical_entities(
            "A variante BRCA1 c.5266dupC aumenta o risco de câncer."
        )

        self.assertEqual(entities["genes"], ("BRCA1",))
        self.assertEqual(entities["variants"], ("c.5266dupC",))

    def test_searches_gene_and_clinvar_dynamically(self):
        calls = []

        def fetch_json(endpoint, params):
            calls.append((endpoint, dict(params)))
            if endpoint == "esearch.fcgi":
                if params["db"] == "gene":
                    return {"esearchresult": {"count": "1", "idlist": ["672"]}}
                return {"esearchresult": {"count": "1", "idlist": ["123"]}}
            if params["db"] == "gene":
                return {"result": {"672": {"uid": "672", "name": "BRCA1"}}}
            return {"result": {"123": {"uid": "123", "clinical_significance": "Pathogenic"}}}

        result = NCBIStructuredSearch(fetch_json=fetch_json).search(
            "A variante BRCA1 c.5266dupC aumenta o risco?", limit=2
        )

        self.assertEqual(result.entities["genes"], ("BRCA1",))
        self.assertEqual(result.gene_records[0]["name"], "BRCA1")
        self.assertEqual(result.clinvar_records[0]["clinical_significance"], "Pathogenic")
        self.assertEqual(len(calls), 5)
        self.assertEqual(result.failures, ())

    def test_reuses_cached_response(self):
        calls = []

        def fetch_json(endpoint, params):
            calls.append((endpoint, tuple(sorted(params.items()))))
            if endpoint == "esearch.fcgi":
                return {"esearchresult": {"count": "0", "idlist": []}}
            return {"result": {}}

        client = NCBIStructuredSearch(fetch_json=fetch_json, cache_ttl=60)
        client.search("BRCA1")
        client.search("BRCA1")

        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
