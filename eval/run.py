"""Print linking and retrieval metrics and compare them to eval/gold/baseline.json.

    python -m eval.run
    python -m eval.run --save
    python -m eval.run --sweep

Exit status is 1 when a gated test-split metric falls below the saved baseline.
Coverage and raw link counts are reported and are not gated: tightening a threshold
lowers them on purpose.
"""

import argparse
import json
import sys

from .io import GOLD, connect, load_jsonl
from .linking import agreement, current_links, sweep
from .metrics import wilson
from .retrieval import (
    embed_queries,
    faculty_sets,
    recent_date_sorted_precision,
    score_rankings,
    search_embedding,
    search_fts,
    search_hybrid,
)

BASELINE = GOLD / "baseline.json"


def _ratio(pair: tuple[int, int]) -> float | None:
    hits, n = pair
    return None if n == 0 else hits / n


def linking_metrics(conn, rows: list[dict]) -> dict[str, float | None]:
    links = current_links(conn)
    metrics: dict[str, float | None] = {}
    for split in ("all", "test", "tune"):
        report = agreement(rows, links, None if split == "all" else split)
        prefix = f"linking.{split}"
        metrics[f"{prefix}.precision"] = _ratio(report["precision"])
        metrics[f"{prefix}.recall_linked"] = _ratio(report["recall_linked"])
        metrics[f"{prefix}.rejected_recovery"] = _ratio(report["rejected_recovery"])
        metrics[f"{prefix}.rejected_same_rate"] = _ratio(report["rejected_same"])
        for stratum, bucket in sorted(report["by_stratum"].items()):
            metrics[f"{prefix}.precision.{stratum}"] = (bucket["same"] / bucket["n"]) if bucket["n"] else None
            metrics[f"{prefix}.n.{stratum}"] = bucket["n"]
    coverage = conn.execute(
        """SELECT (SELECT count(DISTINCT faculty_id) FROM paper_authors) AS linked,
                  (SELECT count(*) FROM faculty) AS faculty,
                  (SELECT count(*) FROM paper_authors WHERE faculty_id IS NOT NULL) AS links,
                  (SELECT count(*) FROM paper_authors WHERE is_uiuc OR NOT has_institution) AS candidates"""
    ).fetchone()
    metrics["info.faculty_coverage"] = coverage["linked"] / coverage["faculty"]
    metrics["info.authorship_link_rate"] = coverage["links"] / coverage["candidates"]
    for row in conn.execute(
        "SELECT match_method, count(*) AS n FROM paper_authors WHERE faculty_id IS NOT NULL GROUP BY 1 ORDER BY 1"
    ):
        metrics[f"info.links.{row['match_method']}"] = row["n"]
    metrics["info.linked_faculty"] = coverage["linked"]
    return metrics


def retrieval_metrics(conn, queries: list[dict]) -> dict[str, float | None]:
    vectors = embed_queries([query["text"] for query in queries])
    fts = {query["id"]: search_fts(conn, query["text"]) for query in queries}
    metrics = {f"retrieval.fts.{key}": value for key, value in score_rankings(queries, fts, conn).items()}
    if vectors is not None:
        emb = {query["id"]: search_embedding(conn, vector) for query, vector in zip(queries, vectors)}
        scores = score_rankings(queries, emb, conn)
        scores.pop("ood.empty")  # nearest-neighbour search always returns rows; refusing needs a score cut-off
        metrics.update({f"retrieval.emb.{key}": value for key, value in scores.items()})
        hybrid = {query["id"]: search_hybrid(conn, query["text"], vector) for query, vector in zip(queries, vectors)}
        metrics.update({f"retrieval.hybrid.{key}": value for key, value in score_rankings(queries, hybrid, conn).items()})
        metrics["retrieval.hybrid.recent.date_sorted_precision@6"] = recent_date_sorted_precision(conn, queries)
    for query in queries:
        if query["kind"] != "faculty":
            continue
        keywords, papers = faculty_sets(conn, query["concepts"])
        both = keywords & papers
        metrics[f"info.faculty.{query['id']}.intersection"] = len(both)
        metrics[f"info.faculty.{query['id']}.keyword_only"] = len(keywords - papers)
        metrics[f"info.faculty.{query['id']}.paper_only"] = len(papers - keywords)
    return metrics


def _gated(key: str) -> bool:
    if key.startswith("linking.test.precision") or key == "linking.test.recall_linked":
        return True
    if key == "linking.test.rejected_recovery":
        return True
    return key.startswith(("retrieval.fts.", "retrieval.emb.", "retrieval.hybrid."))


def _print_report(metrics: dict[str, float | None]) -> None:
    print(f"{'metric':<46} {'value':>8}")
    for key, value in metrics.items():
        if value is None:
            shown = "     n/a"
        elif isinstance(value, float):
            shown = f"{value:8.3f}"
        else:
            shown = f"{value:8}"
        print(f"{key:<46} {shown}")
    full = metrics.get("linking.all.precision")
    semantic = metrics.get("linking.all.precision.semantic")
    if full is not None:
        print(f"proposed bar, overall precision >= 0.95: {full:.3f} {'pass' if full >= 0.95 else 'below'}")
    if semantic is not None:
        print(f"proposed bar, semantic precision >= 0.85: {semantic:.3f} {'pass' if semantic >= 0.85 else 'below'}")


# The embedding server is not bit-exact between runs (GPU batching), so ranking metrics move by about 0.001.
TOLERANCE = 0.005


def compare(metrics: dict[str, float | None], baseline: dict[str, float]) -> list[str]:
    failures = []
    for key, saved in baseline.items():
        current = metrics.get(key)
        if current is None:
            failures.append(f"{key} is missing")
        elif current < saved - TOLERANCE:
            failures.append(f"{key} {current:.4f} < baseline {saved:.4f}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="write eval/gold/baseline.json from this run")
    parser.add_argument("--sweep", action="store_true", help="search thresholds on the tune split")
    args = parser.parse_args()
    linking_path = GOLD / "linking.jsonl"
    queries_path = GOLD / "queries.jsonl"
    if not linking_path.exists() or not queries_path.exists():
        sys.exit("gold files missing; run python -m eval.sample and assemble the labels")
    _lmeta, links = load_jsonl(linking_path)
    _qmeta, queries = load_jsonl(queries_path)
    with connect() as conn:
        metrics = linking_metrics(conn, links)
        metrics.update(retrieval_metrics(conn, queries))
        low, high = _wilson_for(conn, links)
    _print_report(metrics)
    if low is not None:
        print(f"overall affirmed precision Wilson 95%: {low:.3f} – {high:.3f}")
    if args.sweep:
        result = sweep(links)
        t_exact, t_loose, t_none, margin, sem = result["params"]
        print(
            "sweep best on tune, scored on test: "
            f"T_EXACT={t_exact} T_LOOSE={t_loose} T_NO_INSTITUTION={t_none} "
            f"MARGIN={margin} SEM={sem}"
        )
        print(
            f"  tune precision {result['tune_precision']:.3f} recall {result['tune_recall']:.3f} "
            f"rejected recovery {result['tune_recovery']:.3f}; "
            f"test precision {result['test_precision']:.3f} recall {result['test_recall']:.3f} "
            f"rejected recovery {result['test_recovery']:.3f} "
            f"semantic {result['test_semantic']:.3f}; db mismatches {result['mismatches']}"
        )
    gated = {key: value for key, value in metrics.items() if _gated(key) and isinstance(value, float)}
    if args.save:
        BASELINE.write_text(json.dumps(gated, indent=2, sort_keys=True) + "\n")
        print(f"saved {BASELINE}")
        return
    if not BASELINE.exists():
        print("no baseline yet; rerun with --save to record this run")
        return
    failures = compare(metrics, json.loads(BASELINE.read_text()))
    if failures:
        print("below baseline:")
        for line in failures:
            print(f"  {line}")
        sys.exit(1)
    print("baseline: ok")


def _wilson_for(conn, rows: list[dict]) -> tuple[float, float] | tuple[None, None]:
    links = current_links(conn)
    affirmed = [
        row["label"] == "same"
        for row in rows
        if row["label"] in ("same", "different")
        and row["stratum"] != "rejected"
        and links.get((row["paper_id"], row["position"])) == row["faculty_id"]
    ]
    if not affirmed:
        return (None, None)
    return wilson(sum(affirmed), len(affirmed))


if __name__ == "__main__":
    main()
