"""Gera e executa os artefatos da entrega acadêmica do modelo de recuperação."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import nbformat
from nbclient import NotebookClient


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "entrega_modelo_ia"
NOTEBOOK = DELIVERY / "01_modelo_bm25_validacao.ipynb"


def markdown(text: str) -> nbformat.NotebookNode:
    return nbformat.v4.new_markdown_cell(text.strip())


def code(text: str) -> nbformat.NotebookNode:
    return nbformat.v4.new_code_cell(text.strip())


def build_notebook() -> nbformat.NotebookNode:
    cells = [
        markdown(
            """
# Modelo de recuperação de evidências — treinamento e validação

## tl;dr

Este notebook reproduz a preparação, o ajuste ao corpus, a serialização, o carregamento e a avaliação do **índice BM25** usado como baseline do projeto ArtFact. A validação foi ampliada para **22 documentos científicos e 14 consultas**, incluindo casos com um ou vários documentos relevantes e duas consultas fora do domínio. Avaliamos o ranking em `k=1`, `k=3` e `k=5`, porque observar somente a primeira posição poderia esconder documentos relevantes encontrados logo abaixo.

**Precision@k** é a proporção de resultados relevantes entre as `k` primeiras posições; nós a usamos para medir quanto do que o sistema entrega é útil e a calculamos como `relevantes recuperados ÷ k`. **Recall@k** é a proporção de todos os documentos relevantes conhecidos que apareceu até a posição `k`; ele mostra o quanto da evidência disponível foi coberta e é calculado como `relevantes recuperados ÷ relevantes existentes`. **MRR (Mean Reciprocal Rank)** mede quão cedo aparece o primeiro resultado relevante; usamos essa métrica porque o topo recebe mais atenção, calculando `1 ÷ posição do primeiro relevante` e depois a média entre as consultas. **nDCG@k** avalia a qualidade da ordem completa até `k`, aplicando desconto às posições mais baixas e comparando o ranking obtido com o ranking ideal normalizado. A **taxa de abstinência** é a parcela de consultas sem retorno; ela é usada para verificar se o modelo evita apresentar evidências sem relação, mas deve ser interpretada junto do acerto nos casos fora do domínio, pois uma taxa alta ou baixa isoladamente não significa qualidade.

Os resultados desta amostra validam o funcionamento técnico do pipeline de recuperação; **não** medem acurácia clínica, não comprovam generalização e não transformam o BM25 em um classificador de notícias verdadeiras ou falsas.
"""
        ),
        markdown(
            """
## Contexto e métodos

O sistema recupera trechos de artigos científicos para apoiar a checagem de alegações. O artefato treinado desta entrega é o índice lexical Okapi BM25, ajustado às frequências e aos comprimentos dos documentos do corpus. Escolhemos o BM25 como baseline porque ele é determinístico, explicável, rápido e executa localmente; cada pontuação pode ser relacionada aos termos presentes na consulta e no documento. O projeto também possui caminhos opcionais com embeddings e NLI pré-treinados, mas eles não são treinados localmente e, por isso, não são apresentados como um classificador supervisionado criado pela equipe.

### Hipóteses e limites

- O conjunto reúne 2 excertos do conjunto dourado original e 20 títulos PubMed já presentes nos dados do projeto. Os rótulos foram definidos para validação de engenharia a partir da correspondência temática dos títulos; não houve revisão clínica independente.
- As 14 consultas incluem casos específicos, casos com múltiplos relevantes e 2 casos fora do domínio. Recall, MRR e nDCG são calculados somente quando existe ao menos um relevante conhecido.
- `k=1` avalia o primeiro trecho mostrado ao usuário, enquanto `k=3` e `k=5` verificam se a cobertura melhora ao permitir uma lista maior.
- A relevância é binária por PMID e não representa consenso ou validade científica.
"""
        ),
        markdown(
            """
## Ambiente reproduzível

### 0. Instalar todas as dependências do projeto

A célula abaixo instala todas as bibliotecas necessárias no mesmo ambiente do kernel e registra as versões utilizadas. Em uma máquina nova, execute esta célula antes das demais.
"""
        ),
        markdown(
            """
### Como executar em outro computador

1. Instale Python 3.10 ou superior e abra este arquivo no Jupyter Notebook/JupyterLab; como alternativa, envie o `.ipynb` ao Google Colab.
2. Use **Executar tudo / Run all** a partir da primeira célula.
3. A célula seguinte instala automaticamente Pandas, Matplotlib e NumPy no ambiente do kernel.
4. Os dados de validação, o BM25 e as métricas estão incorporados ao notebook. Não é necessário clonar o repositório nem copiar a pasta `src`.
5. Ao final, o notebook cria `modelo_bm25_evidencias.pkl` na mesma pasta de execução e demonstra seu carregamento.
"""
        ),
        code(
            """
import subprocess
import sys
from importlib.metadata import version

if sys.version_info < (3, 10):
    raise RuntimeError("Este notebook requer Python 3.10 ou superior.")

notebook_requirements = [
    "pandas>=2.2,<4",
    "matplotlib>=3.9,<4",
]

subprocess.check_call(
    [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--disable-pip-version-check",
        *notebook_requirements,
    ]
)

print("Dependências necessárias instaladas no kernel atual.")
for package in ["pandas", "matplotlib", "numpy"]:
    print(f"{package}: {version(package)}")
print(f"Python: {sys.version.split()[0]}")
"""
        ),
        markdown("## Dados\n\n### 1. Configurar caminhos e carregar a fixture versionada"),
        code(
            """
from __future__ import annotations

import hashlib
import json
import math
import pickle
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

EMBEDDED_FIXTURE = {
    "schema_version": 1,
    "description": (
        "Conjunto controlado de engenharia com excertos e títulos públicos do PubMed; "
        "não é validação clínica nem ground truth de fake news."
    ),
    "annotation_status": "engineering_review_only",
    "documents": [
        {
            "pmid": "33031652",
            "pmcid": None,
            "doi": "10.1056/NEJMoa2022926",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/33031652/",
            "section": "Resumo: resultados",
            "text": (
                "Death within 28 days occurred in 421 patients (27.0%) in the "
                "hydroxychloroquine group and in 790 (25.0%) in the usual-care group"
            ),
        },
        {
            "pmid": "33859192",
            "pmcid": None,
            "doi": None,
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/33859192/",
            "section": "Resumo: conclusão",
            "text": (
                "We found that treatment with hydroxychloroquine is associated with "
                "increased mortality in COVID-19 patients, and there is no benefit of chloroquine."
            ),
        },
        *[
            {
                "pmid": pmid,
                "pmcid": None,
                "doi": doi,
                "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "section": "Título PubMed",
                "text": title,
            }
            for pmid, doi, title in [
                ("3855486", None, "Early precursors of site-specific cancers in college men and women."),
                ("33977254", "10.1002/iju5.12277", "Trocar site hernia resulting in intestinal necrosis 48 hours after robot-assisted radical prostatectomy."),
                ("14166832", "10.1620/tjem.82.218", "COFFEE CONSUMPTION AND MORTALITY FOR PROSTATE CANCER."),
                ("21991610", None, "Research continues to serve up heart perks for coffee drinkers."),
                ("21999480", "10.1080/01635581.2011.627295", "Should men drink more coffee to delay progression of prostate cancer?"),
                ("28558558", "10.7748/ns.31.40.17.s20", "Three cups of espresso a day may halve prostate cancer risk."),
                ("4509621", None, "[Coffee consumption and neoplasm induction--no causal relation]."),
                ("24448493", "10.1038/ejcn.2013.292", "Re: Coffee consumption and risk of prostate cancer: an up-to-date meta-analysis."),
                ("22962694", "10.1093/jnci/djs383", "Re: coffee consumption and prostate cancer risk and progression in the health professional follow-up study."),
                ("24399415", "10.1002/cncr.28542", "Coffee consumption linked to a reduction in prostate cancer recurrence."),
                ("4843266", "10.1093/jnci/53.2.335", "Cancer of the prostate among men with benign prostatic hyperplasia."),
                ("2611622", "10.1111/j.1464-410x.1989.tb05288.x", "Hot flushes are induced by thermogenic stimuli."),
                ("41531586", "10.7759/cureus.99094", "Habitual Coffee Consumption and Systemic Health Outcomes: A Comprehensive Review."),
                ("40643840", "10.1007/s10552-025-02033-z", "Coffee and tea intake and survival of cancer patients: a systematic review and meta-analysis."),
                ("39266809", "10.1007/s11357-024-01332-8", "Coffee consumption, cancer, and healthy aging: epidemiological evidence and underlying mechanisms."),
                ("30384410", "10.3390/ijms19113407", "Effect of Roasting Levels and Drying Process of Coffea canephora on the Quality of Bioactive Compounds and Cytotoxicity."),
                ("33431520", "10.1136/bmjopen-2020-038902", "Coffee consumption and risk of prostate cancer: a systematic review and meta-analysis."),
                ("25706900", "10.1080/01635581.2015.1004727", "Coffee consumption and prostate cancer risk: a meta-analysis of cohort studies."),
                ("24300907", "10.1038/ejcn.2013.256", "Coffee consumption and risk of prostate cancer: an up-to-date meta-analysis."),
                ("33837499", "10.1007/s10552-021-01417-1", "Post-diagnostic coffee and tea consumption and risk of prostate cancer progression by smoking history."),
            ]
        ],
    ],
    "cases": [
        {
            "case_id": "trial-comparator",
            "claim": "Hydroxychloroquine compared with usual-care: death within 28 days.",
            "relevant_pmids": ["33031652"],
            "acceptable_first_pmids": ["33031652"],
        },
        {
            "case_id": "chloroquine-benefit",
            "claim": "Chloroquine provides a mortality benefit.",
            "relevant_pmids": ["33859192"],
            "acceptable_first_pmids": ["33859192"],
        },
        {
            "case_id": "coffee-prostate-meta-analysis",
            "claim": "Coffee consumption and prostate cancer risk meta-analysis",
            "relevant_pmids": ["24448493", "33431520", "25706900", "24300907"],
            "acceptable_first_pmids": ["24448493", "33431520", "25706900", "24300907"],
        },
        {
            "case_id": "coffee-prostate-progression",
            "claim": "Coffee consumption and prostate cancer progression follow-up study",
            "relevant_pmids": ["22962694", "33837499"],
            "acceptable_first_pmids": ["22962694", "33837499"],
        },
        {
            "case_id": "coffee-prostate-recurrence",
            "claim": "Coffee consumption and prostate cancer recurrence",
            "relevant_pmids": ["24399415"],
            "acceptable_first_pmids": ["24399415"],
        },
        {
            "case_id": "coffee-prostate-mortality",
            "claim": "Coffee consumption and mortality for prostate cancer",
            "relevant_pmids": ["14166832"],
            "acceptable_first_pmids": ["14166832"],
        },
        {
            "case_id": "surgery-complication",
            "claim": "Trocar hernia intestinal necrosis after robot-assisted radical prostatectomy",
            "relevant_pmids": ["33977254"],
            "acceptable_first_pmids": ["33977254"],
        },
        {
            "case_id": "coffee-heart-health",
            "claim": "Heart health benefits for coffee drinkers",
            "relevant_pmids": ["21991610"],
            "acceptable_first_pmids": ["21991610"],
        },
        {
            "case_id": "coffee-systemic-health",
            "claim": "Habitual coffee consumption systemic health outcomes review",
            "relevant_pmids": ["41531586"],
            "acceptable_first_pmids": ["41531586"],
        },
        {
            "case_id": "coffee-healthy-aging",
            "claim": "Coffee cancer healthy aging epidemiological mechanisms",
            "relevant_pmids": ["39266809"],
            "acceptable_first_pmids": ["39266809"],
        },
        {
            "case_id": "coffee-roasting",
            "claim": "Coffee roasting drying bioactive compounds cytotoxicity",
            "relevant_pmids": ["30384410"],
            "acceptable_first_pmids": ["30384410"],
        },
        {
            "case_id": "hot-flush",
            "claim": "Hot flushes caused by thermogenic stimuli",
            "relevant_pmids": ["2611622"],
            "acceptable_first_pmids": ["2611622"],
        },
        {
            "case_id": "out-of-topic-exercise",
            "claim": "Exercise improves cardiovascular function",
            "relevant_pmids": [],
            "acceptable_first_pmids": [],
        },
        {
            "case_id": "out-of-topic-vaccine",
            "claim": "Influenza vaccine effectiveness in children",
            "relevant_pmids": [],
            "acceptable_first_pmids": [],
        },
    ],
}

execution_directory = Path.cwd().resolve()
fixture = EMBEDDED_FIXTURE
raw_fixture = json.dumps(
    fixture,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
fixture_sha256 = hashlib.sha256(raw_fixture).hexdigest()
fixture_source = "dados incorporados ao próprio notebook"

delivery_directory = (
    execution_directory / "entrega_modelo_ia"
    if (execution_directory / "entrega_modelo_ia").is_dir()
    else execution_directory
)
MODEL_PATH = delivery_directory / "modelo_bm25_evidencias.pkl"

print(f"Fonte da fixture: {fixture_source}")
print(f"SHA-256 de referência: {fixture_sha256}")
print(f"Documentos: {len(fixture['documents'])} | Casos: {len(fixture['cases'])}")
print(f"Status da anotação: {fixture['annotation_status']}")
"""
        ),
        code(
            """
@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    pmid: str
    section: str
    text: str
    source_url: str


@dataclass(frozen=True)
class RetrievedChunk:
    rank: int
    score: float
    matched_terms: tuple[str, ...]
    chunk: EvidenceChunk


def tokenize(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return tuple(re.findall(r"[^\\W_]+", without_accents, flags=re.UNICODE))


def fixture_chunks(fixture_data: dict) -> tuple[EvidenceChunk, ...]:
    chunks = []
    for document in fixture_data["documents"]:
        identity = "|".join(
            [document["pmid"], document["section"], document["text"]]
        ).encode("utf-8")
        chunks.append(
            EvidenceChunk(
                chunk_id=hashlib.sha256(identity).hexdigest()[:24],
                pmid=document["pmid"],
                section=document["section"],
                text=document["text"],
                source_url=document["source_url"],
            )
        )
    return tuple(chunks)


class PortableBm25Index:
    def __init__(self, chunks: Sequence[EvidenceChunk], k1: float = 1.5, b: float = 0.75):
        if not chunks:
            raise ValueError("Ao menos um trecho é necessário para criar o índice.")
        self.chunks = tuple(chunks)
        self.k1 = float(k1)
        self.b = float(b)
        self._tokens = tuple(tokenize(chunk.text) for chunk in self.chunks)
        self._term_frequencies = tuple(Counter(tokens) for tokens in self._tokens)
        self._document_lengths = tuple(len(tokens) for tokens in self._tokens)
        self._average_length = sum(self._document_lengths) / len(self.chunks)
        document_frequencies = Counter()
        for tokens in self._tokens:
            document_frequencies.update(set(tokens))
        self._document_frequencies = document_frequencies

    def _idf(self, term: str) -> float:
        document_count = len(self.chunks)
        frequency = self._document_frequencies.get(term, 0)
        return math.log(1 + (document_count - frequency + 0.5) / (frequency + 0.5))

    def _score(self, document_index: int, query_terms: tuple[str, ...]) -> float:
        frequencies = self._term_frequencies[document_index]
        document_length = self._document_lengths[document_index]
        score = 0.0
        for term in query_terms:
            term_frequency = frequencies.get(term, 0)
            if not term_frequency:
                continue
            length_factor = 1 - self.b + self.b * (
                document_length / self._average_length
            )
            score += self._idf(term) * (
                term_frequency * (self.k1 + 1)
            ) / (term_frequency + self.k1 * length_factor)
        return score

    def search(self, query: str, top_k: int = 5) -> tuple[RetrievedChunk, ...]:
        query_terms = tuple(dict.fromkeys(tokenize(query)))
        scored = []
        for document_index, chunk in enumerate(self.chunks):
            score = self._score(document_index, query_terms)
            if score <= 0:
                continue
            frequencies = self._term_frequencies[document_index]
            matched_terms = tuple(term for term in query_terms if term in frequencies)
            scored.append((score, chunk, matched_terms))
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return tuple(
            RetrievedChunk(rank, score, terms, chunk)
            for rank, (score, chunk, terms) in enumerate(scored[:top_k], start=1)
        )

    def to_state(self) -> dict:
        return {
            "k1": self.k1,
            "b": self.b,
            "chunks": [asdict(chunk) for chunk in self.chunks],
            "tokens": [list(tokens) for tokens in self._tokens],
            "term_frequencies": [dict(values) for values in self._term_frequencies],
            "document_lengths": list(self._document_lengths),
            "average_length": self._average_length,
            "document_frequencies": dict(self._document_frequencies),
        }

    @classmethod
    def from_state(cls, state: dict) -> "PortableBm25Index":
        instance = cls.__new__(cls)
        instance.k1 = float(state["k1"])
        instance.b = float(state["b"])
        instance.chunks = tuple(EvidenceChunk(**chunk) for chunk in state["chunks"])
        instance._tokens = tuple(tuple(tokens) for tokens in state["tokens"])
        instance._term_frequencies = tuple(
            Counter(values) for values in state["term_frequencies"]
        )
        instance._document_lengths = tuple(state["document_lengths"])
        instance._average_length = float(state["average_length"])
        instance._document_frequencies = Counter(state["document_frequencies"])
        return instance


def _unique_ranking(ranking: Sequence[str], k: int) -> list[str]:
    return list(dict.fromkeys(ranking))[:k]


def precision_at_k(ranking: Sequence[str], relevant: set[str], k: int) -> float:
    return sum(item in relevant for item in _unique_ranking(ranking, k)) / k


def recall_at_k(ranking: Sequence[str], relevant: set[str], k: int) -> float | None:
    selected = _unique_ranking(ranking, k)
    return sum(item in relevant for item in selected) / len(relevant) if relevant else None


def reciprocal_rank(ranking: Sequence[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    return next(
        (1 / rank for rank, item in enumerate(dict.fromkeys(ranking), 1) if item in relevant),
        0.0,
    )


def ndcg_at_k(ranking: Sequence[str], relevant: set[str], k: int) -> float | None:
    selected = _unique_ranking(ranking, k)
    if not relevant:
        return None
    dcg = sum(
        1 / math.log2(rank + 1)
        for rank, item in enumerate(selected, 1)
        if item in relevant
    )
    ideal = sum(
        1 / math.log2(rank + 1)
        for rank in range(1, min(k, len(relevant)) + 1)
    )
    return dcg / ideal


print("Implementação BM25 e métricas carregadas no próprio notebook.")
"""
        ),
        markdown(
            """
### Fluxo executado

O notebook percorre o processo completo: carrega e valida os dados, prepara os trechos, ajusta as estatísticas do BM25, salva o modelo, recarrega o `.pkl`, executa as consultas e calcula as métricas.
"""
        ),
        code(
            """
workflow_steps = [
    "Fixture JSON",
    "Validação e\\ntokenização",
    "Ajuste do\\nBM25",
    "Modelo .pkl",
    "Consultas",
    "Métricas",
]

fig, ax = plt.subplots(figsize=(12, 2.5))
ax.set_xlim(-0.5, len(workflow_steps) - 0.5)
ax.set_ylim(-0.7, 0.7)
ax.axis("off")

for index, step in enumerate(workflow_steps):
    ax.text(
        index,
        0,
        step,
        ha="center",
        va="center",
        fontsize=10,
        color="#0f172a",
        bbox={
            "boxstyle": "round,pad=0.5",
            "facecolor": "#eaf1f8" if index not in {2, 3} else "#dbeafe",
            "edgecolor": "#2563eb",
            "linewidth": 1.4,
        },
    )
    if index < len(workflow_steps) - 1:
        ax.annotate(
            "",
            xy=(index + 0.68, 0),
            xytext=(index + 0.32, 0),
            arrowprops={"arrowstyle": "->", "color": "#64748b", "lw": 1.5},
        )

ax.set_title("Fluxo reproduzido neste notebook", fontsize=14, pad=18)
fig.tight_layout()
plt.show()
"""
        ),
        markdown(
            """
### 2. Validar e preparar os trechos

Antes de ajustar o índice, verificamos se existem documentos, se cada `chunk_id` é único e se nenhum texto está vazio. Essas checagens evitam que duplicatas recebam peso indevido ou que entradas inválidas alterem o tamanho médio dos documentos. Depois organizamos uma tabela com PMID, seção, tamanho e texto para tornar o corpus inspecionável.
"""
        ),
        code(
            """
chunks = fixture_chunks(fixture)
assert chunks, "O corpus não pode estar vazio."
assert len({chunk.chunk_id for chunk in chunks}) == len(chunks), "Há IDs de chunk duplicados."
assert all(chunk.text.strip() for chunk in chunks), "Há trecho sem texto."

corpus = pd.DataFrame(
    {
        "chunk_id": [chunk.chunk_id for chunk in chunks],
        "pmid": [chunk.pmid for chunk in chunks],
        "secao": [chunk.section for chunk in chunks],
        "caracteres": [len(chunk.text) for chunk in chunks],
        "texto": [chunk.text for chunk in chunks],
    }
)
corpus
"""
        ),
        markdown(
            """
### 2.1 Visualizar o corpus de treinamento

O gráfico mostra o tamanho de cada trecho usado para ajustar as estatísticas do BM25. Como existem apenas dois documentos, essa visualização também deixa evidente o tamanho reduzido do conjunto.
"""
        ),
        code(
            """
corpus_plot = corpus.sort_values("caracteres", ascending=True)
fig, ax = plt.subplots(figsize=(9, 8.5))
bars = ax.barh(
    corpus_plot["pmid"],
    corpus_plot["caracteres"],
    color="#2563eb",
)
ax.set_xlabel("Quantidade de caracteres no trecho")
ax.set_ylabel("PMID")
ax.set_title(f"Tamanho dos textos usados no ajuste do BM25 (n={len(corpus_plot)})")
ax.bar_label(bars, padding=4, fmt="%.0f")
ax.set_xlim(0, corpus_plot["caracteres"].max() * 1.18)
fig.tight_layout()
plt.show()
"""
        ),
        markdown(
            """
## Resultados

### 3. Ajustar o BM25 ao corpus e salvar o modelo

No BM25, “treinar” significa calcular estatísticas do corpus: frequência de documentos por termo, frequência de termos por documento, comprimentos e comprimento médio. Não há otimização por gradiente nem ajuste de um LLM. Mantemos `k1=1,5` para limitar o ganho causado pela repetição de uma palavra e `b=0,75` para normalizar parcialmente a diferença de tamanho entre os textos; esses são valores de referência do baseline e não foram escolhidos após olhar os resultados desta avaliação.
"""
        ),
        code(
            """
model = PortableBm25Index(chunks)
model_bundle = {
    "artifact_version": 2,
    "model_type": "Okapi BM25 evidence retriever",
    "storage_format": "portable Python built-ins",
    "fitted_at_utc": datetime.now(timezone.utc).isoformat(),
    "fixture_source": fixture_source,
    "fixture_sha256": fixture_sha256,
    "training_document_count": len(chunks),
    "annotation_status": fixture["annotation_status"],
    "intended_use": "Recuperar e ordenar trechos científicos; não classificar verdade/falsidade.",
    "model_state": model.to_state(),
}

MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
with MODEL_PATH.open("wb") as file:
    pickle.dump(model_bundle, file, protocol=pickle.HIGHEST_PROTOCOL)

print(f"Modelo salvo em: {MODEL_PATH}")
print(f"Tamanho: {MODEL_PATH.stat().st_size:,} bytes")
"""
        ),
        markdown(
            """
### 4. Carregar o artefato salvo e executar uma busca

Salvamos o estado aprendido em `.pkl` para que frequências, comprimentos e documentos possam ser reutilizados sem repetir manualmente a preparação. Em seguida, carregamos o arquivo e executamos uma consulta de exemplo; essa etapa prova que o artefato entregue funciona fora da memória da etapa de treinamento. Como `pickle` pode executar código durante a leitura, o arquivo deve ser carregado somente quando vier de uma fonte confiável.
"""
        ),
        code(
            """
with MODEL_PATH.open("rb") as file:
    loaded_bundle = pickle.load(file)

loaded_model = PortableBm25Index.from_state(loaded_bundle["model_state"])
assert loaded_bundle["fixture_sha256"] == fixture_sha256

example_query = "Hydroxychloroquine compared with usual-care: death within 28 days."
example_results = loaded_model.search(example_query, top_k=1)
pd.DataFrame(
    [
        {
            "rank": item.rank,
            "score_bm25": round(item.score, 4),
            "pmid": item.chunk.pmid,
            "termos_correspondentes": ", ".join(item.matched_terms),
        }
        for item in example_results
    ]
)
"""
        ),
        markdown(
            """
### 5. Avaliar cada consulta com métricas de ranking

A avaliação é repetida em `k=1`, `k=3` e `k=5`. Usamos três cortes porque `k=1` representa a evidência principal exibida ao usuário, enquanto os valores maiores mostram o equilíbrio entre precisão e cobertura quando mais resultados são apresentados. A Precision usa todas as consultas e denominador igual a `k`; Recall, MRR e nDCG são calculados somente nos casos em que existe pelo menos um documento relevante anotado.
"""
        ),
        code(
            """
evaluation_rows = []

for k in [1, 3, 5]:
    for case in fixture["cases"]:
        results = loaded_model.search(case["claim"], top_k=k)
        ranking = [item.chunk.chunk_id for item in results]
        relevant_ids = {
            chunk.chunk_id
            for chunk in chunks
            if chunk.pmid in set(case["relevant_pmids"])
        }
        out_of_domain = not relevant_ids
        evaluation_rows.append(
            {
                "k": k,
                "caso": case["case_id"],
                "pmids_recuperados": [item.chunk.pmid for item in results],
                "pmid_top1": results[0].chunk.pmid if results else None,
                "precision": precision_at_k(ranking, relevant_ids, k),
                "recall": recall_at_k(ranking, relevant_ids, k),
                "reciprocal_rank": reciprocal_rank(ranking, relevant_ids),
                "ndcg": ndcg_at_k(ranking, relevant_ids, k),
                "abstencao": not results,
                "fora_do_dominio": out_of_domain,
                "decisao_abstencao_correta": (
                    not results if out_of_domain else bool(results)
                ),
                "score_top1": results[0].score if results else 0.0,
                "resultado_top1": (
                    "Recuperação correta"
                    if results and results[0].chunk.pmid in set(case["acceptable_first_pmids"])
                    else "Abstenção correta"
                    if not results and out_of_domain
                    else "Resultado incorreto"
                ),
            }
        )

case_metrics = pd.DataFrame(evaluation_rows)
case_metrics.query("k == 1")[
    ["caso", "pmid_top1", "precision", "recall", "reciprocal_rank", "ndcg", "abstencao"]
]
"""
        ),
        markdown(
            """
### 5.1 Inspecionar o comportamento por consulta

As barras representam a pontuação BM25 do primeiro resultado em `k=1`. A cor e o texto distinguem recuperação correta, abstinência correta e resultado incorreto. Essa inspeção por consulta é importante porque a média pode esconder um falso positivo fora do domínio.
"""
        ),
        code(
            """
case_plot = case_metrics.query("k == 1").sort_values("score_top1", ascending=True)
status_colors = {
    "Recuperação correta": "#2563eb",
    "Abstenção correta": "#d97706",
    "Resultado incorreto": "#be123c",
}

fig, ax = plt.subplots(figsize=(10, 7.2))
bars = ax.barh(
    case_plot["caso"],
    case_plot["score_top1"],
    color=[status_colors[value] for value in case_plot["resultado_top1"]],
)
ax.set_xlabel("Pontuação BM25 do primeiro resultado")
ax.set_ylabel("Caso de avaliação")
ax.set_title("Resultado por consulta no conjunto dourado (k=1)")
for row_index, (_, row) in enumerate(case_plot.iterrows()):
    label_x = row["score_top1"] + max(case_plot["score_top1"].max() * 0.06, 0.12)
    if row["score_top1"] == 0:
        ax.scatter(
            0,
            row_index,
            s=70,
            color=status_colors[row["resultado_top1"]],
            zorder=3,
        )
    ax.text(
        label_x,
        row_index,
        f"{row['score_top1']:.3f} — {row['resultado_top1']}",
        va="center",
        fontsize=9,
        color="#334155",
    )
ax.set_xlim(0, max(case_plot["score_top1"].max() * 1.52, 1.0))
fig.tight_layout()
plt.show()
"""
        ),
        code(
            """
def mean_defined(series: pd.Series) -> float | None:
    defined = series.dropna()
    return float(defined.mean()) if len(defined) else None

summary_rows = []
for k, group in case_metrics.groupby("k", sort=True):
    out_of_domain = group[group["fora_do_dominio"]]
    summary_rows.append(
        {
            "k": int(k),
            "Precision": mean_defined(group["precision"]),
            "Recall": mean_defined(group["recall"]),
            "MRR": mean_defined(group["reciprocal_rank"]),
            "nDCG": mean_defined(group["ndcg"]),
            "Taxa de abstinência": float(group["abstencao"].mean()),
            "Acerto da abstinência fora do domínio": float(
                out_of_domain["decisao_abstencao_correta"].mean()
            ),
        }
    )

summary_table = pd.DataFrame(summary_rows).round(3)
summary_table
"""
        ),
        markdown(
            """
### 6. Visualizar o desempenho observado

O gráfico compara as métricas de ranking nos três cortes. Esperamos que o Recall aumente quando `k` cresce, pois há mais espaço para recuperar documentos relevantes; ao mesmo tempo, a Precision tende a cair porque o denominador aumenta e nem todas as posições adicionais são relevantes. MRR e nDCG ajudam a verificar se os relevantes continuam concentrados no topo, em vez de aparecerem apenas porque a lista ficou maior.
"""
        ),
        code(
            """
plt.style.use("seaborn-v0_8-whitegrid")
fig, ax = plt.subplots(figsize=(10.5, 5.6), layout="constrained")
metric_colors = {
    "Precision": "#2563eb",
    "Recall": "#d97706",
    "MRR": "#64748b",
    "nDCG": "#7c3aed",
}
x_positions = np.arange(len(summary_table))
bar_width = 0.19
metrics = list(metric_colors)
for metric_index, metric in enumerate(metrics):
    offset = (metric_index - (len(metrics) - 1) / 2) * bar_width
    bars = ax.bar(
        x_positions + offset,
        summary_table[metric],
        width=bar_width,
        label=metric,
        color=metric_colors[metric],
    )
    ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=8)
ax.set_ylim(0, 1.08)
ax.set_xticks(x_positions, [f"k={k}" for k in summary_table["k"]])
ax.set_xlabel("Quantidade de posições avaliadas (k)")
ax.set_ylabel("Valor (0–1)")
ax.set_title("Métricas do BM25 por profundidade do ranking (22 documentos, 14 consultas)")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=4, frameon=False)
plt.show()
"""
        ),
        markdown(
            """
### 7. Verificações de consistência

As verificações abaixo confirmam o tamanho do conjunto, os resultados agregados e os dois casos fora do domínio. Um deles gera abstinência correta; o outro produz um falso positivo lexical, mostrando por que a taxa de abstinência não deve ser interpretada isoladamente.
"""
        ),
        code(
            """
assert len(chunks) == 22
assert len(fixture["cases"]) == 14

summary_by_k = summary_table.set_index("k")
assert math.isclose(summary_by_k.loc[1, "Precision"], 0.857, abs_tol=0.001)
assert math.isclose(summary_by_k.loc[1, "Recall"], 0.896, abs_tol=0.001)
assert math.isclose(summary_by_k.loc[5, "Recall"], 1.000, abs_tol=0.001)
assert math.isclose(summary_by_k.loc[1, "MRR"], 1.000, abs_tol=0.001)
assert math.isclose(summary_by_k.loc[1, "nDCG"], 1.000, abs_tol=0.001)
assert math.isclose(summary_by_k.loc[1, "Taxa de abstinência"], 1 / 14, abs_tol=0.001)
assert math.isclose(
    summary_by_k.loc[1, "Acerto da abstinência fora do domínio"],
    0.5,
    abs_tol=0.001,
)
print("Todas as verificações passaram.")
"""
        ),
        markdown(
            """
## Aprendizados e conclusão

- O BM25 é um baseline adequado para o modo local porque é determinístico, rápido, auditável e não exige download de pesos ou serviço externo.
- Nos 12 casos com relevante conhecido, ao menos um relevante apareceu na primeira posição; por isso MRR e nDCG permaneceram em 1,000. Isso descreve este conjunto controlado e não garante o mesmo comportamento em consultas independentes.
- A Precision caiu de 0,857 em `k=1` para 0,229 em `k=5`, enquanto o Recall aumentou de 0,896 para 1,000. Esse movimento mostra o compromisso esperado: listas maiores cobrem mais relevantes, mas também incluem mais resultados não relevantes.
- Entre as duas consultas fora do domínio, somente uma gerou abstinência. O falso positivo restante mostra que correspondência lexical isolada não é um mecanismo de segurança suficiente e que um limiar ou etapa adicional de validação deve ser calibrado.
- O conjunto ampliado melhora a cobertura da validação de engenharia, mas os rótulos ainda foram definidos a partir de títulos e não passaram por revisão clínica independente.
- O maior aprendizado metodológico é separar **recuperação de evidência**, **relação textual** e **veracidade**. O índice recupera trechos; ele não emite um veredito de verdade.

### Próximos passos recomendados

Construir um conjunto maior, independente e revisado por especialistas; medir resultados por tema e idioma; calibrar limiares de abstinência; e somente então comparar BM25, recuperação semântica, híbrida e reranking com intervalos de confiança.
"""
        ),
    ]

    notebook = nbformat.v4.new_notebook(cells=cells)
    notebook.metadata.kernelspec = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    notebook.metadata.language_info = {"name": "python", "version": "3"}
    return notebook


def main() -> None:
    DELIVERY.mkdir(parents=True, exist_ok=True)
    notebook = build_notebook()
    nbformat.write(notebook, NOTEBOOK)
    client = NotebookClient(
        notebook,
        timeout=300,
        kernel_name="python3",
        resources={"metadata": {"path": str(ROOT)}},
    )
    client.execute()
    nbformat.write(notebook, NOTEBOOK)
    print(json.dumps({"notebook": str(NOTEBOOK), "sha256": hashlib.sha256(NOTEBOOK.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
