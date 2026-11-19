"""API contract: status codes, pagination, filters and response shapes against the loaded database."""

from backend.app.routers.faculty import like

FROM = "papers p LEFT JOIN topics t ON t.id = p.primary_topic_id"


def _count(db, where: str, params: list) -> int:
    return db.execute(f"SELECT count(*) AS n FROM {FROM} WHERE {where}", params).fetchone()["n"]


def test_papers_total_matches_count(client, db):
    body = client.get("/api/papers", params={"page_size": 1}).json()
    assert body["total"] == _count(db, "TRUE", [])
    page2 = client.get("/api/papers", params={"page": 2, "page_size": 20}).json()
    assert page2["total"] == body["total"]


def test_faculty_total_matches_count(client, db):
    body = client.get("/api/faculty", params={"page_size": 1}).json()
    assert body["total"] == db.execute("SELECT count(*) AS n FROM faculty").fetchone()["n"]


def test_monthly_counts_cover_every_paper_and_split_out_year_only_dates(client, db):
    months = client.get("/api/stats/publications-by-month").json()
    assert sum(m["count"] for m in months) == _count(db, "TRUE", [])
    jan_first = _count(db, "to_char(p.publication_date, 'MM-DD') = '01-01'", [])
    assert sum(m["year_only"] for m in months) == jan_first
    assert all(0 <= m["year_only"] <= m["count"] for m in months)
    assert all(m["year_only"] == 0 for m in months if not m["month"].endswith("-01"))


def test_topic_field_and_domain_filters_match_the_subset(client, db):
    topic = db.execute(
        "SELECT primary_topic_id AS id, count(*) AS n FROM papers WHERE primary_topic_id IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 1"
    ).fetchone()
    field = db.execute(
        """SELECT t.field AS name, count(*) AS n FROM papers p JOIN topics t ON t.id = p.primary_topic_id
           WHERE t.field IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 1"""
    ).fetchone()
    domain = db.execute(
        """SELECT t.domain AS name, count(*) AS n FROM papers p JOIN topics t ON t.id = p.primary_topic_id
           WHERE t.domain IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 1"""
    ).fetchone()
    assert client.get("/api/papers", params={"topic": topic["id"], "page_size": 1}).json()["total"] == topic["n"]
    assert client.get("/api/papers", params={"field": field["name"], "page_size": 1}).json()["total"] == field["n"]
    assert client.get("/api/papers", params={"domain": domain["name"], "page_size": 1}).json()["total"] == domain["n"]
    assert topic["n"] < client.get("/api/papers", params={"page_size": 1}).json()["total"]


def _descending(values) -> bool:
    return list(values) == sorted(values, reverse=True)


def test_sort_relevance_and_citations_are_descending(client):
    relevant = client.get("/api/papers", params={"query": "machine learning", "sort": "relevance", "page_size": 20})
    cited = client.get("/api/papers", params={"sort": "citations", "page_size": 20})
    assert relevant.status_code == cited.status_code == 200
    relevance = [item["relevance"] for item in relevant.json()["items"]]
    citations = [item["cited_by_count"] for item in cited.json()["items"]]
    assert relevance and all(score is not None for score in relevance)
    assert _descending(relevance)
    assert _descending(citations)


def test_faculty_paper_count_matches_the_papers_returned(client, db):
    top = db.execute(
        """SELECT faculty_id AS id, count(DISTINCT paper_id) AS n
           FROM paper_authors WHERE faculty_id IS NOT NULL
           GROUP BY faculty_id ORDER BY n DESC LIMIT 1"""
    ).fetchone()
    body = client.get(f"/api/faculty/{top['id']}").json()
    assert body["paper_count"] == top["n"]
    assert len(body["papers"]) == min(top["n"], 100)  # the detail payload embeds the 100 newest papers


def test_missing_ids_are_404(client):
    assert client.get("/api/papers/Wdoesnotexist").status_code == 404
    assert client.get("/api/faculty/999999999").status_code == 404


def test_page_size_over_the_limit_is_422(client):
    assert client.get("/api/papers", params={"page_size": 51}).status_code == 422
    assert client.get("/api/faculty", params={"page_size": 101}).status_code == 422


def test_page_past_the_limit_is_422_not_a_database_error(client):
    # A page this large used to overflow the SQL OFFSET and return 500.
    huge = "99999999999999999999"
    assert client.get("/api/papers", params={"page": huge}).status_code == 422
    assert client.get("/api/faculty", params={"page": huge}).status_code == 422


def test_faculty_wildcards_are_literals(client, db):
    everyone = db.execute("SELECT count(*) AS n FROM faculty").fetchone()["n"]
    for text in ("%", "_"):
        escaped = db.execute(
            """SELECT count(*) AS n FROM faculty f
               WHERE f.name ILIKE %s OR EXISTS (
                   SELECT 1 FROM faculty_keywords fk JOIN keywords k ON k.id = fk.keyword_id
                   WHERE fk.faculty_id = f.id AND k.text ILIKE %s)""",
            (like(text), like(text)),
        ).fetchone()["n"]
        assert client.get("/api/faculty", params={"query": text, "page_size": 1}).json()["total"] == escaped
        assert escaped < everyone


def test_paper_query_wildcards_are_not_match_all(client, db):
    everyone = _count(db, "TRUE", [])
    for text in ("%", "_"):
        body = client.get("/api/papers", params={"query": text, "page_size": 1})
        assert body.status_code == 200
        assert body.json()["total"] == 0
        assert body.json()["total"] < everyone
    hundred = db.execute(
        "SELECT count(*) AS n FROM papers WHERE tsv @@ websearch_to_tsquery('english', %s)",
        ("100%",),
    ).fetchone()["n"]
    assert client.get("/api/papers", params={"query": "100%", "page_size": 1}).json()["total"] == hundred
    assert hundred < everyone
