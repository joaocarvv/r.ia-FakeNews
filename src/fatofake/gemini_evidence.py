"""Análise estruturada e rastreável de abstracts com a API Gemini."""

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


class GeminiAnalysisError(RuntimeError):
    """A API não produziu uma análise estruturada utilizável."""


@dataclass(frozen=True)
class EvidenceDocument:
    pmid: str
    title: str
    abstract: str
    source_url: str

    def __post_init__(self) -> None:
        if not self.pmid.strip() or not self.title.strip() or not self.abstract.strip():
            raise ValueError("PMID, título e abstract são obrigatórios.")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("A fonte do documento precisa ser uma URL HTTP(S).")


@dataclass(frozen=True)
class GeminiEvidenceAssessment:
    pmid: str
    relation: str
    confidence: float
    rationale: str
    evidence_quote: str | None
    study_design: str
    model_name: str


JsonPoster = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class GeminiEvidenceAnalyzer:
    """Compara uma alegação com abstracts sem permitir evidência sem proveniência."""

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

    @staticmethod
    def _schema() -> dict[str, Any]:
        return {
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
                            "study_design": {
                                "type": "STRING",
                                "enum": sorted(_STUDY_DESIGNS),
                            },
                        },
                        "required": [
                            "pmid",
                            "relation",
                            "confidence",
                            "rationale",
                            "evidence_quote",
                            "study_design",
                        ],
                    },
                }
            },
            "required": ["assessments"],
        }

    @staticmethod
    def _prompt(claim: str, documents: Sequence[EvidenceDocument]) -> str:
        records = [
            {
                "pmid": item.pmid,
                "title": item.title,
                "abstract": item.abstract,
                "source_url": item.source_url,
            }
            for item in documents
        ]
        return (
            "Você é um classificador de compatibilidade científica. Compare a "
            "ALEGAÇÃO apenas com cada ABSTRACT fornecido, sem usar conhecimento "
            "externo. SUPPORTS significa que o resultado descrito é compatível; "
            "CONTRADICTS significa resultado incompatível; NEUTRAL significa que o "
            "estudo aborda o tema sem responder à alegação; UNCERTAIN significa que "
            "o abstract não permite decidir. A confiança mede somente a segurança da "
            "classificação textual, nunca a probabilidade de verdade. evidence_quote "
            "deve ser uma citação curta, literal e contígua do abstract; use string "
            "vazia se não houver trecho. Não conclua que a alegação é verdadeira ou "
            "falsa.\n\nALEGAÇÃO:\n"
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
    ) -> tuple[GeminiEvidenceAssessment, ...]:
        if not claim.strip():
            raise ValueError("A alegação não pode estar vazia.")
        if not documents:
            return ()
        by_pmid = {item.pmid: item for item in documents}
        if len(by_pmid) != len(documents):
            raise ValueError("Os documentos não podem repetir o mesmo PMID.")

        endpoint = f"{GEMINI_API_BASE_URL}/{self.model_name}:generateContent"
        request_payload = {
            "contents": [
                {"role": "user", "parts": [{"text": self._prompt(claim, documents)}]}
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
            if design not in _STUDY_DESIGNS:
                design = "UNKNOWN"
            try:
                confidence = min(1.0, max(0.0, float(raw.get("confidence", 0))))
            except (TypeError, ValueError):
                confidence = 0.0
            rationale = " ".join(str(raw.get("rationale") or "").split())
            quote = " ".join(str(raw.get("evidence_quote") or "").split())[:500]
            normalized_abstract = " ".join(by_pmid[pmid].abstract.split())
            if quote and quote not in normalized_abstract:
                relation = "UNCERTAIN"
                confidence = 0.0
                rationale = (
                    "O trecho devolvido pelo modelo não foi localizado literalmente "
                    "no abstract; a avaliação foi invalidada."
                )
                quote = ""
            results[pmid] = GeminiEvidenceAssessment(
                pmid=pmid,
                relation=relation,
                confidence=confidence,
                rationale=rationale or "Sem justificativa estruturada.",
                evidence_quote=quote or None,
                study_design=design,
                model_name=self.model_name,
            )
        return tuple(results[item.pmid] for item in documents if item.pmid in results)
