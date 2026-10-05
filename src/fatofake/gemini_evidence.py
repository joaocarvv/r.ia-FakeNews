"""Análise estruturada de trechos científicos rastreáveis com a API Gemini."""

from __future__ import annotations

import json
import ssl
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .transport import default_ssl_context


GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}
_RELATIONS = {"SUPPORTS", "CONTRADICTS", "NEUTRAL", "UNCERTAIN"}
_STUDY_DESIGNS = {
    "SYSTEMATIC_REVIEW_META_ANALYSIS",
    "RANDOMIZED_CLINICAL_TRIAL",
    "OBSERVATIONAL",
    "OTHER",
    "UNKNOWN",
}


_COMPARABILITY = ("DIRECT", "PARTIAL", "INDIRECT")
_ROB_TOOLS = ("ROB2", "ROBINS_I", "AMSTAR2", "NOT_APPLICABLE")
_ROB_JUDGMENTS = ("LOW", "SOME_CONCERNS", "HIGH", "CRITICAL", "UNCLEAR")
_STUDY_ROW_TEXT_LIMITS = {
    "title_pt": 400,
    "design_detail": 200,
    "population": 300,
    "sample_size": 80,
    "intervention_or_exposure": 300,
    "comparator": 300,
    "outcome": 300,
    "effect_estimate": 300,
    "finding_pt": 600,
    "quote_pt": 600,
    "comparability_notes": 400,
    "cohort_or_dataset": 200,
}

_FACTUAL_STUDY_ROW_FIELDS = (
    "title_pt",
    "design_detail",
    "population",
    "sample_size",
    "intervention_or_exposure",
    "comparator",
    "outcome",
    "effect_estimate",
    "finding_pt",
    "quote_pt",
    "cohort_or_dataset",
)


def _study_row_schema() -> dict[str, Any]:
    text = {"type": "STRING"}
    properties: dict[str, Any] = {name: text for name in _STUDY_ROW_TEXT_LIMITS}
    properties.update(
        {
            "comparability": {"type": "STRING", "enum": list(_COMPARABILITY)},
            "rob_tool": {"type": "STRING", "enum": list(_ROB_TOOLS)},
            "rob_overall": {"type": "STRING", "enum": list(_ROB_JUDGMENTS)},
            "rob_domains": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "domain": text,
                        "judgment": {"type": "STRING", "enum": list(_ROB_JUDGMENTS)},
                        "reason": text,
                    },
                    "required": ["domain", "judgment", "reason"],
                },
            },
            "registration_ids": {"type": "ARRAY", "items": text},
        }
    )
    return {"type": "OBJECT", "properties": properties, "required": list(properties)}


def _factual_study_row_schema() -> dict[str, Any]:
    """Campos descritivos; não pede comparabilidade nem risco de viés ao modelo."""

    text = {"type": "STRING"}
    properties: dict[str, Any] = {
        name: text for name in _FACTUAL_STUDY_ROW_FIELDS
    }
    properties["registration_ids"] = {"type": "ARRAY", "items": text}
    return {"type": "OBJECT", "properties": properties, "required": list(properties)}


_STUDY_ROW_PROMPT = (
    "Escreva rationale em português.\n\n"
    "Para cada documento preencha também study_row, uma linha padronizada de "
    "tabela de evidências, usando apenas os trechos: title_pt traduz o título "
    "para português; design_detail descreve o desenho; population, sample_size, "
    "intervention_or_exposure, comparator e outcome descrevem o estudo em "
    "português (string vazia se não informado); effect_estimate copia a medida "
    "de efeito com intervalo de confiança e valor de p quando houver; finding_pt "
    "resume o resultado principal em português; quote_pt traduz evidence_quote. "
    "comparability compara o PICO do estudo com o da alegação: DIRECT quando "
    "população, intervenção/exposição e desfecho coincidem, PARTIAL quando um "
    "elemento difere, INDIRECT quando dois ou mais diferem ou o estudo é "
    "pré-clínico; explique em comparability_notes. Avalie risco de viés com a "
    "ferramenta adequada: ROB2 para ensaios randomizados, ROBINS_I para estudos "
    "não randomizados de intervenção ou exposição, AMSTAR2 para revisões "
    "sistemáticas e NOT_APPLICABLE nos demais casos; use UNCLEAR quando os "
    "trechos não permitirem julgar e nunca invente informação metodológica. "
    "registration_ids lista registros (NCT, ISRCTN, PROSPERO, ReBEC) citados e "
    "cohort_or_dataset nomeia coorte ou base de dados reutilizada, se houver."
)

_FACTUAL_STUDY_ROW_PROMPT = (
    "Escreva rationale em português. Para cada documento preencha study_row "
    "usando exclusivamente informações explícitas nos trechos. title_pt traduz o "
    "título; design_detail copia como os autores descrevem o desenho; population, "
    "sample_size, intervention_or_exposure, comparator e outcome copiam trechos "
    "literais no idioma original; "
    "effect_estimate copia a medida de efeito; finding_pt resume o achado; quote_pt "
    "traduz evidence_quote; registration_ids lista registros citados; "
    "cohort_or_dataset copia o nome da coorte ou base. Use string vazia quando a "
    "informação não estiver presente. Não avalie qualidade metodológica, risco de "
    "viés, robustez, comparabilidade PICO ou validade das conclusões."
)


def _clean_text(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def _enum(value: Any, allowed: Sequence[str], default: str) -> str:
    normalized = _clean_text(value).upper()
    return normalized if normalized in allowed else default


def _parse_study_row(
    raw: Any, *, assess_methodology: bool = True
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    fields = (
        tuple(_STUDY_ROW_TEXT_LIMITS)
        if assess_methodology
        else _FACTUAL_STUDY_ROW_FIELDS
    )
    row: dict[str, Any] = {
        name: _clean_text(raw.get(name), _STUDY_ROW_TEXT_LIMITS[name])
        for name in fields
    }
    if not assess_methodology:
        row["registration_ids"] = [
            _clean_text(item, 60)
            for item in (raw.get("registration_ids") or ())[:5]
            if _clean_text(item)
        ]
        return row
    row["comparability"] = _enum(raw.get("comparability"), _COMPARABILITY, "INDIRECT")
    row["rob_tool"] = _enum(raw.get("rob_tool"), _ROB_TOOLS, "NOT_APPLICABLE")
    row["rob_overall"] = _enum(raw.get("rob_overall"), _ROB_JUDGMENTS, "UNCLEAR")
    row["rob_domains"] = [
        {
            "domain": _clean_text(item.get("domain"), 120),
            "judgment": _enum(item.get("judgment"), _ROB_JUDGMENTS, "UNCLEAR"),
            "reason": _clean_text(item.get("reason"), 300),
        }
        for item in (raw.get("rob_domains") or ())[:8]
        if isinstance(item, dict) and _clean_text(item.get("domain"))
    ]
    row["registration_ids"] = [
        _clean_text(item, 60)
        for item in (raw.get("registration_ids") or ())[:5]
        if _clean_text(item)
    ]
    return row


class GeminiAnalysisError(RuntimeError):
    """A API não produziu uma análise estruturada utilizável."""


@dataclass(frozen=True)
class EvidencePassage:
    passage_id: str
    text: str
    section: str
    source_url: str
    page_number: int | None = None
    content_scope: str = "ABSTRACT"

    def __post_init__(self) -> None:
        if not self.passage_id.strip() or not self.text.strip() or not self.section.strip():
            raise ValueError("Identificador, texto e seção do trecho são obrigatórios.")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("A fonte do trecho precisa ser uma URL HTTP(S).")


@dataclass(frozen=True)
class EvidenceDocument:
    pmid: str
    title: str
    abstract: str
    source_url: str
    passages: tuple[EvidencePassage, ...] = ()

    def __post_init__(self) -> None:
        if not self.pmid.strip() or not self.title.strip():
            raise ValueError("PMID e título são obrigatórios.")
        if not self.abstract.strip() and not self.passages:
            raise ValueError("O documento precisa de resumo ou trechos.")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("A fonte do documento precisa ser uma URL HTTP(S).")

    @property
    def evidence_passages(self) -> tuple[EvidencePassage, ...]:
        if self.passages:
            return self.passages
        return (
            EvidencePassage(
                passage_id=f"{self.pmid}:abstract",
                text=self.abstract,
                section="Abstract",
                source_url=self.source_url,
            ),
        )


@dataclass(frozen=True)
class GeminiEvidenceAssessment:
    pmid: str
    relation: str
    confidence: float
    rationale: str
    evidence_quote: str | None
    study_design: str
    model_name: str
    passage_id: str | None = None
    evidence_section: str | None = None
    evidence_page: int | None = None
    content_scope: str = "ABSTRACT"
    source_url: str | None = None
    # Linha padronizada (PICO, efeito, comparabilidade, viés, tradução).
    study_row: Mapping[str, Any] | None = None


JsonPoster = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class GeminiEvidenceAnalyzer:
    """Compara uma alegação com trechos sem permitir evidência sem proveniência."""

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = "gemini-flash-lite-latest",
        timeout: float = 120.0,
        max_attempts: int = 3,
        retry_backoff: float = 1.0,
        post_json: JsonPoster | None = None,
        ssl_context: ssl.SSLContext | None = None,
        sleep: Callable[[float], None] = time.sleep,
        assess_methodology: bool = True,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A chave Gemini não pode estar vazia.")
        if not model_name.strip():
            raise ValueError("O modelo Gemini não pode estar vazio.")
        if max_attempts < 1:
            raise ValueError("max_attempts deve ser maior ou igual a 1.")
        if retry_backoff < 0:
            raise ValueError("retry_backoff não pode ser negativo.")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.retry_backoff = retry_backoff
        self.assess_methodology = assess_methodology
        self._sleep = sleep
        self._ssl_context = ssl_context or default_ssl_context()
        self._post_json = post_json or self._request_json

    def _request_json(
        self,
        url: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None
        result: Any = None
        for attempt in range(1, self.max_attempts + 1):
            request = Request(
                url,
                data=request_body,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                method="POST",
            )
            try:
                with urlopen(
                    request,
                    timeout=self.timeout,
                    context=self._ssl_context,
                ) as response:
                    result = json.load(response)
                break
            except HTTPError as error:
                last_error = error
                if error.code not in _TRANSIENT_HTTP_STATUS or attempt == self.max_attempts:
                    break
                retry_after = error.headers.get("Retry-After") if error.headers else None
                try:
                    delay = float(retry_after) if retry_after is not None else None
                except ValueError:
                    delay = None
                self._sleep(
                    min(30.0, delay if delay is not None else self.retry_backoff * (2 ** (attempt - 1)))
                )
            except (URLError, TimeoutError) as error:
                last_error = error
                if attempt == self.max_attempts:
                    break
                self._sleep(min(30.0, self.retry_backoff * (2 ** (attempt - 1))))
            except json.JSONDecodeError as error:
                raise GeminiAnalysisError(
                    "O Gemini respondeu, mas o corpo HTTP não contém JSON válido."
                ) from error
        else:  # pragma: no cover - o laço sempre termina por break ou exceção
            raise GeminiAnalysisError("Falha inesperada ao consultar o Gemini.")

        if result is None and last_error is not None:
            if isinstance(last_error, HTTPError) and last_error.code in _TRANSIENT_HTTP_STATUS:
                raise GeminiAnalysisError(
                    "O Gemini está temporariamente indisponível após "
                    f"{self.max_attempts} tentativas (HTTP {last_error.code}). "
                    "Tente novamente em alguns instantes."
                ) from last_error
            raise GeminiAnalysisError(f"Falha ao consultar o Gemini: {last_error}") from last_error
        if not isinstance(result, dict):
            raise GeminiAnalysisError("O Gemini retornou uma resposta inesperada.")
        return result

    def _schema(self) -> dict[str, Any]:
        schema = {
            "type": "OBJECT",
            "properties": {
                "assessments": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "pmid": {"type": "STRING"},
                            "relation": {
                                "type": "STRING",
                                "enum": sorted(_RELATIONS),
                            },
                            "confidence": {
                                "type": "NUMBER",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "rationale": {"type": "STRING"},
                            "evidence_quote": {"type": "STRING"},
                            "passage_id": {"type": "STRING"},
                            "study_design": {
                                "type": "STRING",
                                "enum": sorted(_STUDY_DESIGNS),
                            },
                            "study_row": (
                                _study_row_schema()
                                if self.assess_methodology
                                else _factual_study_row_schema()
                            ),
                        },
                        "required": [
                            "pmid",
                            "relation",
                            "confidence",
                            "rationale",
                            "evidence_quote",
                            "passage_id",
                            "study_design",
                            "study_row",
                        ],
                    },
                }
            },
            "required": ["assessments"],
        }
        if not self.assess_methodology:
            assessment = schema["properties"]["assessments"]["items"]
            assessment["properties"].pop("study_design")
            assessment["required"].remove("study_design")
        return schema

    def _prompt(
        self,
        claim: str,
        documents: Sequence[EvidenceDocument],
        claim_profile: Mapping[str, Any] | None = None,
    ) -> str:
        records = [
            {
                "pmid": item.pmid,
                "title": item.title,
                "passages": [
                    {
                        "passage_id": passage.passage_id,
                        "section": passage.section,
                        "page_number": passage.page_number,
                        "content_scope": passage.content_scope,
                        "source_url": passage.source_url,
                        "text": passage.text,
                    }
                    for passage in item.evidence_passages
                ],
            }
            for item in documents
        ]
        return (
            "Você é um classificador de compatibilidade científica. Compare a "
            "ALEGAÇÃO apenas com os TRECHOS fornecidos, sem usar conhecimento "
            "externo. SUPPORTS significa que o resultado descrito é compatível; "
            "CONTRADICTS significa resultado incompatível; NEUTRAL significa que o "
            "estudo aborda o tema sem responder à alegação; UNCERTAIN significa que "
            "os trechos não permitem decidir. A confiança mede somente a segurança da "
            "classificação textual, nunca a probabilidade de verdade. evidence_quote "
            "deve ser uma citação curta, literal e contígua de um trecho. passage_id "
            "deve identificar exatamente esse trecho; use strings vazias se não houver "
            "evidência. Priorize Results/Resultados e Conclusion/Conclusão sobre "
            "Introdução. Não conclua que a alegação é verdadeira ou "
            "falsa. "
            + (
                _STUDY_ROW_PROMPT
                if self.assess_methodology
                else _FACTUAL_STUDY_ROW_PROMPT
            )
            + (
                "\n\nPICO DA ALEGAÇÃO JSON:\n"
                + json.dumps(
                    {
                        key: claim_profile.get(key)
                        for key in (
                            "claim_type",
                            "population",
                            "intervention",
                            "comparator",
                            "outcome",
                        )
                    },
                    ensure_ascii=False,
                )
                if claim_profile
                else ""
            )
            + "\n\nALEGAÇÃO:\n"
            + claim.strip()
            + "\n\nDOCUMENTOS JSON:\n"
            + json.dumps(records, ensure_ascii=False)
        )

    @staticmethod
    def _response_text(payload: Mapping[str, Any]) -> str:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(str(part.get("text") or "") for part in parts).strip()
        except (KeyError, IndexError, TypeError) as error:
            raise GeminiAnalysisError("Resposta Gemini sem conteúdo analisável.") from error
        if not text:
            raise GeminiAnalysisError("Resposta Gemini vazia.")
        return text

    def analyze(
        self,
        claim: str,
        documents: Sequence[EvidenceDocument],
        claim_profile: Mapping[str, Any] | None = None,
    ) -> tuple[GeminiEvidenceAssessment, ...]:
        if not claim.strip():
            raise ValueError("A alegação não pode estar vazia.")
        if not documents:
            return ()
        by_pmid = {item.pmid: item for item in documents}
        passages_by_pmid = {
            item.pmid: {passage.passage_id: passage for passage in item.evidence_passages}
            for item in documents
        }
        if len(by_pmid) != len(documents):
            raise ValueError("Os documentos não podem repetir o mesmo PMID.")

        endpoint = f"{GEMINI_API_BASE_URL}/{self.model_name}:generateContent"
        request_payload = {
            "contents": [
                {"role": "user", "parts": [{"text": self._prompt(claim, documents, claim_profile)}]}
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": self._schema(),
            },
        }
        response = self._post_json(endpoint, request_payload)
        try:
            decoded = json.loads(self._response_text(response))
            raw_assessments = decoded["assessments"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise GeminiAnalysisError("O Gemini retornou JSON inválido.") from error
        if not isinstance(raw_assessments, list):
            raise GeminiAnalysisError("A lista de avaliações do Gemini é inválida.")

        results: dict[str, GeminiEvidenceAssessment] = {}
        for raw in raw_assessments:
            if not isinstance(raw, dict):
                continue
            pmid = str(raw.get("pmid") or "").strip()
            if pmid not in by_pmid or pmid in results:
                continue
            relation = str(raw.get("relation") or "UNCERTAIN").strip().upper()
            design = str(raw.get("study_design") or "UNKNOWN").strip().upper()
            if relation not in _RELATIONS:
                relation = "UNCERTAIN"
            if design not in _STUDY_DESIGNS or not self.assess_methodology:
                design = "UNKNOWN"
            try:
                confidence = min(1.0, max(0.0, float(raw.get("confidence", 0))))
            except (TypeError, ValueError):
                confidence = 0.0
            rationale = " ".join(str(raw.get("rationale") or "").split())
            quote = " ".join(str(raw.get("evidence_quote") or "").split())[:500]
            passage_id = str(raw.get("passage_id") or "").strip()
            available_passages = passages_by_pmid[pmid]
            if not passage_id and len(available_passages) == 1:
                passage_id = next(iter(available_passages))
            passage = available_passages.get(passage_id)
            normalized_source = " ".join(passage.text.split()) if passage else ""
            missing_direct_evidence = relation in {"SUPPORTS", "CONTRADICTS"} and (
                not quote or passage is None
            )
            invalid_quote = bool(quote) and (
                passage is None or quote not in normalized_source
            )
            if missing_direct_evidence or invalid_quote:
                relation = "UNCERTAIN"
                confidence = 0.0
                rationale = (
                    "A avaliação direta não apresentou uma citação literal localizada "
                    "no trecho indicado; a avaliação foi invalidada."
                )
                quote = ""
            study_row = _parse_study_row(
                raw.get("study_row"), assess_methodology=self.assess_methodology
            )
            if study_row is not None and not self.assess_methodology:
                field_sources = {}
                literal_fields = (
                    "design_detail", "population", "sample_size",
                    "intervention_or_exposure", "comparator", "outcome",
                    "effect_estimate", "cohort_or_dataset",
                )
                for field in literal_fields:
                    value = study_row.get(field) or ""
                    origin = next(
                        (item for item in available_passages.values()
                         if value and value in " ".join(item.text.split())),
                        None,
                    )
                    if origin is None:
                        study_row[field] = ""
                    else:
                        field_sources[field] = {
                            "text": value, "passage_id": origin.passage_id,
                            "section": origin.section, "page": origin.page_number,
                            "source_url": origin.source_url,
                        }
                study_row["registration_ids"] = [
                    value for value in study_row["registration_ids"]
                    if any(value in item.text for item in available_passages.values())
                ]
                study_row["field_sources"] = field_sources
                if not quote:
                    study_row["finding_pt"] = ""
                    study_row["quote_pt"] = ""
            results[pmid] = GeminiEvidenceAssessment(
                pmid=pmid,
                relation=relation,
                confidence=confidence,
                rationale=rationale or "Sem justificativa estruturada.",
                evidence_quote=quote or None,
                study_design=design,
                model_name=self.model_name,
                passage_id=passage.passage_id if passage else None,
                evidence_section=passage.section if passage else None,
                evidence_page=passage.page_number if passage else None,
                content_scope=passage.content_scope if passage else "UNKNOWN",
                source_url=passage.source_url if passage else by_pmid[pmid].source_url,
                study_row=study_row,
            )
        return tuple(results[item.pmid] for item in documents if item.pmid in results)
