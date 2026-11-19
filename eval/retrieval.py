"""Query set and the full-text / embedding baselines."""

import os
import sys

from dotenv import load_dotenv
import httpx
import psycopg

from backend.agent.search import rank_papers, search_papers
from ingestion.build_embeddings import QUERY_INSTRUCTION

from .metrics import mean, mrr, ndcg_at_k, precision_at_k

RANK_K = 20
TOP_K = 10

# Ten prompts from the task statement plus variants, then ten hard queries
# (two concepts, synonyms, and out-of-domain). Topic queries are sampled from the DB.
MANUAL_QUERIES = [
    {"id": "q-recent-01", "kind": "recent", "text": "most recent UIUC papers on AI in war conflict"},
    {"id": "q-recent-02", "kind": "recent", "text": "latest UIUC papers on artificial intelligence in war and conflict"},
    {"id": "q-recent-03", "kind": "recent", "text": "newest papers on AI for armed conflict"},
    {"id": "q-recent-04", "kind": "recent", "text": "most recent research on machine learning in warfare"},
    {"id": "q-recent-05", "kind": "recent", "text": "recent UIUC papers about AI applications in military conflict"},
    {
        "id": "q-faculty-01",
        "kind": "faculty",
        "text": "faculty members who work on Computer Vision in Healthcare",
        "concepts": ["computer vision", "healthcare"],
    },
    {
        "id": "q-faculty-02",
        "kind": "faculty",
        "text": "faculty working on computer vision for healthcare",
        "concepts": ["computer vision", "healthcare"],
    },
    {
        "id": "q-faculty-03",
        "kind": "faculty",
        "text": "which faculty study computer vision in medicine",
        "concepts": ["computer vision", "medicine"],
    },
    {
        "id": "q-faculty-04",
        "kind": "faculty",
        "text": "faculty members doing healthcare computer vision",
        "concepts": ["computer vision", "healthcare"],
    },
    {
        "id": "q-faculty-05",
        "kind": "faculty",
        "text": "researchers who work on computer vision and healthcare",
        "concepts": ["computer vision", "healthcare"],
    },
    {"id": "q-hard-01", "kind": "hard", "text": "graph neural networks for drug discovery"},
    {"id": "q-hard-02", "kind": "hard", "text": "transformers for climate forecasting"},
    {"id": "q-hard-03", "kind": "hard", "text": "reinforcement learning for robotic manipulation"},
    {"id": "q-syn-01", "kind": "hard", "text": "large language models"},
    {"id": "q-syn-02", "kind": "hard", "text": "deep learning for image recognition"},
    {"id": "q-syn-03", "kind": "hard", "text": "cancer genome sequencing"},
    {"id": "q-ood-01", "kind": "ood", "text": "best pizza restaurants in Chicago"},
    {"id": "q-ood-02", "kind": "ood", "text": "Taylor Swift concert tour ticket prices"},
    {"id": "q-ood-03", "kind": "ood", "text": "competitive speedcubing world records"},
    {"id": "q-ood-04", "kind": "ood", "text": "how to change a flat car tire"},
]


def topic_queries(conn: psycopg.Connection, rng, n: int = 20, min_papers: int = 40) -> list[dict]:
    """Queries whose relevance comes from the OpenAlex topic labels, not from the text."""
    rows = conn.execute(
        """SELECT t.id, t.name FROM papers p JOIN topics t ON t.id = p.primary_topic_id
           GROUP BY t.id, t.name HAVING count(*) >= %s ORDER BY t.id""",
        (min_papers,),
    ).fetchall()
    if len(rows) < n:
        sys.exit(f"need {n} topics with at least {min_papers} papers, found {len(rows)}")
    picked = sorted(rng.sample(list(rows), n), key=lambda row: row["id"])
    return [{"id": f"topic-{i:02d}", "kind": "topic", "text": row["name"], "topic_id": row["id"]} for i, row in enumerate(picked, start=1)]


def search_fts(conn: psycopg.Connection, query: str, k: int = RANK_K) -> list[dict]:
    return conn.execute(
        """SELECT p.id, p.publication_date
           FROM papers p
           WHERE p.tsv @@ websearch_to_tsquery('english', %s)
           ORDER BY ts_rank_cd(p.tsv, websearch_to_tsquery('english', %s)) DESC, p.publication_date DESC, p.id
           LIMIT %s""",
        (query, query, k),
    ).fetchall()


def embed_queries(texts: list[str]) -> list[list[float]] | None:
    """Qwen3-Embedding query vectors. None when the embedding server is down."""
    load_dotenv()
    url = os.environ.get("EMBEDDING_URL", "http://localhost:8032/v1")
    model = os.environ.get("EMBEDDING_MODEL", "Qwen3-Embedding-0.6B")
    prefixed = [f"Instruct: {QUERY_INSTRUCTION}\nQuery:{text}" for text in texts]
    vectors: list[list[float]] = []
    try:
        with httpx.Client(timeout=120) as client:
            for start in range(0, len(prefixed), 16):
                chunk = prefixed[start : start + 16]
                response = client.post(f"{url}/embeddings", json={"model": model, "input": chunk})
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item["index"])
                vectors.extend(item["embedding"] for item in data)
    except httpx.HTTPError as exc:
        print(f"embedding server unavailable: {exc}", file=sys.stderr)
        return None
    if len(vectors) != len(texts):
        sys.exit("embedding server returned the wrong number of vectors")
    return vectors


def search_embedding(conn: psycopg.Connection, vector: list[float], k: int = RANK_K) -> list[dict]:
    literal = "[" + ",".join(f"{value:.8f}" for value in vector) + "]"
    return conn.execute(
        """SELECT p.id, p.publication_date
           FROM papers p
           ORDER BY p.embedding <=> %s::vector, p.publication_date DESC, p.id
           LIMIT %s""",
        (literal, k),
    ).fetchall()


def search_hybrid(conn: psycopg.Connection, text: str, vector: list[float], k: int = RANK_K) -> list[dict]:
    """What the chat agent's search_papers ranks: fused full-text and embedding, minus papers below the similarity floor."""
    ids = [paper_id for paper_id, _sim in rank_papers(conn, text, vector)][:k]
    if not ids:
        return []
    dates = {row["id"]: row["publication_date"] for row in conn.execute("SELECT id, publication_date FROM papers WHERE id = ANY(%s)", (ids,))}
    return [{"id": paper_id, "publication_date": dates[paper_id]} for paper_id in ids]


def recent_date_sorted_precision(conn: psycopg.Connection, queries: list[dict], limit: int = 6) -> float | None:
    """Share of relevant papers in the date-sorted list the assistant gets for "most recent" questions."""
    shares = []
    for query in queries:
        if query["kind"] != "recent":
            continue
        papers = search_papers(conn, query["text"], sort_by_date=True, limit=limit)
        shares.append(mean([float(query["qrels"].get(paper["id"], 0) > 0) for paper in papers]) if papers else 0.0)
    return mean(shares)


def _topic_grades(conn: psycopg.Connection, topic_id: str, paper_ids: list[str]) -> list[int]:
    if not paper_ids:
        return []
    rows = conn.execute(
        """SELECT p.id,
                  CASE WHEN p.primary_topic_id = %s THEN 2
                       WHEN EXISTS (
                         SELECT 1 FROM paper_topics pt WHERE pt.paper_id = p.id AND pt.topic_id = %s
                       ) THEN 1 ELSE 0 END AS grade
           FROM papers p WHERE p.id = ANY(%s)""",
        (topic_id, topic_id, paper_ids),
    ).fetchall()
    grades = {row["id"]: row["grade"] for row in rows}
    return [grades.get(paper_id, 0) for paper_id in paper_ids]


def _topic_ideal(conn: psycopg.Connection, topic_id: str, k: int = TOP_K) -> list[int]:
    row = conn.execute(
        """SELECT count(*) FILTER (WHERE primary_topic_id = %s) AS g2,
                  count(*) FILTER (
                    WHERE primary_topic_id IS DISTINCT FROM %s
                      AND EXISTS (SELECT 1 FROM paper_topics pt WHERE pt.paper_id = papers.id AND pt.topic_id = %s)
                  ) AS g1
           FROM papers""",
        (topic_id, topic_id, topic_id),
    ).fetchone()
    ideal = [2] * min(row["g2"], k)
    ideal += [1] * min(row["g1"], k - len(ideal))
    return ideal


def _ranked_grades(query: dict, paper_ids: list[str], conn: psycopg.Connection) -> tuple[list[int], list[int]]:
    if query["kind"] == "topic":
        return _topic_grades(conn, query["topic_id"], paper_ids), _topic_ideal(conn, query["topic_id"])
    qrels = query.get("qrels")
    if not isinstance(qrels, dict):
        sys.exit(f"{query['id']} has no qrels")
    return [int(qrels.get(paper_id, 0)) for paper_id in paper_ids], [int(grade) for grade in qrels.values()]


def score_rankings(queries: list[dict], rankings: dict[str, list[dict]], conn: psycopg.Connection) -> dict[str, float | None]:
    ndcgs, precisions, reciprocal = [], [], []
    topic_precision = []
    ood_empty = []
    for query in queries:
        hits = rankings.get(query["id"], [])
        paper_ids = [hit["id"] for hit in hits]
        ranked, judged = _ranked_grades(query, paper_ids, conn)
        if query["kind"] == "ood":
            ood_empty.append(0.0 if hits else 1.0)
            continue
        ndcgs.append(ndcg_at_k(ranked, TOP_K, judged))
        precisions.append(precision_at_k(ranked, 5))
        reciprocal.append(mrr(ranked))
        if query["kind"] == "recent":
            # "Most recent" first picks the on-topic papers, then sorts them by date, so what matters is topic precision.
            topic_precision.append(precision_at_k(ranked, TOP_K))
    return {
        "ndcg@10": mean(ndcgs),
        "p@5": mean(precisions),
        "mrr": mean(reciprocal),
        "recent.topic_precision@10": mean(topic_precision),
        "ood.empty": mean(ood_empty),
    }


def faculty_sets(conn: psycopg.Connection, concepts: list[str]) -> tuple[set[int], set[int]]:
    """Faculty matched by keywords, and faculty with at least two linked papers that mention every concept."""
    keyword_where = " AND ".join(
        """EXISTS (SELECT 1 FROM faculty_keywords fk JOIN keywords k ON k.id = fk.keyword_id
                    WHERE fk.faculty_id = f.id AND k.text ILIKE %s)"""
        for _ in concepts
    )
    keyword_rows = conn.execute(
        f"SELECT f.id FROM faculty f WHERE {keyword_where}",
        [f"%{concept}%" for concept in concepts],
    ).fetchall()
    paper_where = " AND ".join("lower(p.title || ' ' || p.abstract) LIKE %s" for _ in concepts)
    paper_rows = conn.execute(
        f"""SELECT pa.faculty_id AS id FROM paper_authors pa JOIN papers p ON p.id = pa.paper_id
            WHERE pa.faculty_id IS NOT NULL AND {paper_where}
            GROUP BY pa.faculty_id HAVING count(DISTINCT pa.paper_id) >= 2""",
        [f"%{concept.casefold()}%" for concept in concepts],
    ).fetchall()
    return {row["id"] for row in keyword_rows}, {row["id"] for row in paper_rows}


def paper_cards(conn: psycopg.Connection, paper_ids: list[str]) -> list[dict]:
    if not paper_ids:
        return []
    rows = conn.execute(
        """SELECT p.id, p.title, p.abstract, p.publication_date, t.name AS topic
           FROM papers p LEFT JOIN topics t ON t.id = p.primary_topic_id
           WHERE p.id = ANY(%s)""",
        (paper_ids,),
    ).fetchall()
    order = {paper_id: i for i, paper_id in enumerate(paper_ids)}
    return sorted(rows, key=lambda row: order[row["id"]])
