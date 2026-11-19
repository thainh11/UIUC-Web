"""Hybrid paper search: full-text and embedding candidates fused by reciprocal rank, gated by cosine similarity."""

import re

import psycopg

from ..app.services.papers import FROM, SUMMARY_COLUMNS
from .embed import embed_queries, vector_literal
from .trace import note, span

CANDIDATES = 60  # per ranking
RRF_K = 60
# Full-text only lifts exact terms (acronyms, names): on 12 such queries the share of top-10 papers containing
# the term was 0.57 without it, 0.65 at 0.25, 0.66 at 1.0, while topical nDCG@10 fell 0.721 -> 0.710 -> 0.634.
FTS_WEIGHT = 0.25
# Nearest-neighbour search always returns rows, so something must say "nothing relevant". Measured on the
# eval queries (eval/gold/queries.jsonl): out-of-domain top-1 cosine 0.34-0.43, in-domain 0.48-0.75.
MIN_SIMILARITY = 0.45
# "Most recent": relevance picks which papers, date only orders them. The pool is the RECENT_POOL best fused hits
# within RECENT_MARGIN cosine of the best one; the `limit` most similar of those are then sorted newest first.
# Sorting the whole pool by date and cutting afterwards let newer, loosely related papers push out the best matches.
RECENT_POOL = 20
RECENT_MARGIN = 0.10


def _or_query(text: str) -> str:
    """websearch_to_tsquery syntax with every word OR-ed; the AND default returns nothing for natural questions."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return " or ".join(dict.fromkeys(words))


def rank_papers(
    conn: psycopg.Connection,
    query: str,
    vector: list[float],
    *,
    year_from: int | None = None,
    candidates: int = CANDIDATES,
) -> list[tuple[str, float]]:
    """(paper id, cosine similarity), best first by reciprocal-rank fusion, below MIN_SIMILARITY dropped."""
    literal = vector_literal(vector)
    since = f"{year_from}-01-01" if year_from else None
    date_filter = "AND publication_date >= %s" if since else ""
    date_params = [since] if since else []
    emb = conn.execute(
        f"""SELECT id, 1 - (embedding <=> %s::vector) AS sim FROM papers
            WHERE TRUE {date_filter} ORDER BY embedding <=> %s::vector LIMIT %s""",
        [literal, *date_params, literal, candidates],
    ).fetchall()
    fts = conn.execute(
        f"""SELECT id FROM papers, websearch_to_tsquery('english', %s) q
            WHERE tsv @@ q {date_filter} ORDER BY ts_rank_cd(tsv, q) DESC, id LIMIT %s""",
        [_or_query(query), *date_params, candidates],
    ).fetchall()

    sims = {row["id"]: row["sim"] for row in emb}
    missing = [row["id"] for row in fts if row["id"] not in sims]
    if missing:
        for row in conn.execute(
            "SELECT id, 1 - (embedding <=> %s::vector) AS sim FROM papers WHERE id = ANY(%s)", [literal, missing]
        ):
            sims[row["id"]] = row["sim"]

    score: dict[str, float] = {}
    for ranking, weight in ((emb, 1.0), (fts, FTS_WEIGHT)):
        for rank, row in enumerate(ranking):
            score[row["id"]] = score.get(row["id"], 0.0) + weight / (RRF_K + rank + 1)
    fused = sorted(score, key=lambda pid: (-score[pid], pid))
    kept = [(pid, sims[pid]) for pid in fused if sims[pid] >= MIN_SIMILARITY]
    note(
        "retrieval.papers",
        query=query,
        embedding_candidates=len(emb),
        fulltext_candidates=len(fts),
        below_min_similarity=len(fused) - len(kept),
        top=[(pid, round(sim, 3)) for pid, sim in kept[:5]],
        best_dropped=round(sims[fused[len(kept)]], 3) if len(kept) < len(fused) else None,
    )
    return kept


def search_papers(
    conn: psycopg.Connection,
    query: str,
    *,
    sort_by_date: bool = False,
    year_from: int | None = None,
    limit: int = 8,
) -> list[dict]:
    """Paper summaries with abstract and `similarity`. With sort_by_date: the most similar on-topic papers, newest first."""
    with span("embed", texts=1):
        vector = embed_queries([query])[0]
    ranked = rank_papers(conn, query, vector, year_from=year_from)
    if sort_by_date and ranked:
        pool = [hit for hit in ranked[:RECENT_POOL] if hit[1] >= ranked[0][1] - RECENT_MARGIN]
        ranked = sorted(pool, key=lambda hit: -hit[1])[:limit]
    else:
        ranked = ranked[:limit]
    if not ranked:
        return []
    rows = {
        row["id"]: row
        for row in conn.execute(
            f"SELECT {SUMMARY_COLUMNS}, p.abstract FROM {FROM} WHERE p.id = ANY(%s)", [[pid for pid, _ in ranked]]
        )
    }
    papers = [{**rows[pid], "similarity": round(sim, 3)} for pid, sim in ranked]
    if sort_by_date:
        papers.sort(key=lambda paper: (paper["publication_date"], paper["id"]), reverse=True)
    return papers
