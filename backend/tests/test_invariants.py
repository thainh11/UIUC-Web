"""Data invariants, checked against the loaded database and the cache."""

from pathlib import Path
import json

from ingestion.load_db import rebuild_abstract
from ingestion.load_faculty import load_faculty

ROOT = Path(__file__).resolve().parents[2]
WORKS = ROOT / "data/raw/openalex/works"
CSV = ROOT / "data/raw/illinois-researchers.csv"


def test_paper_count_matches_cache_and_manifest(db):
    manifest = json.loads((WORKS / "manifest.json").read_text())
    cached = 0
    ids = []
    for page in sorted(WORKS.glob("page_*.json")):
        results = json.loads(page.read_text())["results"]
        cached += len(results)
        ids.extend(work["id"].rsplit("/", 1)[-1] for work in results)
    db_count = db.execute("SELECT count(*) AS n FROM papers").fetchone()["n"]
    assert db_count == cached == manifest["count"]
    assert len(ids) == len(set(ids))


def test_publication_dates_stay_inside_the_manifest_window(db):
    manifest = json.loads((WORKS / "manifest.json").read_text())
    outside = db.execute(
        "SELECT count(*) AS n FROM papers WHERE publication_date < %s OR publication_date > %s",
        (manifest["from"], manifest["to"]),
    ).fetchone()["n"]
    assert outside == 0


def test_no_empty_abstracts(db):
    empty = db.execute("SELECT count(*) AS n FROM papers WHERE abstract IS NULL OR abstract = ''").fetchone()["n"]
    assert empty == 0


def test_rebuilt_abstracts_match_the_cache(db):
    mismatches = 0
    missing = 0
    for page in sorted(WORKS.glob("page_*.json")):
        works = json.loads(page.read_text())["results"]
        expected = {work["id"].rsplit("/", 1)[-1]: rebuild_abstract(work["abstract_inverted_index"]) for work in works}
        rows = db.execute("SELECT id, abstract FROM papers WHERE id = ANY(%s)", (list(expected),)).fetchall()
        got = {row["id"]: row["abstract"] for row in rows}
        for paper_id, abstract in expected.items():
            if paper_id not in got:
                missing += 1
            elif got[paper_id] != abstract:
                mismatches += 1
    assert missing == 0
    assert mismatches == 0


def test_faculty_links_are_not_orphans_and_carry_a_method(db):
    orphans = db.execute(
        """SELECT count(*) AS n FROM paper_authors pa
           LEFT JOIN faculty f ON f.id = pa.faculty_id
           WHERE pa.faculty_id IS NOT NULL AND f.id IS NULL"""
    ).fetchone()["n"]
    incomplete = db.execute(
        """SELECT count(*) AS n FROM paper_authors
           WHERE faculty_id IS NOT NULL
             AND (match_method IS NULL OR match_score IS NULL OR match_method NOT IN ('keywords', 'name', 'semantic'))"""
    ).fetchone()["n"]
    assert orphans == 0
    assert incomplete == 0


def test_faculty_and_keyword_counts_match_the_csv(db):
    faculty = load_faculty(CSV)
    keywords = {keyword for person in faculty for keyword in person["keywords"]}
    db_faculty = db.execute("SELECT count(*) AS n FROM faculty").fetchone()["n"]
    db_keywords = db.execute("SELECT count(*) AS n FROM keywords").fetchone()["n"]
    assert db_faculty == len(faculty)
    assert db_keywords == len(keywords)
