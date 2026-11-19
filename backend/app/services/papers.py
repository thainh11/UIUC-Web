"""Paper queries shared by the papers and faculty routers."""

import psycopg

SORTS = {
    "date": "p.publication_date DESC, p.id",
    "citations": "p.cited_by_count DESC, p.id",
    "relevance": "relevance DESC, p.publication_date DESC, p.id",
}

SUMMARY_COLUMNS = """
  p.id, p.doi, p.title, p.publication_date, p.cited_by_count, p.is_oa, p.venue, p.type,
  t.name AS topic, t.field, t.domain,
  (SELECT coalesce(json_agg(a.name ORDER BY a.position), '[]'::json)
     FROM (SELECT name, position FROM paper_authors WHERE paper_id = p.id ORDER BY position LIMIT 6) a) AS authors,
  (SELECT count(*) FROM paper_authors WHERE paper_id = p.id) AS author_count,
  (SELECT coalesce(json_agg(json_build_object('id', f.id, 'name', f.name) ORDER BY f.name), '[]'::json)
     FROM (SELECT DISTINCT faculty_id FROM paper_authors
            WHERE paper_id = p.id AND faculty_id IS NOT NULL) x
     JOIN faculty f ON f.id = x.faculty_id) AS faculty
"""
FROM = "papers p LEFT JOIN topics t ON t.id = p.primary_topic_id"


def list_papers(
    conn: psycopg.Connection,
    *,
    query: str | None = None,
    topic: str | None = None,
    subfield: str | None = None,
    field: str | None = None,
    domain: str | None = None,
    faculty_id: int | None = None,
    sort: str = "date",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    where, params = ["TRUE"], []
    rank = "NULL::real"
    rank_params: list = []
    if query:
        where.append("p.tsv @@ websearch_to_tsquery('english', %s)")
        params.append(query)
        rank = "ts_rank_cd(p.tsv, websearch_to_tsquery('english', %s))"
        rank_params = [query]
    for column, value in (("p.primary_topic_id", topic), ("t.subfield", subfield), ("t.field", field), ("t.domain", domain)):
        if value:
            where.append(f"{column} = %s")
            params.append(value)
    if faculty_id is not None:
        where.append("EXISTS (SELECT 1 FROM paper_authors pa WHERE pa.paper_id = p.id AND pa.faculty_id = %s)")
        params.append(faculty_id)
    if sort == "relevance" and not query:
        sort = "date"
    clause = " AND ".join(where)
    total = conn.execute(f"SELECT count(*) AS n FROM {FROM} WHERE {clause}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT {SUMMARY_COLUMNS}, {rank} AS relevance FROM {FROM} WHERE {clause} "
        f"ORDER BY {SORTS[sort]} LIMIT %s OFFSET %s",
        [*rank_params, *params, page_size, (page - 1) * page_size],
    ).fetchall()
    return rows, total
