"""Executa a cobertura administrativa do vocabulário contra a base real."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402
from services.vector_store import LocalVectorStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "catholic_single_term_queries.json",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "rag-coverage-report.csv")
    parser.add_argument("--limit", type=int, default=0, help="0 percorre todo o vocabulário")
    args = parser.parse_args()
    queries = json.loads(args.fixture.read_text(encoding="utf-8"))["queries"]
    if args.limit > 0:
        queries = queries[: args.limit]
    store = LocalVectorStore(
        settings.DOCUMENTS_DIR,
        settings.INDEX_FILE,
        settings.CHUNK_SIZE,
        settings.CHUNK_OVERLAP,
    )
    rows = []
    for position, item in enumerate(queries, 1):
        started = time.monotonic()
        error = ""
        try:
            results, diagnostics = store.search_ordered(
                item["term"],
                limit=max(settings.MAX_CONTEXT_CHUNKS, 16),
                minimum_score=settings.MIN_RELEVANCE_SCORE,
                include_diagnostics=True,
            )
        except Exception as exc:  # relatório deve continuar e registrar a falha técnica
            results, diagnostics, error = [], {}, f"{type(exc).__name__}: {exc}"
        exact_count = diagnostics.get("candidate_counts", {}).get("lexical_exact", 0)
        semantic_count = diagnostics.get("candidate_counts", {}).get("semantic_expansion", 0)
        if error:
            classification = "FALHA"
        elif results:
            classification = "APROVADO" if exact_count or semantic_count else "ATENÇÃO"
        elif exact_count or semantic_count:
            classification = "FALHA"
        else:
            classification = "SEM COBERTURA"
        rows.append(
            {
                "term": item["term"],
                "category": item["category"],
                "lexical_occurrences": exact_count,
                "semantic_results": semantic_count,
                "best_score": max((result.get("score", 0) for result in results), default=0),
                "best_title": results[0]["source"] if results else "",
                "after_filters": len(results),
                "reranking": json.dumps(diagnostics.get("reranking", [])[:3], ensure_ascii=False),
                "critic": "not_run_retrieval_only",
                "empty": not bool(results),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "errors": error,
                "classification": classification,
            }
        )
        print(f"[{position}/{len(queries)}] {item['term']}: {classification}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys() if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Relatório gravado em {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
