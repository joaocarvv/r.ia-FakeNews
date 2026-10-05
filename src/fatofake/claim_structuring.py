"""Estrutura cada alegação em tipo, PICO, importância e conceitos de busca."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .gemini_evidence import GEMINI_API_BASE_URL, GeminiAnalysisError, GeminiEvidenceAnalyzer


CLAIM_TYPES = (
    "CAUSAL",
    "THERAPEUTIC",
    "DIAGNOSTIC",
    "PROGNOSTIC",
    "PREVENTIVE",
    "ASSOCIATION",
    "PREVALENCE",
    "MECHANISTIC",
    "OTHER",
)
CLAIM_TYPE_LABELS = {
    "CAUSAL": "Causal",
    "THERAPEUTIC": "Terapêutica",
    "DIAGNOSTIC": "Diagnóstica",
    "PROGNOSTIC": "Prognóstica",
    "PREVENTIVE": "Preventiva",
    "ASSOCIATION": "Associação",
    "PREVALENCE": "Prevalência/frequência",
    "MECHANISTIC": "Mecanismo",
    "OTHER": "Outra",
}
IMPORTANCE_LEVELS = ("HIGH", "MEDIUM", "LOW")

# Palavras sem valor de busca no PubMed quando a consulta vem de tradução livre.
ENGLISH_STOPWORDS = frozenset(
    """a an and are as at be been being by can could do does for from had has have
    in into is it its may might must not of on only or our should such than that the
    their them then there these they this those to was were which while who will with
    would also more less very most both each other some any all no""".split()
)


@dataclass(frozen=True)
class ClaimProfile:
    claim_type: str = "OTHER"
    population: str = ""
    intervention: str = ""
    comparator: str = ""
    outcome: str = ""
    importance: str = "MEDIUM"
    importance_reason: str = ""
    # Cada grupo é um conceito; os termos do grupo são sinônimos em inglês.
    concept_groups: tuple[tuple[str, ...], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "claim_type": self.claim_type,
            "claim_type_label": CLAIM_TYPE_LABELS.get(self.claim_type, "Outra"),
            "population": self.population,
            "intervention": self.intervention,
            "comparator": self.comparator,
            "outcome": self.outcome,
            "importance": self.importance,
            "importance_reason": self.importance_reason,
            "concept_groups": [list(group) for group in self.concept_groups],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "ClaimProfile | None":
        if not payload:
            return None
        return parse_claim_profile(payload)


def claim_profile_schema() -> dict[str, Any]:
    """Fragmento de schema reaproveitado pela extração e pela reestruturação."""

    return {
        "claim_type": {"type": "STRING", "enum": list(CLAIM_TYPES)},
        "population": {"type": "STRING"},
        "intervention": {"type": "STRING"},
        "comparator": {"type": "STRING"},
        "outcome": {"type": "STRING"},
        "importance": {"type": "STRING", "enum": list(IMPORTANCE_LEVELS)},
        "importance_reason": {"type": "STRING"},
        "concept_groups": {
            "type": "ARRAY",
            "items": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
    }


CLAIM_PROFILE_INSTRUCTIONS = (
    "Cada alegação deve ser autocontida: inclua a população e a condição que a "
    "definem (por exemplo, 'crianças com transtorno do desenvolvimento' em vez de "
    "'as 12 crianças avaliadas'), sem pronomes nem referências ao próprio estudo. "
    "Para cada alegação, classifique claim_type (CAUSAL, THERAPEUTIC, DIAGNOSTIC, "
    "PROGNOSTIC, PREVENTIVE, ASSOCIATION, PREVALENCE, MECHANISTIC ou OTHER) e "
    "preencha population, intervention (intervenção ou exposição), comparator e "
    "outcome em português, usando string vazia quando o elemento não existir. "
    "importance indica o peso da alegação para a conclusão do artigo (HIGH, MEDIUM, "
    "LOW) e importance_reason explica em uma frase. concept_groups lista de 2 a 4 "
    "conceitos essenciais para buscar no PubMed, incluindo sempre a condição ou "
    "população que define o estudo, nesta ordem: primeiro a intervenção ou "
    "exposição (quando houver), depois a condição ou população, depois o desfecho; "
    "cada conceito é uma lista de 1 a 4 "
    "sinônimos em inglês (preferindo termos MeSH), sem números, desfechos "
    "numéricos ou palavras como 'study' e 'patients'."
)


def _clean(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def parse_claim_profile(raw: Mapping[str, Any]) -> ClaimProfile:
    claim_type = _clean(raw.get("claim_type")).upper()
    importance = _clean(raw.get("importance")).upper()
    groups: list[tuple[str, ...]] = []
    for raw_group in raw.get("concept_groups") or ():
        if isinstance(raw_group, str):
            raw_group = [raw_group]
        if not isinstance(raw_group, (list, tuple)):
            continue
        terms = tuple(
            dict.fromkeys(
                term
                for term in (_clean(item, 80) for item in raw_group[:4])
                if len(term) >= 2 and not re.search(r"[\"()]", term)
            )
        )
        if terms:
            groups.append(terms)
    return ClaimProfile(
        claim_type=claim_type if claim_type in CLAIM_TYPES else "OTHER",
        population=_clean(raw.get("population")),
        intervention=_clean(raw.get("intervention")),
        comparator=_clean(raw.get("comparator")),
        outcome=_clean(raw.get("outcome")),
        importance=importance if importance in IMPORTANCE_LEVELS else "MEDIUM",
        importance_reason=_clean(raw.get("importance_reason"), 400),
        concept_groups=tuple(groups[:4]),
    )


def _quote_term(term: str) -> str:
    return f'"{term}"' if " " in term or "-" in term else term


def boolean_queries(groups: Sequence[Sequence[str]]) -> tuple[str, ...]:
    """Monta consultas PubMed: todos os conceitos e, se houver, sem o último."""

    clauses = [
        "(" + " OR ".join(_quote_term(term) for term in group) + ")"
        if len(group) > 1
        else _quote_term(group[0])
        for group in groups
        if group
    ]
    if not clauses:
        return ()
    queries = [" AND ".join(clauses)]
    # Uma versão mais ampla evita zero resultados quando o desfecho é específico demais.
    if len(clauses) >= 3:
        queries.append(" AND ".join(clauses[:-1]))
    return tuple(query[:300] for query in queries)


def english_keywords(text: str) -> str:
    terms = [
        token
        for token in re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
        if len(token) >= 3 and token not in ENGLISH_STOPWORDS
    ]
    return " ".join(dict.fromkeys(terms))[:300]


class GeminiClaimStructurer:
    """Reestrutura alegações editadas pelo usuário antes da busca externa."""

    def __init__(self, gateway: GeminiEvidenceAnalyzer) -> None:
        self.gateway = gateway

    @property
    def model_name(self) -> str:
        return self.gateway.model_name

    def structure(self, claim: str, *, context: str = "") -> ClaimProfile:
        prompt = (
            "Estruture a ALEGAÇÃO científica abaixo para uma revisão de literatura, "
            "respondendo em português do Brasil (exceto concept_groups, em inglês). "
            "Não julgue se ela é verdadeira. Preserve exatamente o sentido, inclusive "
            "restrições como 'apenas', 'sempre' e faixas de tamanho ou idade. "
            + CLAIM_PROFILE_INSTRUCTIONS
            + ("\n\nCONTEXTO DO ARTIGO:\n" + context[:1500] if context else "")
            + "\n\nALEGAÇÃO:\n"
            + claim.strip()
        )
        properties = claim_profile_schema()
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": properties,
                    "required": list(properties),
                },
            },
        }
        response = self.gateway._post_json(
            f"{GEMINI_API_BASE_URL}/{self.gateway.model_name}:generateContent",
            payload,
        )
        try:
            decoded = json.loads(self.gateway._response_text(response))
        except json.JSONDecodeError as error:
            raise GeminiAnalysisError("A estruturação da alegação retornou JSON inválido.") from error
        if not isinstance(decoded, dict):
            raise GeminiAnalysisError("A estruturação da alegação retornou formato inesperado.")
        return parse_claim_profile(decoded)
