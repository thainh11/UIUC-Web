"""Draw the linking sample and the query pools.

    python -m eval.sample
    python -m eval.sample --assemble

The blinded files hide stratum, score, and match method. Assemble after
eval/work/linking_labels.jsonl and eval/work/qrel_labels.jsonl are filled.
"""

import argparse
import random
import sys

from .io import (
    GOLD,
    HOLDOUT,
    LABELER,
    ROOT,
    SEED,
    WORK,
    connect,
    dump_jsonl,
    load_jsonl,
)
from .linking import (
    attach_authors,
    blind_view,
    format_case,
    gold_view,
    key_view,
    sample_pairs,
)
from .retrieval import (
    MANUAL_QUERIES,
    RANK_K,
    embed_queries,
    paper_cards,
    search_embedding,
    search_fts,
    topic_queries,
)


def draw(force: bool) -> None:
    blind_path = WORK / "linking_blind.jsonl"
    if blind_path.exists() and not force:
        sys.exit("eval/work already has a sample; pass --force to redraw it")
    WORK.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        pairs = sample_pairs(conn, random.Random(SEED))
        print("reading author institutions from the OpenAlex cache")
        attach_authors(pairs, ROOT / "data" / "raw" / "openalex" / "works")
        topics = topic_queries(conn, random.Random(SEED))
        queries = [*topics, *[dict(row, qrels=None) for row in MANUAL_QUERIES]]
        pools = _pools(conn, [query for query in queries if query["kind"] != "topic"])
    dump_jsonl(blind_path, {"task": "linking-blind", "labeler": LABELER, "seed": SEED}, [blind_view(row) for row in pairs])
    dump_jsonl(WORK / "linking_keys.jsonl", {"task": "linking-keys", "seed": SEED, "holdout_fraction": HOLDOUT}, [key_view(row) for row in pairs])
    dump_jsonl(WORK / "queries.jsonl", {"task": "queries-draft", "labeler": LABELER, "seed": SEED}, queries)
    dump_jsonl(WORK / "pool_ids.jsonl", {"task": "pools", "seed": SEED}, pools["ids"])
    (WORK / "blind.txt").write_text("\n".join(format_case(blind_view(row)) for row in pairs), encoding="utf-8")
    (WORK / "pools.txt").write_text(pools["text"], encoding="utf-8")
    print(f"wrote {len(pairs)} blinded linking cases and {len(queries)} queries to {WORK}")


def _pools(conn, queries: list[dict]) -> dict:
    vectors = embed_queries([query["text"] for query in queries])
    rng = random.Random(SEED)
    ids = []
    blocks = []
    for index, query in enumerate(queries):
        found = {row["id"] for row in search_fts(conn, query["text"], RANK_K)}
        if vectors is not None:
            found.update(row["id"] for row in search_embedding(conn, vectors[index], RANK_K))
        ordered = sorted(found)
        rng.shuffle(ordered)
        cards = {row["id"]: row for row in paper_cards(conn, ordered)}
        blocks.append(f"QUERY {query['id']}\n{query['text']}\n")
        for paper_id in ordered:
            card = cards[paper_id]
            ids.append({"qid": query["id"], "paper_id": paper_id})
            blocks.append(
                f"{paper_id}\nTitle: {card['title']}\nDate: {card['publication_date']} | Topic: {card['topic']}\n"
                f"Abstract: {(card['abstract'] or '')[:500]}\n"
            )
        print(f"pool {query['id']}: {len(ordered)}")
    return {"ids": ids, "text": "\n".join(blocks) + "\n"}


def assemble() -> None:
    labels_path = WORK / "linking_labels.jsonl"
    qrels_path = WORK / "qrel_labels.jsonl"
    if not labels_path.exists() or not qrels_path.exists():
        sys.exit("missing eval/work/linking_labels.jsonl or eval/work/qrel_labels.jsonl")
    _meta, blind = load_jsonl(WORK / "linking_blind.jsonl")
    _kmeta, keys = load_jsonl(WORK / "linking_keys.jsonl")
    _lmeta, labels = load_jsonl(labels_path)
    by_blind = {row["id"]: row for row in blind}
    by_key = {row["id"]: row for row in keys}
    by_label = {row["id"]: row for row in labels}
    if set(by_blind) != set(by_key) or set(by_blind) != set(by_label):
        sys.exit("linking label ids do not match the blinded sample")
    linked = []
    for item_id in sorted(by_blind):
        label = by_label[item_id]["label"]
        if label not in ("same", "different", "unsure"):
            sys.exit(f"{item_id} has label {label!r}")
        linked.append(gold_view({**by_key[item_id], **by_blind[item_id]}, label, by_label[item_id].get("note")))
    dump_jsonl(
        GOLD / "linking.jsonl",
        {"task": "linking", "labeler": LABELER, "seed": SEED, "holdout_fraction": HOLDOUT},
        linked,
    )

    _qmeta, queries = load_jsonl(WORK / "queries.jsonl")
    _pmeta, pool_ids = load_jsonl(WORK / "pool_ids.jsonl")
    _rmeta, qrel_rows = load_jsonl(qrels_path)
    grades = {}
    for row in qrel_rows:
        if row["grade"] not in (0, 1, 2):
            sys.exit(f"bad grade on {row['qid']} {row['paper_id']}")
        grades[(row["qid"], row["paper_id"])] = row["grade"]
    required = {(row["qid"], row["paper_id"]) for row in pool_ids}
    if grades.keys() != required:
        missing = len(required - grades.keys())
        extra = len(grades.keys() - required)
        sys.exit(f"qrels do not match the pool ({missing} missing, {extra} extra)")
    finished = []
    for query in queries:
        if query["kind"] == "topic":
            finished.append(query)
            continue
        qrels = {paper_id: grades[(query["id"], paper_id)] for paper_id in {row["paper_id"] for row in pool_ids if row["qid"] == query["id"]}}
        finished.append({**query, "qrels": qrels})
    dump_jsonl(
        GOLD / "queries.jsonl",
        {
            "task": "queries",
            "labeler": LABELER,
            "seed": SEED,
            "topic_qrels": "OpenAlex topic labels, independent of the paper text",
            "manual_qrels": "agent judgments on the union of top-20 full-text and top-20 embedding, system identity hidden",
        },
        finished,
    )
    print(f"wrote {GOLD / 'linking.jsonl'} ({len(linked)}) and {GOLD / 'queries.jsonl'} ({len(finished)})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--assemble", action="store_true")
    args = parser.parse_args()
    if args.assemble:
        assemble()
    else:
        draw(args.force)


if __name__ == "__main__":
    main()
