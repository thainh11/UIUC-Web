"""Reload PostgreSQL from the cached OpenAlex pages and the faculty CSV.

Run: python -m ingestion.load_db
Drops every table, applies db/schema.sql, then bulk-loads (COPY). Embeddings and
faculty<->authorship links are NOT filled here; build_embeddings.py / link_authors.py do that.
"""

from pathlib import Path
import json
import os
import sys

from dotenv import load_dotenv
import psycopg

from ingestion.fetch_openalex import UIUC_ID
from ingestion.load_faculty import load_faculty

WORKS_DIR = Path("data/raw/openalex/works")
SCHEMA = Path("db/schema.sql")
TABLES = "paper_topics, paper_authors, faculty_keywords, papers, topics, authors, faculty, keywords"


def short_id(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def rebuild_abstract(inv: dict[str, list[int]]) -> str:
    words: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            words[i] = word
    return " ".join(words[i] for i in sorted(words))


def authorship_name(a: dict) -> str:
    """Display name; unresolved authors come as "Last, First", so flip those to "First Last"."""
    name = a["author"]["display_name"] or a.get("raw_author_name") or ""
    if not a["author"]["id"] and "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    return name


def read_works() -> list[dict]:
    pages = sorted(WORKS_DIR.glob("page_*.json"))
    if not pages:
        sys.exit(f"no pages in {WORKS_DIR}; run ingestion.fetch_openalex first")
    return [w for p in pages for w in json.loads(p.read_text())["results"]]


def build_rows(works: list[dict]) -> dict[str, list[tuple]]:
    topics: dict[str, tuple] = {}
    authors: dict[str, str] = {}
    papers, paper_topics, paper_authors = [], [], []

    def add_topic(t: dict) -> str:
        tid = short_id(t["id"])
        topics.setdefault(
            tid,
            (
                tid,
                t["display_name"],
                (t.get("subfield") or {}).get("display_name"),
                (t.get("field") or {}).get("display_name"),
                (t.get("domain") or {}).get("display_name"),
            ),
        )
        return tid

    for w in works:
        wid = short_id(w["id"])
        pt = w.get("primary_topic")
        primary = add_topic(pt) if pt else None
        oa = w.get("open_access") or {}
        source = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        papers.append(
            (
                wid,
                w.get("doi"),
                w["title"] or "",
                rebuild_abstract(w["abstract_inverted_index"]),
                w["publication_date"],
                w["cited_by_count"],
                bool(oa.get("is_oa")),
                oa.get("oa_status"),
                w["type"],
                source,
                [k["display_name"] for k in w.get("keywords") or []],
                primary,
            )
        )
        for t in w.get("topics") or []:
            paper_topics.append((wid, add_topic(t), t["score"]))
        for pos, a in enumerate(w["authorships"]):
            aid = short_id(a["author"]["id"]) if a["author"]["id"] else None
            if aid:
                authors[aid] = a["author"]["display_name"] or ""
            is_uiuc = any(short_id(i["id"]) == UIUC_ID for i in a["institutions"])
            paper_authors.append((wid, pos, aid, authorship_name(a), is_uiuc, bool(a["institutions"])))

    return {
        "topics": list(topics.values()),
        "authors": list(authors.items()),
        "papers": papers,
        "paper_topics": paper_topics,
        "paper_authors": paper_authors,
    }


def copy_rows(cur: psycopg.Cursor, table_cols: str, rows: list[tuple]) -> None:
    with cur.copy(f"COPY {table_cols} FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)


def load_faculty_rows(cur: psycopg.Cursor) -> int:
    faculty = load_faculty()
    keywords = sorted({k for f in faculty for k in f["keywords"]})
    copy_rows(cur, "keywords (text)", [(k,) for k in keywords])
    cur.execute("SELECT text, id FROM keywords")
    kw_id = dict(cur.fetchall())

    links = []
    for f in faculty:
        cur.execute(
            "INSERT INTO faculty (email, name, photo_url, position) VALUES (%s, %s, %s, %s) RETURNING id",
            (f["email"], f["name"], f["photo_url"], f["position"]),
        )
        fid = cur.fetchone()[0]
        links.extend((fid, kw_id[k]) for k in f["keywords"])
    copy_rows(cur, "faculty_keywords (faculty_id, keyword_id)", links)
    return len(faculty)


def main() -> None:
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL missing (see .env.example)")

    rows = build_rows(read_works())
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {TABLES} CASCADE")
        cur.execute(SCHEMA.read_text())
        copy_rows(cur, "topics (id, name, subfield, field, domain)", rows["topics"])
        copy_rows(cur, "authors (id, name)", rows["authors"])
        copy_rows(
            cur,
            "papers (id, doi, title, abstract, publication_date, cited_by_count, is_oa, oa_status,"
            " type, venue, keywords, primary_topic_id)",
            rows["papers"],
        )
        copy_rows(cur, "paper_topics (paper_id, topic_id, score)", rows["paper_topics"])
        copy_rows(cur, "paper_authors (paper_id, position, author_id, name, is_uiuc, has_institution)", rows["paper_authors"])
        n_fac = load_faculty_rows(cur)
    print({**{k: len(v) for k, v in rows.items()}, "faculty": n_fac})


if __name__ == "__main__":
    main()
