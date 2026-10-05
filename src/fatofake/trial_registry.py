"""Consulta ao ClinicalTrials.gov: ensaios registrados e sem resultados publicados.

Registros mostram pesquisa em andamento ou não publicada; ajudam a separar
"não encontrado na literatura" de "não estudado" e a sinalizar viés de publicação.
"""

from __future__ import annotations

import json
import logging
import ssl
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .transport import default_ssl_context


logger = logging.getLogger(__name__)

CLINICAL_TRIALS_URL = "https://clinicaltrials.gov/api/v2/studies"
INTERVENTIONAL_TYPES = frozenset({"THERAPEUTIC", "PREVENTIVE"})


def _term(groups: Sequence[Sequence[str]]) -> str:
    clauses = []
    for group in groups[:3]:
        terms = [f'"{term}"' if " " in term else term for term in group[:3]]
        clauses.append("(" + " OR ".join(terms) + ")" if len(terms) > 1 else terms[0])
    return " AND ".join(clauses)


class ClinicalTrialsRegistry:
    def __init__(
        self,
        *,
        timeout: float = 15.0,
        get_json: Callable[[str], Mapping[str, Any]] | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.timeout = timeout
        self._ssl_context = ssl_context or default_ssl_context()
        self._get_json = get_json or self._request_json

    def _request_json(self, url: str) -> Mapping[str, Any]:
        request = Request(url, headers={"User-Agent": "FatoOuFake/0.1", "Accept": "application/json"})
        with urlopen(request, timeout=self.timeout, context=self._ssl_context) as response:
            return json.loads(response.read(5_000_000).decode("utf-8"))

    def summarize(self, claim_profile: Mapping[str, Any] | None) -> dict[str, Any] | None:
        profile = claim_profile or {}
        groups = profile.get("concept_groups") or []
        if profile.get("claim_type") not in INTERVENTIONAL_TYPES or len(groups) < 2:
            return None
        term = _term(groups)
        params = urlencode(
            {
                "query.term": term,
                "countTotal": "true",
                "pageSize": "6",
                "fields": "NCTId,BriefTitle,OverallStatus,HasResults,StartDate,Phase,EnrollmentInfo",
            }
        )
        try:
            payload = self._get_json(f"{CLINICAL_TRIALS_URL}?{params}")
            with_results = self._get_json(
                f"{CLINICAL_TRIALS_URL}?{urlencode({'query.term': term, 'countTotal': 'true', 'pageSize': '1', 'aggFilters': 'results:with'})}"
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            logger.info("ClinicalTrials.gov indisponível: %s", error)
            return {"status": "UNAVAILABLE", "query": term}
        total = int(payload.get("totalCount") or 0)
        results_total = int(with_results.get("totalCount") or 0)
        examples = []
        for study in payload.get("studies") or []:
            protocol = study.get("protocolSection") or {}
            identification = protocol.get("identificationModule") or {}
            status = protocol.get("statusModule") or {}
            design = protocol.get("designModule") or {}
            nct = identification.get("nctId")
            if not nct:
                continue
            examples.append(
                {
                    "nct_id": nct,
                    "title": identification.get("briefTitle"),
                    "status": status.get("overallStatus"),
                    "start_date": (status.get("startDateStruct") or {}).get("date"),
                    "phases": design.get("phases") or [],
                    "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
                    "has_results": bool(study.get("hasResults")),
                    "url": f"https://clinicaltrials.gov/study/{nct}",
                }
            )
        return {
            "status": "OK",
            "query": term,
            "registered_count": total,
            "with_results_count": results_total,
            "without_results_count": max(0, total - results_total),
            "examples": examples,
            "note": (
                "Ensaios registrados sem resultados podem indicar estudos em andamento "
                "ou não publicados (possível viés de publicação)."
            ),
        }
