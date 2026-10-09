"""Converte o texto de métricas para Markdown pronto para uma célula Jupyter."""

from __future__ import annotations

import re
from pathlib import Path


SOURCE = Path(
    "/Users/aluno1/.codex/attachments/8f6cebbf-57c6-47ac-89cd-04ebe1930139/"
    "Pasted text.txt"
)
OUTPUT = Path("docs/metricas_avaliacao_pipeline_jupyter.md")


def format_markdown(text: str) -> str:
    formatted = text.strip()

    # O primeiro bloco representa o fluxo do pipeline, não código executável.
    formatted = formatted.replace(
        "```\n\nAlegação\n",
        "```text\nAlegação\n",
        1,
    )

    # MathJax/Jupyter renderiza $$...$$ de forma consistente em células Markdown.
    formatted = re.sub(
        r"\\\[\s*\n(.*?)\n\s*\\\]",
        lambda match: "$$\n" + match.group(1).strip() + "\n$$",
        formatted,
        flags=re.DOTALL,
    )

    # Evita espaços excessivos sem desmontar listas, tabelas e fórmulas.
    formatted = re.sub(r"\n{4,}", "\n\n\n", formatted)
    return formatted + "\n"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(format_markdown(SOURCE.read_text(encoding="utf-8")), encoding="utf-8")
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()
