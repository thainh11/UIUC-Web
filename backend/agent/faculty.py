"""Faculty search: papers on the topic that a person wrote, plus embedding match against their keywords.

Faculty keywords are noisy and numerous, so a person's keyword string is never embedded as one text. Each
keyword has its own embedding; a concept is "supported" by the closest single keyword. Paper evidence is the
person's linked papers among the papers closest to the whole topic phrase, which is where "computer vision" AND
"healthcare" are both required without splitting the query.
"""

import psycopg

from ..app.routers.faculty import FACULTY_COLUMNS, like
from .embed import embed_queries, vector_literal
from .search import RRF_K, rank_papers
from .trace import note, span

PAPER_POOL = 200  # papers closest to the topic that are scanned for linked faculty
KEYWORD_MIN = 0.58  # cosine; "computer vision" vs "machine vision" 0.60, vs "computer science" 0.54
MAX_EVIDENCE = 3


def search_faculty(
    conn: psycopg.Connection,
    topic: str,
    concepts: list[str] | None = None,
    *,
    limit: int = 8,
) -> list[dict]:
    """Faculty ranked by evidence for `topic`. `concepts` are its parts; every one must be supported by a keyword.

    Ranking tiers: both paper and keyword evidence, then paper evidence only, then keyword evidence only.
    """
    concepts = [c.strip() for c in (concepts or []) if c.strip()] or [topic]
    with span("embed", texts=1 + len(concepts)):
        vectors = embed_queries([topic, *concepts])
    topic_vector, concept_vectors = vectors[0], vectors[1:]

    papers: dict[int, list[tuple[float, str, float]]] = {}  # faculty -> (rrf weight, paper id, similarity)
    ranked = rank_papers(conn, topic, topic_vector, candidates=PAPER_POOL)
    if ranked:
        sims = dict(ranked)
        order = {paper_id: rank for rank, (paper_id, _) in enumerate(ranked)}
        for row in conn.execute(
            "SELECT DISTINCT paper_id, faculty_id FROM paper_authors WHERE faculty_id IS NOT NULL AND paper_id = ANY(%s)",
            [list(sims)],
        ):
            papers.setdefault(row["faculty_id"], []).append(
                (1.0 / (RRF_K + order[row["paper_id"]] + 1), row["paper_id"], sims[row["paper_id"]])
            )

    keywords: dict[int, dict[str, tuple[float, str]]] = {}  # faculty -> concept -> (similarity, keyword)
    for concept, vector in zip(concepts, concept_vectors):
        literal = vector_literal(vector)
        for row in conn.execute(
            """SELECT DISTINCT ON (fk.faculty_id) fk.faculty_id, k.text, 1 - (k.embedding <=> %s::vector) AS sim
               FROM faculty_keywords fk JOIN keywords k ON k.id = fk.keyword_id
               ORDER BY fk.faculty_id, k.embedding <=> %s::vector""",
            [literal, literal],
        ):
            keywords.setdefault(row["faculty_id"], {})[concept] = (row["sim"], row["text"])

    scored = []
    for faculty_id in papers.keys() | keywords.keys():
        by_concept = keywords.get(faculty_id, {})
        supported = len(by_concept) == len(concepts) and all(sim >= KEYWORD_MIN for sim, _ in by_concept.values())
        weight = sum(w for w, _, _ in papers.get(faculty_id, ()))
        if faculty_id not in papers and not supported:
            continue
        tier = 2 if (faculty_id in papers and supported) else 1 if faculty_id in papers else 0
        floor = min((sim for sim, _ in by_concept.values()), default=0.0)
        scored.append((tier, weight, floor, faculty_id))
    scored.sort(reverse=True)
    chosen = scored[:limit]
    note(
        "retrieval.faculty",
        topic=topic,
        concepts=concepts,
        paper_pool=len(papers),
        keyword_pool=len(keywords),
        eligible=len(scored),
        top=[{"faculty_id": f, "tier": t, "paper_weight": round(w, 4)} for t, w, _floor, f in chosen[:5]],
    )
    if not chosen:
        return []

    ids = [faculty_id for *_, faculty_id in chosen]
    people = {row["id"]: row for row in conn.execute(f"SELECT {FACULTY_COLUMNS} FROM faculty f WHERE f.id = ANY(%s)", [ids])}
    titles = {
        row["id"]: row
        for row in conn.execute(
            "SELECT id, title, publication_date FROM papers WHERE id = ANY(%s)",
            [[pid for faculty_id in ids for _, pid, _ in papers.get(faculty_id, ())]],
        )
    }
    results = []
    for tier, _weight, _floor, faculty_id in chosen:
        matched = sorted(papers.get(faculty_id, ()), reverse=True)
        by_concept = keywords.get(faculty_id, {})
        results.append(
            {
                **people[faculty_id],
                "evidence": ["keywords", "papers", "papers and keywords"][tier],
                "matching_papers": len(matched),
                "papers": [
                    {"id": pid, "title": titles[pid]["title"], "publication_date": titles[pid]["publication_date"]}
                    for _, pid, _ in matched[:MAX_EVIDENCE]
                ],
                "keywords": [
                    {"concept": concept, "keyword": text, "similarity": round(sim, 3)}
                    for concept, (sim, text) in by_concept.items()
                    if sim >= KEYWORD_MIN
                ],
            }
        )
    return results


def find_faculty_by_name(conn: psycopg.Connection, name: str, limit: int = 8) -> list[dict]:
    return conn.execute(
        f"""SELECT * FROM (SELECT {FACULTY_COLUMNS} FROM faculty f WHERE f.name ILIKE %s) s
            ORDER BY paper_count DESC, name LIMIT %s""",
        [like(name), limit],
    ).fetchall()
