"""Gera um dossiê estruturado e rastreável a partir do artigo inteiro."""

from __future__ import annotations

import base64
import json
import re
from typing import TYPE_CHECKING, Any, Mapping

from .gemini_evidence import GeminiAnalysisError, GeminiEvidenceAnalyzer

if TYPE_CHECKING:
    from .article_ingestion import ArticleSubmission, ResolvedArticleDocument


class WholeArticleAnalysisError(RuntimeError):
    """O documento não pôde ser transformado em um dossiê confiável."""


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


_CAPTION_PATTERN = re.compile(
    r"(?im)^\s*(tabela|table|quadro|figura|figure|fig\.|gráfico|graph)\s*([0-9]+[a-z]?|[ivx]+)\b[.:\s-]*(.{0,140})"
)
_SCOPE_LABELS = {
    "LOCAL_PDF_FULL_TEXT": "Texto completo do PDF enviado",
    "FULL_TEXT": "Texto completo recuperado",
    "OPEN_ACCESS_FULL_TEXT": "Texto completo de acesso aberto",
    "ABSTRACT": "Somente o resumo: o artigo inteiro NÃO foi lido",
    "ABSTRACT_ONLY": "Somente o resumo: o artigo inteiro NÃO foi lido",
    "METADATA_ONLY": "Somente metadados: o conteúdo do artigo NÃO foi lido",
    "URL_CONTEXT_UNVERIFIED": (
        "Leitura indireta pela página do artigo; não é possível garantir que o "
        "texto inteiro foi lido"
    ),
}


def detect_tables_and_figures(
    resolved: ResolvedArticleDocument | None,
) -> list[dict[str, Any]]:
    """Inventário determinístico de legendas, independente do modelo."""

    if resolved is None:
        return []
    pages = resolved.pages or ()
    sources = [(page.page_number, page.text) for page in pages] or [(None, resolved.text)]
    found: dict[str, dict[str, Any]] = {}
    for page_number, text in sources:
        for match in _CAPTION_PATTERN.finditer(text or ""):
            word = match.group(1).casefold()
            kind = "TABLE" if word in {"tabela", "table", "quadro"} else "FIGURE"
            label = f"{match.group(1).strip().capitalize()} {match.group(2)}"
            key = f"{kind}:{match.group(2).casefold()}"
            found.setdefault(
                key,
                {
                    "kind": kind,
                    "label": label,
                    "caption": " ".join(match.group(3).split()),
                    "page": page_number,
                },
            )
    return list(found.values())[:60]


class GeminiWholeArticleAnalyzer:
    """Lê a fonte principal inteira e produz um relatório, não uma conversa."""

    def __init__(self, gateway: GeminiEvidenceAnalyzer) -> None:
        self.gateway = gateway

    @staticmethod
    def _citation_schema() -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "quote": {"type": "STRING"},
                "section": {"type": "STRING"},
            },
            "required": ["quote", "section"],
        }

    @classmethod
    def _schema(cls) -> dict[str, Any]:
        citation = cls._citation_schema()
        return {
            "type": "OBJECT",
            "properties": {
                "overview": {
                    "type": "OBJECT",
                    "properties": {
                        "purpose": {"type": "STRING"},
                        "research_question": {"type": "STRING"},
                        "plain_language_summary": {"type": "STRING"},
                        "authors_conclusion": {"type": "STRING"},
                    },
                    "required": [
                        "purpose",
                        "research_question",
                        "plain_language_summary",
                        "authors_conclusion",
                    ],
                },
                "study": {
                    "type": "OBJECT",
                    "properties": {
                        "design": {"type": "STRING"},
                        "population": {"type": "STRING"},
                        "sample_size": {"type": "STRING"},
                        "intervention_or_exposure": {"type": "STRING"},
                        "comparator": {"type": "STRING"},
                        "outcomes": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "follow_up": {"type": "STRING"},
                        "registration_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "cohort_or_dataset": {"type": "STRING"},
                        "statistical_methods": {"type": "ARRAY", "items": {"type": "STRING"}},
                    },
                    "required": [
                        "design",
                        "population",
                        "sample_size",
                        "intervention_or_exposure",
                        "comparator",
                        "outcomes",
                        "follow_up",
                        "statistical_methods",
                    ],
                },
                "section_summaries": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "section": {"type": "STRING"},
                            "summary": {"type": "STRING"},
                            "key_points": {"type": "ARRAY", "items": {"type": "STRING"}},
                            "citations": {"type": "ARRAY", "items": citation},
                        },
                        "required": ["section", "summary", "key_points", "citations"],
                    },
                },
                "main_findings": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "finding": {"type": "STRING"},
                            "numbers": {"type": "STRING"},
                            "interpretation": {"type": "STRING"},
                            "citations": {"type": "ARRAY", "items": citation},
                        },
                        "required": ["finding", "numbers", "interpretation", "citations"],
                    },
                },
                "strengths": {"type": "ARRAY", "items": {"type": "STRING"}},
                "limitations": {"type": "ARRAY", "items": {"type": "STRING"}},
                "internal_consistency": {
                    "type": "OBJECT",
                    "properties": {
                        "status": {
                            "type": "STRING",
                            "enum": ["CONSISTENT", "PARTIALLY_CONSISTENT", "INCONSISTENT", "NOT_ASSESSABLE"],
                        },
                        "explanation": {"type": "STRING"},
                        "citations": {"type": "ARRAY", "items": citation},
                    },
                    "required": ["status", "explanation", "citations"],
                },
                "red_flags": {"type": "ARRAY", "items": {"type": "STRING"}},
                "authors_declared_limitations": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "limitation": {"type": "STRING"},
                            "citations": {"type": "ARRAY", "items": citation},
                        },
                        "required": ["limitation", "citations"],
                    },
                },
                "tables_figures": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "label": {"type": "STRING"},
                            "kind": {"type": "STRING", "enum": ["TABLE", "FIGURE"]},
                            "description": {"type": "STRING"},
                            "key_data": {"type": "STRING"},
                        },
                        "required": ["label", "kind", "description", "key_data"],
                    },
                },
                "funding": {
                    "type": "OBJECT",
                    "properties": {
                        "status": {
                            "type": "STRING",
                            "enum": ["REPORTED", "NO_FUNDING_DECLARED", "NOT_REPORTED"],
                        },
                        "statement": {"type": "STRING"},
                        "sources": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "citations": {"type": "ARRAY", "items": citation},
                    },
                    "required": ["status", "statement", "sources", "citations"],
                },
                "conflicts_of_interest": {
                    "type": "OBJECT",
                    "properties": {
                        "status": {
                            "type": "STRING",
                            "enum": ["DECLARED_NONE", "DECLARED_PRESENT", "NOT_REPORTED"],
                        },
                        "statement": {"type": "STRING"},
                        "citations": {"type": "ARRAY", "items": citation},
                    },
                    "required": ["status", "statement", "citations"],
                },
                "glossary": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "term": {"type": "STRING"},
                            "definition": {"type": "STRING"},
                        },
                        "required": ["term", "definition"],
                    },
                },
            },
            "required": [
                "overview",
                "study",
                "section_summaries",
                "main_findings",
                "strengths",
                "limitations",
                "internal_consistency",
                "red_flags",
                "glossary",
                "authors_declared_limitations",
                "tables_figures",
                "funding",
                "conflicts_of_interest",
            ],
        }

    @staticmethod
    def _prompt(resolved: ResolvedArticleDocument | None, *, assess_methodology: bool = True) -> str:
        section_names = [title for title, _text in (resolved.sections if resolved else ())]
        inventory = ", ".join(section_names) or "não disponível"
        prompt = (
            "Leia TODO o artigo fornecido e produza um dossiê científico estruturado em "
            "português do Brasil. Isto não é uma conversa. Não use conhecimento externo "
            "e não complete lacunas por suposição. Diferencie explicitamente o que os autores "
            "relatam da sua interpretação metodológica. Resuma todas as seções substantivas, "
            "incluindo métodos, resultados e conclusão. Para resultados, preserve números, "
            "denominadores, medidas de efeito e incerteza quando existirem. Toda afirmação "
            "central deve citar um trecho literal curto e sua seção. Se uma informação não "
            "estiver no documento, escreva 'Não informado'. Não avalie evidência externa nesta "
            "etapa. Em authors_declared_limitations liste somente limitações que os próprios "
            "autores declaram; em limitations, as limitações metodológicas que você "
            "identificar. Em tables_figures descreva cada tabela e figura do artigo e copie "
            "em key_data os números centrais. Em funding e conflicts_of_interest transcreva "
            "as declarações de financiamento e de conflito de interesses; use NOT_REPORTED "
            "quando ausentes. Em study.registration_ids liste registros do estudo (NCT, "
            "ISRCTN, PROSPERO, ReBEC) e em study.cohort_or_dataset o nome do ensaio, coorte "
            "ou base de dados (por exemplo PREDIMED, ELSA-Brasil); use string vazia se não houver. "
            "Para financiamento e conflitos, use NOT_REPORTED "
            "quando o documento não as trouxer. "
            f"Inventário de seções detectadas: {inventory}."
        )
        if not assess_methodology:
            prompt = prompt.replace(
                "Diferencie explicitamente o que os autores relatam da sua interpretação metodológica.",
                "Relate somente o que os autores declaram.",
            ).replace(
                "em limitations, as limitações metodológicas que você identificar.",
                "em limitations, retorne uma lista vazia. Não julgue qualidade metodológica, risco de viés ou validade das conclusões.",
            )
            prompt += (
                " Em study copie valores literais no idioma original; use 'Não informado' "
                "quando não houver trecho explícito. Traduções e resumos ficam nos campos narrativos."
            )
        return prompt

    @staticmethod
    def _page_for_quote(
        quote: str, resolved: ResolvedArticleDocument | None
    ) -> int | None:
        if not resolved or not quote:
            return None
        normalized_quote = _normalize(quote)
        for page in resolved.pages:
            if normalized_quote in _normalize(page.text):
                return page.page_number
        return None

    @classmethod
    def _verify_citations(
        cls, value: Any, resolved: ResolvedArticleDocument | None
    ) -> None:
        if isinstance(value, list):
            for item in value:
                cls._verify_citations(item, resolved)
            return
        if not isinstance(value, dict):
            return
        if "quote" in value and "section" in value:
            quote = " ".join(str(value.get("quote") or "").split())[:1200]
            document_text = _normalize(resolved.text) if resolved else ""
            verified = bool(quote and document_text and _normalize(quote) in document_text)
            value["quote"] = quote
            value["verified"] = verified
            value["page"] = cls._page_for_quote(quote, resolved) if verified else None
        for nested in value.values():
            cls._verify_citations(nested, resolved)

    @staticmethod
    def _coverage(
        report: Mapping[str, Any], resolved: ResolvedArticleDocument | None
    ) -> dict[str, Any]:
        source_sections = [title for title, _text in (resolved.sections if resolved else ())]
        summarized = [
            str(item.get("section") or "")
            for item in (report.get("section_summaries") or ())
            if isinstance(item, Mapping)
        ]
        normalized_summaries = " ".join(_normalize(item) for item in summarized)
        covered = [
            title for title in source_sections if _normalize(title) in normalized_summaries
        ]
        full_scope = bool(
            resolved
            and resolved.content_scope
            in {"FULL_TEXT", "OPEN_ACCESS_FULL_TEXT", "LOCAL_PDF_FULL_TEXT"}
        )
        percentage = (
            round(100 * len(covered) / len(source_sections)) if source_sections else None
        )
        return {
            "content_scope": resolved.content_scope if resolved else "URL_CONTEXT_UNVERIFIED",
            "full_article_available": full_scope,
            "page_count": resolved.page_count if resolved else None,
            "character_count": len(resolved.text) if resolved else None,
            "source_sections": source_sections,
            "summarized_sections": summarized,
            "covered_section_count": len(covered),
            "section_count": len(source_sections),
            "section_coverage_percentage": percentage,
            "citation_verification_available": resolved is not None,
            "scope_label": _SCOPE_LABELS.get(
                resolved.content_scope if resolved else "URL_CONTEXT_UNVERIFIED",
                "Escopo de leitura não identificado",
            ),
            "detected_tables_figures": detect_tables_and_figures(resolved),
        }

    def analyze(
        self,
        submission: ArticleSubmission,
        resolved: ResolvedArticleDocument | None,
    ) -> dict[str, Any]:
        assess_methodology = getattr(self.gateway, "assess_methodology", True)
        parts: list[dict[str, Any]] = [{"text": self._prompt(resolved, assess_methodology=assess_methodology)}]
        payload: dict[str, Any] = {
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": self._schema(),
            }
        }
        if resolved is not None:
            parts.append({"text": "ARTIGO COMPLETO DISPONÍVEL PARA ANÁLISE:\n" + resolved.text})
        elif submission.content is not None:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": submission.mime_type,
                        "data": base64.b64encode(submission.content).decode("ascii"),
                    }
                }
            )
        else:
            reference = (
                f"https://doi.org/{submission.reference}"
                if submission.reference_type == "doi"
                else submission.reference
            )
            parts.append({"text": f"URL do artigo: {reference}"})
            payload["tools"] = [{"url_context": {}}]
        payload["contents"] = [{"role": "user", "parts": parts}]
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gateway.model_name}:generateContent"
        )
        try:
            response = self.gateway._post_json(endpoint, payload)
            decoded = json.loads(self.gateway._response_text(response))
        except (GeminiAnalysisError, json.JSONDecodeError, TypeError) as error:
            raise WholeArticleAnalysisError(
                "Não foi possível gerar o dossiê integral do artigo."
            ) from error
        if not isinstance(decoded, dict):
            raise WholeArticleAnalysisError("O dossiê integral retornou formato inválido.")
        self._verify_citations(decoded, resolved)
        if not assess_methodology:
            decoded["limitations"] = []
            decoded["methodology_assessment"] = "NOT_EVALUATED"
            study = decoded.get("study") or {}
            source = " ".join(resolved.text.split()) if resolved else ""
            for field in ("design", "population", "sample_size", "intervention_or_exposure", "comparator", "follow_up", "cohort_or_dataset"):
                value = " ".join(str(study.get(field) or "").split())
                study[field] = value if value and value in source else "Não informado"
            for field in ("outcomes", "statistical_methods", "registration_ids"):
                study[field] = [value for value in study.get(field) or () if isinstance(value, str) and value and " ".join(value.split()) in source]
            decoded["study"] = study
        decoded["coverage"] = self._coverage(decoded, resolved)
        decoded["model_name"] = self.gateway.model_name
        return decoded
