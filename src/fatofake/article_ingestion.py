"""Validação e extração das alegações de um artigo enviado pelo usuário."""

from __future__ import annotations

import base64
from difflib import SequenceMatcher
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

from .article_profile import build_article_dossier
from .crossref import (
    CrossrefClient,
    CrossrefError,
    IdentityVerification,
    verify_publication_identity,
)
from .gemini_evidence import GeminiAnalysisError, GeminiEvidenceAnalyzer
from .document_parsing import DocumentParsingError, LiteParseDocumentParser, ParsedPage
from .input_validation import DOI_PATTERN, DOI_PREFIX_PATTERN, InputValidationError
from .pmc import ContentRetrievalError, PmcClient, retrieve_article_content
from .pubmed import PubMedClient, PubMedError
from .result_presentation import build_user_summary
from .verification_cards import build_verification_indicators


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
class ExtractedClaim:
    claim_id: str
    text: str
    search_query: str
    quote: str | None = None
    section: str | None = None
    page: int | None = None


@dataclass(frozen=True)
class ExtractedArticle:
    title: str | None
    doi: str | None
    primary_claim: str
    search_query: str
    additional_claims: tuple[str, ...]
    absolute_language: tuple[str, ...]
    extraction_model: str
    claims: tuple[ExtractedClaim, ...] = ()
    primary_claim_quote: str | None = None
    research_context: str = "UNKNOWN"
    primary_claim_section: str | None = None
    primary_claim_page: int | None = None


@dataclass(frozen=True)
class ResolvedArticleDocument:
    title: str | None
    doi: str | None
    text: str
    pmid: str | None = None
    parser_name: str = "scientific-api"
    page_count: int | None = None
    pages: tuple[ParsedPage, ...] = ()
    sections: tuple[tuple[str, str], ...] = ()
    content_scope: str = "UNKNOWN"
    authors: tuple[str, ...] = ()
    journal: str | None = None
    publication_date: str | None = None
    publication_types: tuple[str, ...] = ()
    source_url: str | None = None
    identity_verification: IdentityVerification | None = None


class ArticleIngestionError(RuntimeError):
    """O artigo não pôde ser lido de forma confiável."""


class PubMedReferenceResolver:
    """Resolve PMID/DOI pelas APIs do NCBI, sem pedir ao LLM para abrir a página."""

    def __init__(
        self,
        pubmed_client: PubMedClient,
        pmc_client: PmcClient,
        crossref_client: CrossrefClient | None = None,
    ) -> None:
        self.pubmed_client = pubmed_client
        self.pmc_client = pmc_client
        self.crossref_client = crossref_client

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
            if not publications:
                raise ArticleIngestionError(
                    f"Não foi possível recuperar os metadados do PMID {pmid}."
                )
            content = retrieve_article_content(publications[0], self.pmc_client)
        except (PubMedError, ContentRetrievalError) as error:
            raise ArticleIngestionError(
                f"Não foi possível recuperar o conteúdo do PMID {pmid}."
            ) from error
        if not content.abstract and not content.full_text:
            raise ArticleIngestionError(
                f"O PMID {pmid} não possui texto disponível para análise."
            )
        publication = publications[0]
        identity: IdentityVerification | None = None
        if self.crossref_client is not None:
            try:
                identity = verify_publication_identity(publication, self.crossref_client)
            except CrossrefError:
                identity = None
        sections = tuple((section.title, section.text) for section in content.sections)
        pages = tuple(
            ParsedPage(section.page_number, section.text)
            for section in content.sections
            if section.page_number is not None
        )
        if content.full_text:
            body = "\n\n".join(
                f"## {title}\n{text}" for title, text in sections
            ) or content.full_text
            parser_name = (
                "liteparse-pmc-pdf"
                if pages
                else "pmc-xml"
            )
        else:
            body = f"## Abstract\n{content.abstract}"
            sections = (("Abstract", content.abstract or ""),)
            parser_name = "pubmed-abstract"
        text = f"Título: {publication.title}\n\n{body}"
        return ResolvedArticleDocument(
            title=publication.title,
            doi=publication.doi
            or (submission.reference if submission.reference_type == "doi" else None),
            text=text,
            pmid=pmid,
            parser_name=parser_name,
            sections=sections,
            pages=pages,
            page_count=len(pages) or None,
            content_scope=content.access_level,
            authors=publication.authors,
            journal=publication.journal,
            publication_date=publication.publication_date,
            publication_types=publication.publication_types,
            source_url=publication.url,
            identity_verification=identity,
        )


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
        claim_schema = {
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING"},
                "quote": {"type": "STRING"},
                "search_query": {"type": "STRING"},
            },
            "required": ["text", "quote", "search_query"],
        }
        return {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING"},
                "doi": {"type": "STRING"},
                "primary_claim": {"type": "STRING"},
                "primary_claim_quote": {"type": "STRING"},
                "search_query": {"type": "STRING"},
                "research_context": {
                    "type": "STRING",
                    "enum": [
                        "BASIC_SCIENCE",
                        "CLINICAL",
                        "EPIDEMIOLOGICAL",
                        "SYSTEMATIC_REVIEW",
                        "UNKNOWN",
                    ],
                },
                "additional_claims": {"type": "ARRAY", "items": {"type": "STRING"}},
                "absolute_language": {"type": "ARRAY", "items": {"type": "STRING"}},
                "claims": {
                    "type": "ARRAY",
                    "items": claim_schema,
                },
            },
            "required": [
                "title",
                "doi",
                "primary_claim",
                "primary_claim_quote",
                "search_query",
                "research_context",
                "additional_claims",
                "absolute_language",
                "claims",
            ],
        }

    @staticmethod
    def _claim_key(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        plain = "".join(char for char in decomposed if not unicodedata.combining(char))
        return " ".join(re.findall(r"[a-z0-9]+", plain))

    @classmethod
    def _is_duplicate(cls, candidate: str, accepted: list[str]) -> bool:
        candidate_key = cls._claim_key(candidate)
        if not candidate_key:
            return True
        candidate_tokens = set(candidate_key.split())
        for previous in accepted:
            previous_key = cls._claim_key(previous)
            if candidate_key == previous_key:
                return True
            previous_tokens = set(previous_key.split())
            union = candidate_tokens | previous_tokens
            overlap = len(candidate_tokens & previous_tokens) / len(union) if union else 1.0
            similarity = SequenceMatcher(None, candidate_key, previous_key).ratio()
            if overlap >= 0.88 or similarity >= 0.93:
                return True
        return False

    @staticmethod
    def _locate_quote(
        resolved: ResolvedArticleDocument | None,
        raw_quote: str,
    ) -> tuple[str | None, str | None, int | None]:
        quote = " ".join(raw_quote.split())[:1000]
        if not quote or resolved is None:
            return quote or None, None, None
        if quote not in " ".join(resolved.text.split()):
            return None, None, None
        page_number: int | None = None
        section_name: str | None = None
        for page in resolved.pages:
            if quote in " ".join(page.text.split()):
                page_number = page.page_number
                break
        for section, section_text in resolved.sections:
            if quote in " ".join(section_text.split()):
                section_name = section
                break
        return quote, section_name, page_number

    def extract(
        self,
        submission: ArticleSubmission,
        resolved: ResolvedArticleDocument | None = None,
    ) -> ExtractedArticle:
        prompt = (
            "Leia o artigo fornecido e extraia de uma a quatro alegações científicas "
            "atômicas e verificáveis, em ordem de importância. Não julgue se são verdadeiras. "
            "Separe relações diferentes: cada alegação deve expressar apenas uma relação "
            "entre exposição/intervenção e desfecho, mecanismo ou fenômeno. Não junte numa "
            "mesma frase resultados que exigiriam buscas diferentes. Para cada item de claims, "
            "copie em quote o menor trecho literal que o sustenta e crie uma search_query curta "
            "em inglês, sem percentuais nem a conclusão do artigo. Evite alegações duplicadas "
            "ou paráfrases. Preencha também os campos legados primary_claim, "
            "primary_claim_quote e search_query com o primeiro item de claims; coloque os demais "
            "textos em additional_claims. Ignore publicidade, opinião e frases sem resultado "
            "científico. Em absolute_language, copie "
            "expressões absolutas realmente presentes no documento. Use strings vazias "
            "quando título ou DOI não estiverem disponíveis. Classifique research_context conforme "
            "o desenho do artigo; BASIC_SCIENCE não deve ser tratado como ensaio clínico."
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
        raw_claims = decoded.get("claims") or [
            {
                "text": primary_claim,
                "quote": decoded.get("primary_claim_quote") or "",
                "search_query": search_query,
            },
            *(
                {
                    "text": str(item),
                    "quote": "",
                    "search_query": str(item),
                }
                for item in (decoded.get("additional_claims") or [])[:3]
            ),
        ]
        claims: list[ExtractedClaim] = []
        accepted_texts: list[str] = []
        for raw_claim in raw_claims[:8]:
            if not isinstance(raw_claim, Mapping):
                continue
            claim_text = " ".join(str(raw_claim.get("text") or "").split())
            claim_query = " ".join(str(raw_claim.get("search_query") or "").split())
            if len(claim_text) < 8 or len(claim_query) < 3:
                continue
            if self._is_duplicate(claim_text, accepted_texts):
                continue
            quote, section, page = self._locate_quote(
                resolved,
                str(raw_claim.get("quote") or ""),
            )
            accepted_texts.append(claim_text)
            claims.append(
                ExtractedClaim(
                    claim_id=f"claim-{len(claims) + 1:02d}",
                    text=claim_text,
                    search_query=claim_query,
                    quote=quote,
                    section=section,
                    page=page,
                )
            )
            if len(claims) == 4:
                break
        if not claims:
            raise GeminiAnalysisError(
                "O documento não apresentou uma alegação científica verificável."
            )
        primary = claims[0]
        primary_claim = primary.text
        search_query = primary.search_query
        additional = tuple(item.text for item in claims[1:])
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
        research_context = str(decoded.get("research_context") or "UNKNOWN").upper()
        if research_context not in {
            "BASIC_SCIENCE",
            "CLINICAL",
            "EPIDEMIOLOGICAL",
            "SYSTEMATIC_REVIEW",
            "UNKNOWN",
        }:
            research_context = "UNKNOWN"
        return ExtractedArticle(
            title=title,
            doi=doi,
            primary_claim=primary_claim,
            search_query=search_query,
            additional_claims=additional,
            absolute_language=absolute,
            extraction_model=self.gateway.model_name,
            claims=tuple(claims),
            primary_claim_quote=primary.quote,
            research_context=research_context,
            primary_claim_section=primary.section,
            primary_claim_page=primary.page,
        )


class IndependentEvidenceRunner(Protocol):
    def analyze(
        self,
        claim: str,
        article_reference: str | None = None,
        *,
        excluded_dois: tuple[str, ...] = (),
        query_override: str | None = None,
        related_seed_pmids: tuple[str, ...] = (),
        seed_doi: str | None = None,
        seed_authors: tuple[str, ...] = (),
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

    @staticmethod
    def _claim_payload(claim: ExtractedClaim) -> dict[str, Any]:
        return {
            "claim_id": claim.claim_id,
            "text": claim.text,
            "search_query": claim.search_query,
            "quote": claim.quote,
            "section": claim.section,
            "page": claim.page,
        }

    @classmethod
    def _submitted_article_payload(
        cls,
        *,
        extracted: ExtractedArticle,
        active_claim: ExtractedClaim,
        submission: ArticleSubmission,
        resolved: ResolvedArticleDocument | None,
        include_all_claims: bool,
    ) -> dict[str, Any]:
        payload = {
            "title": extracted.title,
            "doi": extracted.doi,
            "primary_claim": active_claim.text,
            "active_claim_id": active_claim.claim_id,
            "search_query": active_claim.search_query,
            "additional_claims": [
                claim.text for claim in extracted.claims if claim != active_claim
            ],
            "absolute_language": list(extracted.absolute_language),
            "extraction_model": extracted.extraction_model,
            "primary_claim_quote": active_claim.quote,
            "primary_claim_section": active_claim.section,
            "primary_claim_page": active_claim.page,
            "research_context": extracted.research_context,
            "excluded_from_independent_evidence": bool(extracted.doi),
            "document_parser": resolved.parser_name if resolved else "gemini-multimodal",
            "page_count": resolved.page_count if resolved else None,
            "content_scope": resolved.content_scope if resolved else "GEMINI_URL_CONTEXT",
            "source": submission.label,
        }
        if include_all_claims:
            payload["claims"] = [cls._claim_payload(claim) for claim in extracted.claims]
        return payload

    @staticmethod
    def _add_article_assessment(result: dict[str, Any]) -> None:
        synthesis = result.get("synthesis") or {}
        direction = synthesis.get("direction", "NEUTRAL")
        assessment_by_direction = {
            "SUPPORTS": ("COMPATIBLE", "Compatível com os trechos independentes analisados"),
            "CONTRADICTS": (
                "POTENTIAL_TENSION",
                "Possível incompatibilidade com evidência independente",
            ),
            "MIXED": ("MIXED", "Evidências independentes divergentes"),
            "NEUTRAL": (
                "CONTEXT_ONLY",
                "Contexto relacionado encontrado, sem confirmação direta",
            ),
        }
        status, label = assessment_by_direction.get(
            direction, assessment_by_direction["NEUTRAL"]
        )
        result["article_assessment"] = {
            "status": status,
            "label": label,
            "explanation": (
                "Este rótulo expressa compatibilidade com os trechos recuperados, "
                "não determina que o artigo seja verdadeiro ou falso."
            ),
        }

    def _enrich_claim_result(
        self,
        *,
        result: dict[str, Any],
        extracted: ExtractedArticle,
        active_claim: ExtractedClaim,
        submission: ArticleSubmission,
        resolved: ResolvedArticleDocument | None,
    ) -> dict[str, Any]:
        result["input"] = {
            "type": "article_claim",
            "source": submission.label,
            "source_type": submission.reference_type or submission.mime_type,
            "claim_id": active_claim.claim_id,
        }
        result["submitted_article"] = self._submitted_article_payload(
            extracted=extracted,
            active_claim=active_claim,
            submission=submission,
            resolved=resolved,
            include_all_claims=False,
        )
        verification = dict(result.get("verification") or {})
        verification.pop("confidence_index", None)
        verification["indicators"] = build_verification_indicators(
            articles=tuple(result.get("articles") or ()),
            research_context=extracted.research_context,
        )
        if extracted.research_context != "CLINICAL":
            verification["clinical_trials"] = {
                "status": "NOT_APPLICABLE",
                "registration_percentage": None,
                "registered_count": 0,
                "eligible_count": 0,
                "with_results_count": 0,
                "explanation": (
                    "O artigo foi classificado como "
                    f"{extracted.research_context.lower().replace('_', ' ')}; "
                    "a exigência de registro no ClinicalTrials.gov não se aplica a esse desenho."
                ),
            }
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
                "source_url": (
                    submission.reference if submission.reference_type == "url" else None
                ),
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
                    "source_url": (
                        submission.reference if submission.reference_type == "url" else None
                    ),
                },
            )
        verification["alerts"] = alerts
        result["verification"] = verification
        self._add_article_assessment(result)
        if result.get("report", {}).get("conclusion") == "INSUFFICIENT_EVIDENCE":
            result["report"]["headline"] = "Alegação processada; comparação externa limitada"
            result["report"]["summary"] = (
                "A alegação foi extraída, mas não houve trechos independentes "
                "suficientes para medir compatibilidade. Isso não indica informação falsa."
            )
        result["user_summary"] = build_user_summary(result)
        return result

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
                pages=tuple(getattr(parsed, "pages", ()) or ()),
                content_scope="LOCAL_PDF_FULL_TEXT",
            )
        extracted = self.extractor.extract(submission, resolved)
        dossier = build_article_dossier(
            title=extracted.title,
            doi=extracted.doi,
            pmid=resolved.pmid if resolved else None,
            authors=resolved.authors if resolved else (),
            journal=resolved.journal if resolved else None,
            publication_date=resolved.publication_date if resolved else None,
            publication_types=resolved.publication_types if resolved else (),
            text=resolved.text if resolved else "",
            sections=resolved.sections if resolved else (),
            identity=resolved.identity_verification if resolved else None,
            llm_context=extracted.research_context,
            absolute_language=extracted.absolute_language,
            source_url=(resolved.source_url if resolved else submission.reference),
        )
        excluded = (extracted.doi,) if extracted.doi else ()
        claims = extracted.claims or (
            ExtractedClaim(
                claim_id="claim-01",
                text=extracted.primary_claim,
                search_query=extracted.search_query,
                quote=extracted.primary_claim_quote,
                section=extracted.primary_claim_section,
                page=extracted.primary_claim_page,
            ),
        )
        claim_analyses: list[dict[str, Any]] = []
        for claim in claims:
            claim_result = dict(
                self.evidence_runner.analyze(
                    claim.text,
                    None,
                    excluded_dois=excluded,
                    query_override=claim.search_query,
                    related_seed_pmids=(
                        (resolved.pmid,) if resolved and resolved.pmid else ()
                    ),
                    seed_doi=extracted.doi,
                    seed_authors=resolved.authors if resolved else (),
                )
            )
            claim_result = self._enrich_claim_result(
                result=claim_result,
                extracted=extracted,
                active_claim=claim,
                submission=submission,
                resolved=resolved,
            )
            claim_result["article_dossier"] = dossier
            dossier_alerts: list[dict[str, Any]] = []
            if dossier["editorial_status"]["retraction"] == "RETRACTED":
                dossier_alerts.append(
                    {
                        "code": "SUBMITTED_ARTICLE_RETRACTED",
                        "severity": "CRITICAL",
                        "title": "Alerta grave: artigo enviado retratado",
                        "detail": dossier["editorial_status"]["retraction_explanation"],
                        "source_url": dossier["identity"]["source_url"],
                    }
                )
            if dossier["identity"]["status"] == "REVIEW_REQUIRED":
                dossier_alerts.append(
                    {
                        "code": "SUBMITTED_ARTICLE_IDENTITY_INCONSISTENT",
                        "severity": "CRITICAL",
                        "title": "Alerta grave: identidade inconsistente",
                        "detail": dossier["identity"]["explanation"],
                        "source_url": dossier["identity"]["source_url"],
                    }
                )
            if dossier_alerts:
                verification = dict(claim_result.get("verification") or {})
                verification["alerts"] = dossier_alerts + list(
                    verification.get("alerts") or ()
                )
                claim_result["verification"] = verification
            claim_analyses.append(
                {
                    "claim_id": claim.claim_id,
                    "claim": self._claim_payload(claim),
                    "status": "SUCCEEDED",
                    "result": claim_result,
                }
            )

        result = dict(claim_analyses[0]["result"])
        result["input"] = {
            "type": "article",
            "source": submission.label,
            "source_type": submission.reference_type or submission.mime_type,
        }
        result["submitted_article"] = self._submitted_article_payload(
            extracted=extracted,
            active_claim=claims[0],
            submission=submission,
            resolved=resolved,
            include_all_claims=True,
        )
        result["claim_analyses"] = claim_analyses
        result["article_dossier"] = dossier
        result["user_summary"] = build_user_summary(result)
        return result
