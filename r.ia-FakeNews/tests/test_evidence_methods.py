import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fatofake.claim_structuring import (
    GeminiClaimStructurer,
    boolean_queries,
    english_keywords,
    parse_claim_profile,
)
from fatofake.document_parsing import ParsedPage
from fatofake.evidence_table import synthesize_evidence
from fatofake.gemini_evidence import (
    EvidenceDocument,
    EvidencePassage,
    GeminiEvidenceAnalyzer,
    _parse_study_row,
)
from fatofake.report_export import render_markdown_report
from fatofake.research_plan import research_estimates
from fatofake.article_ingestion import ResolvedArticleDocument
from fatofake.whole_article_analysis import detect_tables_and_figures


def article(pmid, relation, *, design="RANDOMIZED_CLINICAL_TRIAL", year="2020",
            comparability="DIRECT", rob="LOW", registration=(), status=None):
    payload = {
        "pmid": pmid,
        "doi": f"10.1000/{pmid}",
        "title": f"Study {pmid}",
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "publication_date": f"{year} Jan",
        "access_level": "FULL_TEXT",
        "quality": {"study_design": design},
        "assessments": [
            {
                "relation": relation,
                "rationale": "Motivo.",
                "evidence": {"text": "quote", "section": "Results"},
                "study_row": {
                    "title_pt": f"Estudo {pmid}",
                    "comparability": comparability,
                    "rob_overall": rob,
                    "rob_tool": "ROB2",
                    "registration_ids": list(registration),
                    "quote_pt": "trecho",
                },
            }
        ],
    }
    if status:
        payload["editorial_status"] = status
    return payload


class ClaimStructuringTests(unittest.TestCase):
    def test_parses_profile_and_builds_boolean_queries(self):
        profile = parse_claim_profile(
            {
                "claim_type": "therapeutic",
                "population": "Adultos",
                "importance": "high",
                "concept_groups": [
                    ["carcinoid tumor", "neuroendocrine tumor"],
                    ["appendix"],
                    ["appendectomy", "appendicectomy"],
                    ['bad "term"'],
                ],
            }
        )

        self.assertEqual(profile.claim_type, "THERAPEUTIC")
        self.assertEqual(profile.importance, "HIGH")
        self.assertEqual(len(profile.concept_groups), 3)
        queries = boolean_queries(profile.concept_groups)
        self.assertEqual(
            queries[0],
            '("carcinoid tumor" OR "neuroendocrine tumor") AND appendix AND '
            "(appendectomy OR appendicectomy)",
        )
        self.assertEqual(
            queries[1], '("carcinoid tumor" OR "neuroendocrine tumor") AND appendix'
        )

    def test_unknown_enums_fall_back(self):
        profile = parse_claim_profile({"claim_type": "x", "importance": "huge"})

        self.assertEqual(profile.claim_type, "OTHER")
        self.assertEqual(profile.importance, "MEDIUM")
        self.assertEqual(boolean_queries(profile.concept_groups), ())

    def test_english_keywords_drop_stopwords(self):
        self.assertEqual(
            english_keywords("Carcinoid tumors of the appendix can only be treated with appendectomy"),
            "carcinoid tumors appendix treated appendectomy",
        )

    def test_structurer_calls_gemini_with_schema(self):
        class Gateway:
            model_name = "stub"

            def __init__(self):
                self.payloads = []

            def _post_json(self, url, payload):
                self.payloads.append(payload)
                text = json.dumps({"claim_type": "PROGNOSTIC", "concept_groups": [["a b"]]})
                return {"candidates": [{"content": {"parts": [{"text": text}]}}]}

            _response_text = staticmethod(GeminiEvidenceAnalyzer._response_text)

        gateway = Gateway()
        profile = GeminiClaimStructurer(gateway).structure("Alegação apenas em adultos.")

        self.assertEqual(profile.claim_type, "PROGNOSTIC")
        prompt = gateway.payloads[0]["contents"][0]["parts"][0]["text"]
        self.assertIn("apenas", prompt)


class StudyRowTests(unittest.TestCase):
    def test_normalizes_enums_and_limits(self):
        row = _parse_study_row(
            {
                "comparability": "weird",
                "rob_tool": "rob2",
                "rob_overall": "high",
                "rob_domains": [{"domain": "Randomização", "judgment": "x", "reason": "r"}, "bad"],
                "registration_ids": ["NCT0001", ""],
                "title_pt": "Título",
            }
        )

        self.assertEqual(row["comparability"], "INDIRECT")
        self.assertEqual(row["rob_tool"], "ROB2")
        self.assertEqual(row["rob_overall"], "HIGH")
        self.assertEqual(row["rob_domains"][0]["judgment"], "UNCLEAR")
        self.assertEqual(row["registration_ids"], ["NCT0001"])
        self.assertIsNone(_parse_study_row("not a dict"))

    def test_analyzer_parses_study_row_and_sends_pico(self):
        documents = [
            EvidenceDocument(
                pmid="1",
                title="Trial",
                abstract="",
                source_url="https://example.org/1",
                passages=(
                    EvidencePassage(
                        passage_id="1:r",
                        text="Mortality was lower with treatment.",
                        section="Results",
                        source_url="https://example.org/1",
                    ),
                ),
            )
        ]
        sent = []

        def post_json(url, payload):
            sent.append(payload)
            output = {
                "assessments": [
                    {
                        "pmid": "1",
                        "relation": "SUPPORTS",
                        "confidence": 0.8,
                        "rationale": "Compatível.",
                        "evidence_quote": "Mortality was lower with treatment.",
                        "passage_id": "1:r",
                        "study_design": "RANDOMIZED_CLINICAL_TRIAL",
                        "study_row": {"title_pt": "Ensaio", "comparability": "DIRECT"},
                    }
                ]
            }
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(output)}]}}]}

        analyzer = GeminiEvidenceAnalyzer("key", post_json=post_json)
        result = analyzer.analyze(
            "Tratamento reduz mortalidade.",
            documents,
            claim_profile={"population": "Adultos com sepse"},
        )

        self.assertEqual(result[0].study_row["title_pt"], "Ensaio")
        self.assertEqual(result[0].study_row["comparability"], "DIRECT")
        self.assertIn("Adultos com sepse", sent[0]["contents"][0]["parts"][0]["text"])


class WeightedSynthesisTests(unittest.TestCase):
    def test_weights_by_method_instead_of_votes(self):
        articles = [
            article("1", "SUPPORTS"),
            article("2", "CONTRADICTS", design="OBSERVATIONAL", comparability="INDIRECT", rob="HIGH"),
            article("3", "CONTRADICTS", design="OBSERVATIONAL", comparability="INDIRECT", rob="HIGH"),
        ]

        synthesis = synthesize_evidence(articles, candidate_count=3)

        # Dois estudos fracos contra um ensaio direto de baixo risco não viram maioria.
        self.assertEqual(synthesis["verdict"]["code"], "WEIGHTED_SUPPORT")
        self.assertGreater(synthesis["weighted"]["supports"], synthesis["weighted"]["contradicts"])
        self.assertEqual(synthesis["rows"][0]["title_pt"], "Estudo 1")

    def test_concept_check_downgrades_study_of_another_intervention(self):
        metformin = article("1", "SUPPORTS")
        metformin["title"] = "Metformin and SARS-CoV-2 viral load in outpatients"
        ivermectin = article("2", "SUPPORTS")
        ivermectin["title"] = "Ivermectin for COVID-19 hospitalization in outpatients"
        profile = {
            "claim_type": "THERAPEUTIC",
            "concept_groups": [["ivermectin"], ["COVID-19", "SARS-CoV-2"], ["hospitalization"]],
        }

        rows = synthesize_evidence([metformin, ivermectin], candidate_count=2, claim_profile=profile)["rows"]

        self.assertEqual(rows[0]["model_comparability"], "DIRECT")
        self.assertEqual(rows[0]["comparability"], "INDIRECT")
        self.assertIn("intervenção", rows[0]["comparability_check"])
        self.assertEqual(rows[1]["comparability"], "DIRECT")
        self.assertGreater(rows[1]["weight"], rows[0]["weight"])

    def test_shared_population_splits_weight(self):
        articles = [
            article("1", "SUPPORTS", registration=("NCT0001",)),
            article("2", "SUPPORTS", registration=("NCT 0001",)),
        ]

        rows = synthesize_evidence(articles, candidate_count=2)["rows"]

        self.assertEqual(rows[0]["duplicate_group"], "registro NCT0001")
        self.assertAlmostEqual(rows[0]["weight"] + rows[1]["weight"], 0.85, places=2)

    def test_links_registry_and_cohort_and_excludes_submitted_population(self):
        linked = article("1", "SUPPORTS", registration=("ISRCTN35739639",))
        linked["assessments"][0]["study_row"]["cohort_or_dataset"] = "PREDIMED"
        cohort_only = article("2", "SUPPORTS")
        cohort_only["assessments"][0]["study_row"]["cohort_or_dataset"] = "PREDIMED"
        registry_only = article("3", "SUPPORTS", registration=("ISRCTN35739639",))
        independent = article("4", "SUPPORTS")

        free = synthesize_evidence([linked, cohort_only, registry_only], candidate_count=3)["rows"]
        excluded = synthesize_evidence(
            [linked, cohort_only, registry_only, independent],
            candidate_count=4,
            submitted_population=["PREDIMED"],
        )

        # Uma única população: os três dividem o peso de um estudo.
        self.assertEqual(len({row["duplicate_group"] for row in free}), 1)
        self.assertAlmostEqual(sum(row["weight"] for row in free), 0.85, places=2)
        rows = excluded["rows"]
        self.assertTrue(all(row["same_population_as_submitted"] for row in rows[:3]))
        self.assertEqual([row["weight"] for row in rows[:3]], [0.0, 0.0, 0.0])
        self.assertGreater(rows[3]["weight"], 0)
        self.assertIn("mesma população do artigo enviado", excluded["verdict"]["explanation"])

    def test_retracted_study_has_no_weight(self):
        synthesis = synthesize_evidence(
            [article("1", "CONTRADICTS", status="RETRACTED")], candidate_count=1
        )

        self.assertEqual(synthesis["rows"][0]["weight"], 0)
        self.assertEqual(synthesis["verdict"]["code"], "NO_DIRECT_EVIDENCE")
        self.assertIn("retratado", synthesis["verdict"]["explanation"])

    def test_distinguishes_not_found_from_not_existing(self):
        empty = synthesize_evidence([], candidate_count=0, sources=["PubMed"])
        unanswered = synthesize_evidence([article("1", "NEUTRAL")], candidate_count=4)

        self.assertEqual(empty["absence"]["code"], "NOT_FOUND")
        self.assertIn("não “não existe”", empty["absence"]["message"])
        self.assertEqual(unanswered["absence"]["code"], "FOUND_NOT_ANSWERED")

    def test_timeline_range(self):
        synthesis = synthesize_evidence(
            [article("1", "SUPPORTS", year="2001"), article("2", "NEUTRAL", year="2019")],
            candidate_count=2,
        )

        self.assertEqual(synthesis["timeline"], {"first_year": 2001, "last_year": 2019})


class ReportAndPlanTests(unittest.TestCase):
    def test_markdown_report_includes_citations_and_reproducibility(self):
        weighted = synthesize_evidence([article("1", "SUPPORTS")], candidate_count=1)
        job = {
            "analysis_id": "abc",
            "article_reference": "10.1/x",
            "updated_at": "2026-10-01",
            "result": {
                "submitted_article": {"title": "Artigo"},
                "whole_article_analysis": {
                    "overview": {"purpose": "Objetivo"},
                    "study": {},
                    "coverage": {"scope_label": "Somente o resumo"},
                    "funding": {"statement": "CNPq", "citations": [{"quote": "CNPq", "section": "Funding", "verified": True}]},
                },
                "claim_analyses": [
                    {
                        "claim": {"text": "Alegação X", "quote": "trecho", "page": 2},
                        "result": {
                            "weighted_evidence": weighted,
                            "reproducibility": {"queries": ["a AND b"], "depth": "QUICK"},
                        },
                    }
                ],
            },
        }

        markdown = render_markdown_report(job)

        self.assertIn("# Relatório artfact — Artigo", markdown)
        self.assertIn("Somente o resumo", markdown)
        self.assertIn("CNPq", markdown)
        self.assertIn("Estudo 1", markdown)
        self.assertIn("`a AND b`", markdown)

    def test_estimates_scale_with_depth(self):
        modes = research_estimates("model")["modes"]

        self.assertLess(modes["QUICK"]["cost_usd_per_claim"], modes["DEEP"]["cost_usd_per_claim"])
        self.assertLess(modes["QUICK"]["seconds_per_claim"][1], modes["DEEP"]["seconds_per_claim"][1])

    def test_detects_table_and_figure_captions_by_page(self):
        resolved = ResolvedArticleDocument(
            title=None,
            doi=None,
            text="",
            pages=(
                ParsedPage(1, "Introdução\nTabela 1 - Características"),
                ParsedPage(2, "Figure 2. Survival curve\nTabela 1 continuação"),
            ),
        )

        found = detect_tables_and_figures(resolved)

        self.assertEqual(
            [(item["kind"], item["label"], item["page"]) for item in found],
            [("TABLE", "Tabela 1", 1), ("FIGURE", "Figure 2", 2)],
        )


if __name__ == "__main__":
    unittest.main()
