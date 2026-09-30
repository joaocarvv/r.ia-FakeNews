"""Validação e extração das alegações de um artigo enviado pelo usuário."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

from .gemini_evidence import GeminiAnalysisError, GeminiEvidenceAnalyzer
from .document_parsing import DocumentParsingError, LiteParseDocumentParser
from .input_validation import DOI_PATTERN, DOI_PREFIX_PATTERN, InputValidationError
from .pmc import ContentRetrievalError, PmcClient
from .pubmed import PubMedClient, PubMedError


MAX_ARTICLE_FILE_BYTES = 10 * 1024 * 1024
SUPPORTED_ARTICLE_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}


@dataclass(frozen=True)
class ArticleSubmission:
    reference: str | None
    reference_type: str | None
    file_name: str | None
    mime_type: str | None
    content: bytes | None

    @property
    def label(self) -> str:
        return self.reference or self.file_name or "artigo enviado"


@dataclass(frozen=True)
class ExtractedArticle:
    title: str | None
    doi: str | None
    primary_claim: str
    search_query: str
    additional_claims: tuple[str, ...]
    absolute_language: tuple[str, ...]
    extraction_model: str


@dataclass(frozen=True)
class ResolvedArticleDocument:
    title: str | None
    doi: str | None
    text: str
    parser_name: str = "scientific-api"
    page_count: int | None = None


class ArticleIngestionError(RuntimeError):
    """O artigo não pôde ser lido de forma confiável."""


class PubMedReferenceResolver:
    """Resolve PMID/DOI pelas APIs do NCBI, sem pedir ao LLM para abrir a página."""

    def __init__(self, pubmed_client: PubMedClient, pmc_client: PmcClient) -> None:
        self.pubmed_client = pubmed_client
        self.pmc_client = pmc_client

    @staticmethod
    def _pmid_from_reference(submission: ArticleSubmission) -> str | None:
        if submission.reference_type != "url" or not submission.reference:
            return None
        parsed = urlparse(submission.reference)
        if parsed.hostname not in {"pubmed.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"}:
            return None
        match = re.search(r"/(?:pubmed/)?(\d{5,10})(?:/|$)", parsed.path)
        return match.group(1) if match else None

    def resolve(self, submission: ArticleSubmission) -> ResolvedArticleDocument | None:
        pmid = self._pmid_from_reference(submission)
        if pmid is None and submission.reference_type == "doi" and submission.reference:
            try:
                _total, identifiers = self.pubmed_client.search_ids(
                    f'"{submission.reference}"[doi]',
                    max_results=1,
                )
            except PubMedError as error:
                raise ArticleIngestionError(
                    "Não foi possível resolver o DOI no PubMed."
                ) from error
            pmid = identifiers[0] if identifiers else None
        if pmid is None:
            return None
        try:
            publications = self.pubmed_client.fetch_summaries((pmid,), {pmid: ()})
            abstract = self.pmc_client.fetch_pubmed_abstract(pmid)
        except (PubMedError, ContentRetrievalError) as error:
            raise ArticleIngestionError(
                f"Não foi possível recuperar o conteúdo do PMID {pmid}."
            ) from error
        if not abstract:
            raise ArticleIngestionError(
                f"O PMID {pmid} não possui abstract disponível para análise."
            )
        publication = publications[0] if publications else None
        title = publication.title if publication else None
        doi = publication.doi if publication else (
            submission.reference if submission.reference_type == "doi" else None
        )
        text = f"Título: {title}\n\nAbstract: {abstract}" if title else abstract
        return ResolvedArticleDocument(title=title, doi=doi, text=text)


def _normalize_reference(value: str) -> tuple[str, str]:
    normalized = value.strip()
    possible_doi = DOI_PREFIX_PATTERN.sub("", normalized).strip()
    if DOI_PATTERN.fullmatch(possible_doi):
        return possible_doi, "doi"
    parsed = urlparse(normalized)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return normalized, "url"
    raise InputValidationError("Informe um DOI ou link HTTP(S) válido para o artigo.")


def validate_article_submission(payload: Mapping[str, Any]) -> ArticleSubmission:
    """Aceita exatamente um link/DOI ou um PDF/imagem codificado em base64."""

    reference_value = payload.get("article_reference")
    file_payload = payload.get("article_file")
    has_reference = isinstance(reference_value, str) and bool(reference_value.strip())
    has_file = isinstance(file_payload, dict)
    if has_reference == has_file:
        raise InputValidationError(
            "Envie exatamente uma origem: link/DOI ou arquivo PDF/imagem."
        )
    if has_reference:
        reference, reference_type = _normalize_reference(reference_value)
        return ArticleSubmission(reference, reference_type, None, None, None)

    assert isinstance(file_payload, dict)
    allowed_fields = {"name", "mime_type", "data_base64"}
    unknown = set(file_payload) - allowed_fields
    if unknown:
        raise InputValidationError("O arquivo contém campos não reconhecidos.")
    name = str(file_payload.get("name") or "").strip()
    mime_type = str(file_payload.get("mime_type") or "").strip().casefold()
    encoded = file_payload.get("data_base64")
    if not name or mime_type not in SUPPORTED_ARTICLE_MIME_TYPES:
        raise InputValidationError("Envie um arquivo PDF, PNG, JPEG ou WebP válido.")
    if not isinstance(encoded, str) or not encoded:
        raise InputValidationError("O conteúdo do arquivo não foi informado.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise InputValidationError("O arquivo enviado possui base64 inválido.") from error
    if not content:
        raise InputValidationError("O arquivo enviado está vazio.")
    if len(content) > MAX_ARTICLE_FILE_BYTES:
        raise InputValidationError("O arquivo deve ter no máximo 10 MB.")
    return ArticleSubmission(None, None, name, mime_type, content)


class GeminiArticleExtractor:
    """Extrai alegações do documento; não avalia se elas estão corretas."""

    def __init__(self, gateway: GeminiEvidenceAnalyzer) -> None:
        self.gateway = gateway

    @staticmethod
    def _schema() -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING"},
                "doi": {"type": "STRING"},
                "primary_claim": {"type": "STRING"},
                "search_query": {"type": "STRING"},
                "additional_claims": {"type": "ARRAY", "items": {"type": "STRING"}},
                "absolute_language": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": [
                "title",
                "doi",
                "primary_claim",
                "search_query",
                "additional_claims",
                "absolute_language",
            ],
        }

    def extract(
        self,
        submission: ArticleSubmission,
        resolved: ResolvedArticleDocument | None = None,
    ) -> ExtractedArticle:
        prompt = (
            "Leia o artigo fornecido e extraia sua principal alegação científica "
            "verificável. Não julgue se ela é verdadeira. A alegação deve mencionar, "
            "quando disponíveis, população, intervenção ou exposição, comparação e "
            "desfecho. Ignore publicidade, opinião e frases sem resultado científico. "
            "Liste no máximo três alegações adicionais. Em absolute_language, copie "
            "expressões absolutas realmente presentes no documento. Use strings vazias "
            "quando título ou DOI não estiverem disponíveis. Em search_query, produza "
            "uma consulta curta em inglês com apenas população, intervenção/exposição "
            "e desfecho, sem dose, percentuais ou a conclusão do artigo."
        )
        parts: list[dict[str, Any]] = [{"text": prompt}]
        payload: dict[str, Any] = {
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": self._schema(),
            }
        }
        if resolved is not None:
            parts.append({"text": "CONTEÚDO RECUPERADO DE FONTE CIENTÍFICA:\n" + resolved.text})
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
        response = self.gateway._post_json(endpoint, payload)
        try:
            decoded = json.loads(self.gateway._response_text(response))
            primary_claim = " ".join(str(decoded["primary_claim"]).split())
            search_query = " ".join(str(decoded["search_query"]).split())
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise GeminiAnalysisError("Não foi possível extrair alegações do artigo.") from error
        if len(primary_claim) < 8:
            raise GeminiAnalysisError(
                "O documento não apresentou uma alegação científica verificável."
            )
        if len(search_query) < 3:
            raise GeminiAnalysisError("Não foi possível preparar a busca científica.")
        additional = tuple(
            " ".join(str(item).split())
            for item in (decoded.get("additional_claims") or [])[:3]
            if str(item).strip()
        )
        absolute = tuple(
            " ".join(str(item).split())
            for item in (decoded.get("absolute_language") or [])[:10]
            if str(item).strip()
        )
        title = " ".join(str(decoded.get("title") or "").split()) or (
            resolved.title if resolved else None
        )
        doi = DOI_PREFIX_PATTERN.sub("", str(decoded.get("doi") or "").strip()) or (
            resolved.doi if resolved else None
        )
        if doi and not DOI_PATTERN.fullmatch(doi):
            doi = None
        return ExtractedArticle(
            title=title,
            doi=doi,
            primary_claim=primary_claim,
            search_query=search_query,
            additional_claims=additional,
            absolute_language=absolute,
            extraction_model=self.gateway.model_name,
        )


class IndependentEvidenceRunner(Protocol):
    def analyze(
        self,
        claim: str,
        article_reference: str | None = None,
        *,
        excluded_dois: tuple[str, ...] = (),
        query_override: str | None = None,
    ) -> Mapping[str, Any]: ...


class ArticleFirstAnalysisRunner:
    """Extrai a alegação do documento e só então busca evidências independentes."""

    def __init__(
        self,
        extractor: GeminiArticleExtractor,
        evidence_runner: IndependentEvidenceRunner,
        reference_resolver: PubMedReferenceResolver | None = None,
        document_parser: LiteParseDocumentParser | None = None,
    ) -> None:
        self.extractor = extractor
        self.evidence_runner = evidence_runner
        self.reference_resolver = reference_resolver
        self.document_parser = document_parser

    def analyze_article(self, submission: ArticleSubmission) -> Mapping[str, Any]:
        resolved = (
            self.reference_resolver.resolve(submission)
            if self.reference_resolver is not None
            else None
        )
        if (
            resolved is None
            and submission.mime_type == "application/pdf"
            and submission.content is not None
            and self.document_parser is not None
        ):
            try:
                parsed = self.document_parser.parse_pdf(submission.content)
            except DocumentParsingError as error:
                raise ArticleIngestionError(str(error)) from error
            resolved = ResolvedArticleDocument(
                title=None,
                doi=None,
                text=parsed.text,
                parser_name=parsed.parser_name,
                page_count=parsed.page_count,
            )
        extracted = self.extractor.extract(submission, resolved)
        excluded = (extracted.doi,) if extracted.doi else ()
        result = dict(
            self.evidence_runner.analyze(
                extracted.primary_claim,
                None,
                excluded_dois=excluded,
                query_override=extracted.search_query,
            )
        )
        result["input"] = {
            "type": "article",
            "source": submission.label,
            "source_type": submission.reference_type or submission.mime_type,
        }
        result["submitted_article"] = {
            "title": extracted.title,
            "doi": extracted.doi,
            "primary_claim": extracted.primary_claim,
            "search_query": extracted.search_query,
            "additional_claims": list(extracted.additional_claims),
            "absolute_language": list(extracted.absolute_language),
            "extraction_model": extracted.extraction_model,
            "excluded_from_independent_evidence": bool(extracted.doi),
            "document_parser": resolved.parser_name if resolved else "gemini-multimodal",
            "page_count": resolved.page_count if resolved else None,
        }
        verification = dict(result.get("verification") or {})
        alerts = [
            item
            for item in (verification.get("alerts") or [])
            if item.get("code") != "NO_ARTICLE_SUBMITTED"
        ]
        alerts.append(
            {
                "code": "PEER_REVIEW_NOT_VERIFIED",
                "severity": "INFO",
                "title": "Revisão por pares ainda não confirmada",
                "detail": (
                    "O artigo foi identificado, mas o status de revisão por pares "
                    "ainda precisa ser confirmado por metadados editoriais."
                ),
                "source_url": submission.reference if submission.reference_type == "url" else None,
            }
        )
        if extracted.absolute_language:
            alerts.insert(
                0,
                {
                    "code": "ABSOLUTE_LANGUAGE_IN_ARTICLE",
                    "severity": "WARNING",
                    "title": "Linguagem absoluta no artigo enviado",
                    "detail": "; ".join(extracted.absolute_language),
                    "source_url": submission.reference if submission.reference_type == "url" else None,
                },
            )
        verification["alerts"] = alerts
        result["verification"] = verification
        return result
