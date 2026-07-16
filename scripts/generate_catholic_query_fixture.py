"""Gera a matriz versionada de termos a partir da seção de vocabulário do briefing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import unicodedata


CATEGORY_PATTERN = re.compile(r"^([A-Q])\.\s+(.+)$")
SINGLE_TERM_PATTERN = re.compile(r"^[^\W\d_]+(?:-[^\W\d_]+)*$", re.UNICODE)


def slug(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")


def extract_queries(text: str) -> list[dict]:
    start_marker = "VOCABULÁRIO CATÓLICO INICIAL OBRIGATÓRIO"
    end_marker = "REGRAS PARA VARIAÇÕES ORTOGRÁFICAS"
    section = text.split(start_marker, 1)[1].split(end_marker, 1)[0]
    category = ""
    category_label = ""
    by_term: dict[str, dict] = {}
    for raw_line in section.splitlines():
        line = raw_line.strip().lstrip("﻿")
        category_match = CATEGORY_PATTERN.match(line)
        if category_match:
            category_label = category_match.group(2).strip()
            category = f"{category_match.group(1).lower()}_{slug(category_label)}"
            continue
        if not category or not SINGLE_TERM_PATTERN.fullmatch(line):
            continue
        key = slug(line)
        if not key:
            continue
        if key in by_term:
            by_term[key]["categories"].append(category)
            continue
        by_term[key] = {
            "term": line,
            "category": category,
            "category_label": category_label,
            "categories": [category],
            "expected_mode": "TERM",
            "must_run_lexical_search": True,
            "must_run_semantic_expansion": True,
            "must_not_return_empty_if_documents_exist": True,
        }
    return list(by_term.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Arquivo de briefing que contém o vocabulário")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/fixtures/catholic_single_term_queries.json"),
    )
    args = parser.parse_args()
    queries = extract_queries(args.source.read_text(encoding="utf-8"))
    if not queries:
        raise SystemExit("Nenhum termo foi extraído do briefing.")
    payload = {
        "version": 1,
        "language": "pt-BR",
        "description": "Regressão permanente de consultas católicas de uma palavra.",
        "queries": queries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(queries)} consultas gravadas em {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
