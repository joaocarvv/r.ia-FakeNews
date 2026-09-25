"""Valida sinais externos usados no perfil preliminar de qualidade científica."""

from __future__ import annotations

import json
import re
import ssl
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .crossref import CrossrefClient, CrossrefError, verify_publication_identity
from .evidence_synthesis import ArticleQualityProfile, QualityLevel
from .pmc import ArticleContent
from .pubmed import Publication
from .retrieval import RetrievalError
from .transport import default_ssl_context


DATACITE_API_URL = "https://api.datacite.org/dois"
CLINICAL_TRIALS_API_URL = "https://clinicaltrials.gov/api/v2/studies"
JsonFetcher = Callable[[str, Mapping[str, str]], Mapping[str, Any]]


class ValidationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class StudyDesign(str, Enum):
    SYSTEMATIC_REVIEW_META_ANALYSIS = "SYSTEMATIC_REVIEW_META_ANALYSIS"
    RANDOMIZED_CLINICAL_TRIAL = "RANDOMIZED_CLINICAL_TRIAL"
    OBSERVATIONAL = "OBSERVATIONAL"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ExternalServiceError(RuntimeError):
    """Falha ao consultar ou interpretar um serviço externo de validação."""


@dataclass(frozen=True)
class DatasetRecord:
    doi: str
    title: str
    relation_type: str
    url: str


@dataclass(frozen=True)
class TrialRegistration:
    nct_id: str
    overall_status: str | None
    has_results: bool
    url: str


@dataclass(frozen=True)
class QualityCheck:
    name: str
    status: ValidationStatus
    summary: str
    source_url: str


@dataclass(frozen=True)
class ArticleQualityReport:
    pmid: str
    doi: str | None
    study_design: StudyDesign
    quality_level: QualityLevel
    checks: tuple[QualityCheck, ...]
    datasets: tuple[DatasetRecord, ...]
    trial_registrations: tuple[TrialRegistration, ...]
    rationale: str

    def to_quality_profile(self, publication: Publication) -> ArticleQualityProfile:
        return ArticleQualityProfile(
            pmid=self.pmid,
            level=self.quality_level,
            study_design=self.study_design.value,
            rationale=self.rationale,
            source_url=publication.url,
        )


class _JsonClient:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        fetch_json: JsonFetcher | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.timeout = timeout
        self._fetch_json = fetch_json or self._request_json
        self._ssl_context = ssl_context or default_ssl_context()

    def _request_json(self, url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(f"{url}{query}", headers={"User-Agent": "FatoOuFake/0.1"})
        try:
            with urlopen(request, timeout=self.timeout, context=self._ssl_context) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ExternalServiceError(f"Falha ao consultar {url}: {error}") from error
        if not isinstance(payload, dict):
            raise ExternalServiceError("O serviço externo retornou JSON inesperado.")
        return payload


class DataCiteClient(_JsonClient):
    """Busca datasets explicitamente ligados ao DOI do artigo."""

    _DATA_RELATIONS = {
        "IsCitedBy",
        "IsDescribedBy",
        "IsDocumentedBy",
        "IsReferencedBy",
        "IsSourceOf",
        "IsSupplementTo",
    }

    def find_related_datasets(self, article_doi: str) -> tuple[DatasetRecord, ...]:
        normalized_doi = article_doi.strip().casefold()
        payload = self._fetch_json(
            DATACITE_API_URL,
            {
                "query": f"relatedIdentifiers.relatedIdentifier:{normalized_doi}",
                "resource-type-id": "dataset",
                "page[size]": "25",
            },
        )
        records: list[DatasetRecord] = []
        for item in payload.get("data") or []:
            attributes = item.get("attributes") or {}
            matching_relation = next(
                (
                    relation
                    for relation in attributes.get("relatedIdentifiers") or []
                    if str(relation.get("relatedIdentifier") or "").strip().casefold()
                    == normalized_doi
                    and relation.get("relationType") in self._DATA_RELATIONS
                ),
                None,
            )
            if not matching_relation:
                continue
            titles = attributes.get("titles") or []
            title = str(titles[0].get("title") or "Dataset sem título").strip()
            doi = str(attributes.get("doi") or item.get("id") or "").strip()
            if doi:
                records.append(
                    DatasetRecord(
                        doi=doi,
                        title=title,
                        relation_type=str(matching_relation["relationType"]),
                        url=str(attributes.get("url") or f"https://doi.org/{doi}"),
                    )
                )
        return tuple(records)


class ClinicalTrialsClient(_JsonClient):
    """Confere registros somente quando o artigo fornece um NCT explícito."""

    def fetch_registration(self, nct_id: str) -> TrialRegistration:
        normalized = nct_id.strip().upper()
        payload = self._fetch_json(f"{CLINICAL_TRIALS_API_URL}/{normalized}", {})
        try:
            protocol = payload["protocolSection"]
            returned_id = protocol["identificationModule"]["nctId"]
        except (KeyError, TypeError) as error:
            raise ExternalServiceError("Registro ClinicalTrials.gov incompleto.") from error
        status = (protocol.get("statusModule") or {}).get("overallStatus")
        return TrialRegistration(
            nct_id=str(returned_id),
            overall_status=str(status) if status else None,
            has_results=bool(payload.get("hasResults")),
            url=f"https://clinicaltrials.gov/study/{returned_id}",
        )


def detect_study_design(title: str, abstract: str | None) -> StudyDesign:
    text = f"{title} {abstract or ''}".casefold()
    if "systematic review" in text and "meta-analysis" in text:
        return StudyDesign.SYSTEMATIC_REVIEW_META_ANALYSIS
    if re.search(r"randomi[sz]ed(?: controlled)? trial", text):
        return StudyDesign.RANDOMIZED_CLINICAL_TRIAL
    if any(term in text for term in ("cohort study", "case-control", "cross-sectional")):
        return StudyDesign.OBSERVATIONAL
    return StudyDesign.UNKNOWN


def _check(name: str, status: ValidationStatus, summary: str, source: str) -> QualityCheck:
    return QualityCheck(name=name, status=status, summary=summary, source_url=source)


def validate_article_quality(
    publication: Publication,
    content: ArticleContent,
    crossref_client: CrossrefClient,
    datacite_client: DataCiteClient,
    clinical_trials_client: ClinicalTrialsClient,
) -> ArticleQualityReport:
    """Executa verificações independentes e mantém ausências como inconclusivas."""

    checks: list[QualityCheck] = []
    design = detect_study_design(publication.title, content.abstract)
    design_status = ValidationStatus.CONFIRMED if design is not StudyDesign.UNKNOWN else ValidationStatus.UNKNOWN
    checks.append(
        _check(
            "study_design",
            design_status,
            f"Desenho identificado de forma conservadora: {design.value}.",
            publication.url,
        )
    )

    try:
        identity = verify_publication_identity(publication, crossref_client)
        identity_status = (
            ValidationStatus.CONFIRMED
            if identity.status == "VERIFIED"
            else ValidationStatus.NOT_FOUND
            if identity.status == "NOT_FOUND"
            else ValidationStatus.UNKNOWN
        )
        checks.append(_check("identity", identity_status, identity.reason, identity.crossref_url or publication.url))
        retractions = [
            update for update in identity.crossref_updates if update.update_type == "retraction"
        ]
        if identity.status in {"NOT_FOUND", "NOT_CHECKED"}:
            checks.append(
                _check(
                    "retraction",
                    ValidationStatus.UNKNOWN,
                    "Não foi possível associar um registro Crossref para consultar retratações.",
                    publication.url,
                )
            )
        else:
            checks.append(
                _check(
                    "retraction",
                    ValidationStatus.CONFIRMED if retractions else ValidationStatus.NOT_FOUND,
                    (
                        f"Crossref/Retraction Watch informou {len(retractions)} retratação(ões)."
                        if retractions
                        else "Nenhuma retratação foi localizada no registro consultado; ausência não prova inexistência."
                    ),
                    identity.crossref_url or publication.url,
                )
            )
    except CrossrefError as error:
        checks.extend(
            (
                _check("identity", ValidationStatus.UNKNOWN, str(error), publication.url),
                _check("retraction", ValidationStatus.UNKNOWN, str(error), publication.url),
            )
        )
        retractions = []

    datasets: tuple[DatasetRecord, ...] = ()
    if publication.doi:
        try:
            datasets = datacite_client.find_related_datasets(publication.doi)
            checks.append(
                _check(
                    "data_availability",
                    ValidationStatus.CONFIRMED if datasets else ValidationStatus.NOT_FOUND,
                    (
                        f"DataCite informou {len(datasets)} dataset(s) com relação explícita ao artigo."
                        if datasets
                        else "Nenhum dataset com relação qualificadora foi localizado; isso não prova que os dados não existam."
                    ),
                    "https://api.datacite.org/",
                )
            )
        except ExternalServiceError as error:
            checks.append(_check("data_availability", ValidationStatus.UNKNOWN, str(error), "https://api.datacite.org/"))
    else:
        checks.append(_check("data_availability", ValidationStatus.UNKNOWN, "Artigo sem DOI para consulta no DataCite.", publication.url))

    registrations: list[TrialRegistration] = []
    if design is StudyDesign.RANDOMIZED_CLINICAL_TRIAL:
        nct_ids = tuple(dict.fromkeys(re.findall(r"\bNCT\d{8}\b", f"{publication.title} {content.abstract or ''}", re.I)))
        if not nct_ids:
            checks.append(_check("trial_registration", ValidationStatus.NOT_FOUND, "Nenhum identificador NCT explícito foi localizado.", publication.url))
        else:
            try:
                registrations = [clinical_trials_client.fetch_registration(nct_id) for nct_id in nct_ids]
                checks.append(_check("trial_registration", ValidationStatus.CONFIRMED, f"{len(registrations)} registro(s) NCT confirmado(s).", registrations[0].url))
            except ExternalServiceError as error:
                checks.append(_check("trial_registration", ValidationStatus.UNKNOWN, str(error), "https://clinicaltrials.gov/"))
    else:
        checks.append(_check("trial_registration", ValidationStatus.NOT_APPLICABLE, "A conferência de protocolo NCT aplica-se a ensaios clínicos, não a este desenho.", "https://clinicaltrials.gov/"))

    checks.append(
        _check(
            "full_text",
            ValidationStatus.CONFIRMED if content.full_text else ValidationStatus.NOT_FOUND,
            "Texto completo disponível no PMC." if content.full_text else "Somente resumo disponível.",
            content.pmc_url or content.pubmed_url,
        )
    )
    quality_level = QualityLevel.LOW if retractions else QualityLevel.UNCLEAR
    rationale = (
        "Há registro de retratação; o artigo não deve sustentar a síntese sem revisão humana."
        if retractions
        else "Metadados externos foram verificados, mas a qualidade permanece não esclarecida até uma avaliação estruturada de risco de viés."
    )
    return ArticleQualityReport(
        pmid=publication.pmid,
        doi=publication.doi,
        study_design=design,
        quality_level=quality_level,
        checks=tuple(checks),
        datasets=datasets,
        trial_registrations=tuple(registrations),
        rationale=rationale,
    )
