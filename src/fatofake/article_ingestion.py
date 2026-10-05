"""Validação e extração das alegações de um artigo enviado pelo usuário."""

from __future__ import annotations

import base64
from difflib import SequenceMatcher
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

from .article_profile import build_article_dossier
from .claim_structuring import (
    CLAIM_PROFILE_INSTRUCTIONS,
    ClaimProfile,
    GeminiClaimStructurer,
    boolean_queries,
    claim_profile_schema,
    parse_claim_profile,
)
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
from .evidence_table import synthesize_evidence
from .research_plan import research_estimates
from .result_presentation import build_user_summary
from .verification_cards import build_verification_indicators
from .structured_logging import logged_step


logger = logging.getLogger(__name__)


MAX_ARTICLE_FILE_BYTES = 25 * 1024 * 1024
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
    profile: ClaimProfile | None = None
    edited: bool = False


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


@dataclass(frozen=True)
class PreparedArticle:
    """Snapshot serializável produzido antes da escolha humana das alegações."""

    submission: ArticleSubmission
    resolved: ResolvedArticleDocument | None
    extracted: ExtractedArticle
    dossier: Mapping[str, Any]
    whole_article_analysis: Mapping[str, Any] | None

    def to_workflow_payload(self) -> dict[str, Any]:
        resolved = self.resolved
        return {
            "version": 1,
            "submission": {
                "reference": self.submission.reference,
                "reference_type": self.submission.reference_type,
                "file_name": self.submission.file_name,
                "mime_type": self.submission.mime_type,
            },
            "resolved": None if resolved is None else {
                "title": resolved.title,
                "doi": resolved.doi,
                "text": resolved.text,
                "pmid": resolved.pmid,
                "parser_name": resolved.parser_name,
                "page_count": resolved.page_count,
                "pages": [
                    {"page_number": item.page_number, "text": item.text}
                    for item in resolved.pages
                ],
                "sections": [list(item) for item in resolved.sections],
                "content_scope": resolved.content_scope,
                "authors": list(resolved.authors),
                "journal": resolved.journal,
                "publication_date": resolved.publication_date,
                "publication_types": list(resolved.publication_types),
                "source_url": resolved.source_url,
            },
            "extracted": {
                "title": self.extracted.title,
                "doi": self.extracted.doi,
                "primary_claim": self.extracted.primary_claim,
                "search_query": self.extracted.search_query,
                "additional_claims": list(self.extracted.additional_claims),
                "absolute_language": list(self.extracted.absolute_language),
                "extraction_model": self.extracted.extraction_model,
                "claims": [
                    {
                        "claim_id": claim.claim_id,
                        "text": claim.text,
                        "search_query": claim.search_query,
                        "quote": claim.quote,
                        "section": claim.section,
                        "page": claim.page,
                        "profile": claim.profile.to_payload() if claim.profile else None,
                    }
                    for claim in self.extracted.claims
                ],
                "primary_claim_quote": self.extracted.primary_claim_quote,
                "research_context": self.extracted.research_context,
                "primary_claim_section": self.extracted.primary_claim_section,
                "primary_claim_page": self.extracted.primary_claim_page,
            },
            "dossier": dict(self.dossier),
            "whole_article_analysis": (
                dict(self.whole_article_analysis)
                if self.whole_article_analysis is not None
                else None
            ),
        }

    @classmethod
    def from_workflow_payload(cls, payload: Mapping[str, Any]) -> "PreparedArticle":
        submission_data = payload["submission"]
        extracted_data = payload["extracted"]
        resolved_data = payload.get("resolved")
        submission = ArticleSubmission(
            reference=submission_data.get("reference"),
            reference_type=submission_data.get("reference_type"),
            file_name=submission_data.get("file_name"),
            mime_type=submission_data.get("mime_type"),
            content=None,
        )
        resolved = None
        if resolved_data is not None:
            resolved = ResolvedArticleDocument(
                title=resolved_data.get("title"),
                doi=resolved_data.get("doi"),
                text=resolved_data.get("text") or "",
                pmid=resolved_data.get("pmid"),
                parser_name=resolved_data.get("parser_name") or "persisted",
                page_count=resolved_data.get("page_count"),
                pages=tuple(
                    ParsedPage(item["page_number"], item["text"])
                    for item in resolved_data.get("pages") or ()
                ),
                sections=tuple(
                    (str(item[0]), str(item[1]))
                    for item in resolved_data.get("sections") or ()
                ),
                content_scope=resolved_data.get("content_scope") or "UNKNOWN",
                authors=tuple(resolved_data.get("authors") or ()),
                journal=resolved_data.get("journal"),
                publication_date=resolved_data.get("publication_date"),
                publication_types=tuple(resolved_data.get("publication_types") or ()),
                source_url=resolved_data.get("source_url"),
            )
        claims = tuple(
            ExtractedClaim(
                claim_id=item["claim_id"],
                text=item["text"],
                search_query=item.get("search_query") or item["text"],
                quote=item.get("quote"),
                section=item.get("section"),
                page=item.get("page"),
                profile=ClaimProfile.from_payload(item.get("profile")),
            )
            for item in extracted_data.get("claims") or ()
        )
        extracted = ExtractedArticle(
            title=extracted_data.get("title"),
            doi=extracted_data.get("doi"),
            primary_claim=extracted_data["primary_claim"],
            search_query=extracted_data.get("search_query") or extracted_data["primary_claim"],
            additional_claims=tuple(extracted_data.get("additional_claims") or ()),
            absolute_language=tuple(extracted_data.get("absolute_language") or ()),
            extraction_model=extracted_data.get("extraction_model") or "persisted",
            claims=claims,
            primary_claim_quote=extracted_data.get("primary_claim_quote"),
            research_context=extracted_data.get("research_context") or "UNKNOWN",
            primary_claim_section=extracted_data.get("primary_claim_section"),
            primary_claim_page=extracted_data.get("primary_claim_page"),
        )
        return cls(
            submission=submission,
            resolved=resolved,
            extracted=extracted,
            dossier=dict(payload.get("dossier") or {}),
            whole_article_analysis=payload.get("whole_article_analysis"),
        )


class ArticleIngestionError(RuntimeError):
    """O artigo não pôde ser lido de forma confiável."""


class OpenAccessArticleResolver:
    """Obtém o texto integral aberto do artigo enviado quando o PubMed não o tem.

    Evita depender da leitura indireta por URL do modelo, que não permite
    verificar citações nem garantir que o artigo inteiro foi lido.
    """

    def __init__(self, locator: Any, content_client: Any) -> None:
        self.locator = locator
        self.content_client = content_client

    def resolve(self, submission: ArticleSubmission) -> ResolvedArticleDocument | None:
        if not submission.reference or submission.reference_type == "pmid":
            return None
        doi = submission.reference if submission.reference_type == "doi" else None
        known_url = submission.reference if submission.reference.startswith("https://") else None
        lead = self.locator.locate(doi, known_url=known_url)
        candidates = list(lead.candidates)
        if doi and not candidates:
            from .full_text_sources import FullTextCandidate

            # A página do DOI costuma ser a cópia aberta em periódicos como o SciELO.
            candidates.append(FullTextCandidate(f"https://doi.org/{doi}", "DOI", False))
        for candidate in candidates[:4]:
            try:
                content = self.content_client.retrieve(
                    pmid=doi or submission.reference,
                    pmcid=lead.pmcid,
                    doi=doi,
                    pubmed_url=candidate.url,
                    full_text_url=candidate.url,
                    abstract=lead.abstract,
                )
            except Exception as error:  # cada fonte falha de um jeito diferente
                logger.info("Cópia aberta do artigo indisponível em %s: %s", candidate.source, error)
                continue
            if not content.full_text:
                continue
            pages = tuple(
                ParsedPage(section.page_number, section.text)
                for section in content.sections
                if section.page_number is not None
            )
            return ResolvedArticleDocument(
                title=None,
                doi=doi,
                text=content.full_text,
                parser_name=f"open-access:{candidate.source}",
                page_count=len(pages) or None,
                pages=pages,
                sections=tuple(
                    (section.title, section.text)
                    for section in content.sections
                    if section.page_number is None
                ),
                content_scope="OPEN_ACCESS_FULL_TEXT",
                source_url=content.pmc_url or candidate.url,
            )
        return None


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
        match = re.fullmatch(r"/(?:pubmed/)?(\d{1,10})/?", parsed.path)
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
                # Sem o PubMed, as fontes abertas ainda podem fornecer o artigo.
                logger.warning("PubMed indisponível ao resolver o DOI: %s", error)
                return None
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
            if submission.reference_type == "doi":
                logger.warning("PubMed/PMC indisponível para o PMID %s: %s", pmid, error)
                return None
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
    if re.fullmatch(r"\d{1,10}", normalized):
        return f"https://pubmed.ncbi.nlm.nih.gov/{normalized}/", "url"
    possible_doi = DOI_PREFIX_PATTERN.sub("", normalized).strip()
    if DOI_PATTERN.fullmatch(possible_doi):
        return possible_doi, "doi"
    parsed = urlparse(normalized)
    if (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"pubmed.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"}
        and re.fullmatch(r"/(?:pubmed/)?\d{1,10}/?", parsed.path)
    ):
        return normalized, "url"
    raise InputValidationError(
        "Informe um PMID, DOI ou link de artigo do PubMed válido."
    )


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
        raise InputValidationError("O arquivo deve ter no máximo 25 MB.")
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
                **claim_profile_schema(),
            },
            "required": ["text", "quote", "search_query", *claim_profile_schema()],
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
            "Escreva text, primary_claim e additional_claims em português do Brasil mesmo "
            "quando o artigo estiver em outro idioma; quote continua literal no idioma "
            "original. "
            "Inclua obrigatoriamente a conclusão ou interpretação central dos autores, "
            "inclusive associações causais apenas sugeridas na discussão (por exemplo, a "
            "ligação temporal com uma vacina, droga ou exposição), porque costuma ser a "
            "alegação de maior repercussão pública; dê a ela importance HIGH. "
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
            "o desenho do artigo; BASIC_SCIENCE não deve ser tratado como ensaio clínico. "
            + CLAIM_PROFILE_INSTRUCTIONS
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
        # Com url_context o Gemini às vezes devolve candidato sem partes; repetir costuma bastar.
        for attempt in range(2):
            response = self.gateway._post_json(endpoint, payload)
            try:
                response_text = self.gateway._response_text(response)
                break
            except GeminiAnalysisError as error:
                if attempt == 1 and "tools" in payload:
                    raise GeminiAnalysisError(
                        "Não foi possível ler o artigo pelo link e nenhuma cópia aberta foi "
                        "encontrada. Envie o PDF para uma leitura integral."
                    ) from error
                if attempt == 1:
                    raise
                logger.warning("Resposta Gemini vazia na extração de alegações; repetindo.")
        try:
            decoded = json.loads(response_text)
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
                    profile=(
                        parse_claim_profile(raw_claim)
                        if raw_claim.get("concept_groups") or raw_claim.get("claim_type")
                        else None
                    ),
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
        search_queries: tuple[str, ...] = (),
        depth: str = "QUICK",
        claim_profile: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


class WholeArticleAnalyzer(Protocol):
    def analyze(
        self,
        submission: ArticleSubmission,
        resolved: ResolvedArticleDocument | None,
    ) -> Mapping[str, Any]: ...


class ArticleFirstAnalysisRunner:
    """Extrai a alegação do documento e só então busca evidências independentes."""

    def __init__(
        self,
        extractor: GeminiArticleExtractor,
        evidence_runner: IndependentEvidenceRunner,
        reference_resolver: PubMedReferenceResolver | None = None,
        document_parser: LiteParseDocumentParser | None = None,
        whole_article_analyzer: WholeArticleAnalyzer | None = None,
        claim_structurer: GeminiClaimStructurer | None = None,
        open_access_resolver: OpenAccessArticleResolver | None = None,
        pubmed_only: bool = False,
    ) -> None:
        self.extractor = extractor
        self.evidence_runner = evidence_runner
        self.reference_resolver = reference_resolver
        self.document_parser = document_parser
        self.whole_article_analyzer = whole_article_analyzer
        self.claim_structurer = claim_structurer
        self.open_access_resolver = open_access_resolver
        self.pubmed_only = pubmed_only

    @staticmethod
    def _submitted_population(whole_article_analysis: Mapping[str, Any] | None) -> list[str]:
        study = (whole_article_analysis or {}).get("study") or {}
        values = [*(study.get("registration_ids") or ()), study.get("cohort_or_dataset") or ""]
        return [
            " ".join(str(value).split())
            for value in values
            if str(value).strip() and str(value).strip().casefold() != "não informado"
        ]

    def _restructure_edited(
        self,
        claim: ExtractedClaim,
        extracted: ExtractedArticle,
    ) -> ExtractedClaim:
        """Texto editado invalida PICO e conceitos extraídos; refaz antes da busca."""

        if not claim.edited or self.claim_structurer is None:
            return claim
        try:
            with logged_step(logger, "claim_restructuring", claim_id=claim.claim_id):
                profile = self.claim_structurer.structure(
                    claim.text,
                    context=extracted.title or "",
                )
        except GeminiAnalysisError as error:
            logger.warning("Reestruturação da alegação editada falhou: %s", error)
            return replace(claim, profile=None)
        return replace(claim, profile=profile)

    @staticmethod
    def _claim_payload(claim: ExtractedClaim) -> dict[str, Any]:
        return {
            "claim_id": claim.claim_id,
            "text": claim.text,
            "search_query": claim.search_query,
            "quote": claim.quote,
            "section": claim.section,
            "page": claim.page,
            "edited": claim.edited,
            "profile": claim.profile.to_payload() if claim.profile else None,
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
            assess_methodology=False,
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

    def prepare_article(self, submission: ArticleSubmission) -> PreparedArticle:
        with logged_step(
            logger,
            "article_resolution",
            source_type=submission.reference_type or submission.mime_type,
        ) as step:
            resolved = (
                self.reference_resolver.resolve(submission)
                if self.reference_resolver is not None
                else None
            )
            step["resolved"] = resolved is not None
        if self.pubmed_only and submission.reference and resolved is None:
            raise ArticleIngestionError(
                "Não foi possível obter o artigo pelo PubMed/PMC. "
                "Confira o DOI ou link do PubMed, ou envie o PDF."
            )
        if resolved is None and self.open_access_resolver is not None:
            with logged_step(logger, "open_access_article_resolution") as step:
                try:
                    resolved = self.open_access_resolver.resolve(submission)
                except Exception as error:
                    logger.warning("Resolução aberta do artigo falhou: %s", error)
                    resolved = None
                step["resolved"] = resolved is not None
                step["parser"] = resolved.parser_name if resolved else None
        if (
            resolved is None
            and submission.mime_type == "application/pdf"
            and submission.content is not None
            and self.document_parser is not None
        ):
            try:
                with logged_step(logger, "document_parsing") as step:
                    parsed = self.document_parser.parse_pdf(submission.content)
                    step["page_count"] = parsed.page_count
                    step["parser"] = parsed.parser_name
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
        with logged_step(logger, "claim_extraction") as step:
            extracted = self.extractor.extract(submission, resolved)
            step["claim_count"] = len(extracted.claims) or 1
            step["research_context"] = extracted.research_context
        with logged_step(logger, "article_dossier") as step:
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
                llm_context=None if self.pubmed_only else extracted.research_context,
                absolute_language=extracted.absolute_language,
                source_url=(resolved.source_url if resolved else submission.reference),
            )
            step["identity_status"] = dossier["identity"]["status"]
            step["retraction_status"] = dossier["editorial_status"]["retraction"]
        whole_article_analysis: Mapping[str, Any] | None = None
        if self.whole_article_analyzer is not None:
            try:
                with logged_step(logger, "whole_article_analysis") as step:
                    whole_article_analysis = self.whole_article_analyzer.analyze(
                        submission, resolved
                    )
                    coverage = whole_article_analysis.get("coverage") or {}
                    step["full_article_available"] = coverage.get(
                        "full_article_available"
                    )
                    step["section_coverage_percentage"] = coverage.get(
                        "section_coverage_percentage"
                    )
            except Exception as error:
                logger.warning(
                    "Dossiê integral indisponível: %s",
                    error,
                    exc_info=True,
                )
                whole_article_analysis = {
                    "status": "UNAVAILABLE",
                    "error": str(error),
                    "coverage": {
                        "content_scope": (
                            resolved.content_scope if resolved else "URL_CONTEXT_UNVERIFIED"
                        ),
                        "full_article_available": bool(
                            resolved
                            and resolved.content_scope
                            in {"FULL_TEXT", "OPEN_ACCESS_FULL_TEXT", "LOCAL_PDF_FULL_TEXT"}
                        ),
                        "page_count": resolved.page_count if resolved else None,
                    },
                }
        return PreparedArticle(
            submission=submission,
            resolved=resolved,
            extracted=extracted,
            dossier=dossier,
            whole_article_analysis=whole_article_analysis,
        )

    @staticmethod
    def _claims_for(extracted: ExtractedArticle) -> tuple[ExtractedClaim, ...]:
        return extracted.claims or (
            ExtractedClaim(
                claim_id="claim-01",
                text=extracted.primary_claim,
                search_query=extracted.search_query,
                quote=extracted.primary_claim_quote,
                section=extracted.primary_claim_section,
                page=extracted.primary_claim_page,
            ),
        )

    def preparation_result(self, prepared: PreparedArticle) -> dict[str, Any]:
        claims = self._claims_for(prepared.extracted)
        result: dict[str, Any] = {
            "workflow": {
                "stage": "CLAIM_SELECTION",
                "message": (
                    "Revise, edite e selecione as alegações que devem ser "
                    "comparadas com evidência externa."
                ),
            },
            "input": {
                "type": "article",
                "source": prepared.submission.label,
                "source_type": (
                    prepared.submission.reference_type or prepared.submission.mime_type
                ),
            },
            "submitted_article": self._submitted_article_payload(
                extracted=prepared.extracted,
                active_claim=claims[0],
                submission=prepared.submission,
                resolved=prepared.resolved,
                include_all_claims=True,
            ),
            "article_dossier": dict(prepared.dossier),
            "research_estimates": research_estimates(
                getattr(getattr(self.extractor, "gateway", None), "model_name", None)
            ),
        }
        # O fallback criado por _claims_for também precisa aparecer para seleção.
        result["submitted_article"]["claims"] = [
            self._claim_payload(claim) for claim in claims
        ]
        if prepared.whole_article_analysis is not None:
            result["whole_article_analysis"] = dict(prepared.whole_article_analysis)
        return result

    def analyze_prepared(
        self,
        prepared: PreparedArticle,
        selected_claims: tuple[ExtractedClaim, ...] | None = None,
        depth: str = "QUICK",
    ) -> Mapping[str, Any]:
        submission = prepared.submission
        resolved = prepared.resolved
        extracted = prepared.extracted
        dossier = prepared.dossier
        whole_article_analysis = prepared.whole_article_analysis
        excluded = (extracted.doi,) if extracted.doi else ()
        claims = tuple(
            self._restructure_edited(claim, extracted)
            for claim in (selected_claims or self._claims_for(extracted))
        )
        claim_analyses: list[dict[str, Any]] = []
        for claim in claims:
            search_queries = (
                boolean_queries(claim.profile.concept_groups) if claim.profile else ()
            )
            with logged_step(
                logger,
                "independent_evidence",
                claim_id=claim.claim_id,
            ) as step:
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
                        search_queries=search_queries,
                        depth=depth,
                        claim_profile=(
                            claim.profile.to_payload() if claim.profile else None
                        ),
                    )
                )
                step["article_count"] = len(claim_result.get("articles") or ())
            submitted_population = self._submitted_population(whole_article_analysis)
            if submitted_population and claim_result.get("weighted_evidence") is not None:
                reproducibility = dict(claim_result.get("reproducibility") or {})
                reproducibility["submitted_population"] = submitted_population
                claim_result["reproducibility"] = reproducibility
                claim_result["weighted_evidence"] = synthesize_evidence(
                    claim_result.get("articles") or (),
                    candidate_count=(claim_result.get("search") or {}).get("candidate_count", 0),
                    claim_profile=reproducibility.get("claim_profile"),
                    submitted_population=submitted_population,
                    queries=reproducibility.get("queries") or (),
                    sources=list(
                        dict.fromkeys(
                            source
                            for article in claim_result.get("articles") or ()
                            for source in (article.get("retrieval") or {}).get("sources") or ()
                        )
                    ),
                    assess_methodology=False,
                )
            with logged_step(
                logger,
                "result_enrichment",
                claim_id=claim.claim_id,
            ):
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
        result["reproducibility"] = {
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "depth": depth,
            "extraction_model": extracted.extraction_model,
            "dossier_model": (whole_article_analysis or {}).get("model_name"),
            "content_scope": resolved.content_scope if resolved else "URL_CONTEXT_UNVERIFIED",
            "parser": resolved.parser_name if resolved else None,
            "selected_claims": [claim.claim_id for claim in claims],
            "edited_claims": [claim.claim_id for claim in claims if claim.edited],
        }
        if whole_article_analysis is not None:
            result["whole_article_analysis"] = dict(whole_article_analysis)
        result["user_summary"] = build_user_summary(result)
        return result

    def analyze_article(self, submission: ArticleSubmission) -> Mapping[str, Any]:
        """Compatibilidade: executa o fluxo completo quando não há etapa humana."""

        prepared = self.prepare_article(submission)
        return self.analyze_prepared(prepared)
