"""Independent recall check for faculty linking.

Samples 30 faculty and compares papers linked in the database with the OpenAlex
work count for that person over the same window. Also checks papers truncated at
100 authors: the single-work endpoint returns the full authorship list.

    python -m eval.faculty_recall
"""

import json
import random
import sys

from dotenv import load_dotenv
import httpx

from ingestion.fetch_openalex import TYPES, UIUC_ID, get
from ingestion.link_authors import name_match, name_tokens

from .io import GOLD, ROOT, SEED, connect

SAMPLE = 30


def _author_id(client: httpx.Client, name: str) -> dict | None:
    data = get(
        client,
        "/authors",
        {
            "search": name,
            "filter": f"affiliations.institution.id:{UIUC_ID}",
            "per_page": 5,
            "select": "id,display_name,works_count",
        },
    )
    tokens = name_tokens(name)
    exact, loose = [], []
    for author in data["results"]:
        tier = name_match(tokens, name_tokens(author["display_name"]))
        if tier == "exact":
            exact.append(author)
        elif tier == "loose":
            loose.append(author)
    chosen = exact or loose
    if not chosen:
        return None
    chosen.sort(key=lambda author: author.get("works_count") or 0, reverse=True)
    return {"id": chosen[0]["id"].rsplit("/", 1)[-1], "name": chosen[0]["display_name"], "ambiguous": len(chosen) > 1}


def _work_ids(client: httpx.Client, author_id: str, start: str, end: str) -> list[str]:
    filt = ",".join(
        [
            f"authorships.author.id:{author_id}",
            f"authorships.institutions.id:{UIUC_ID}",
            f"from_publication_date:{start}",
            f"to_publication_date:{end}",
            "has_abstract:true",
            "is_paratext:false",
            f"type:{TYPES}",
        ]
    )
    cursor = "*"
    ids = []
    while cursor:
        data = get(client, "/works", {"filter": filt, "per_page": 100, "select": "id", "cursor": cursor})
        ids.extend(work["id"].rsplit("/", 1)[-1] for work in data["results"])
        cursor = data["meta"]["next_cursor"] if data["results"] else None
    return ids


def _truncated_hits(client: httpx.Client, paper_ids: list[str], faculty_tokens: list[str]) -> int:
    """Papers in the 100-author cap where this faculty name only appears past position 99."""
    found = 0
    for paper_id in paper_ids:
        work = get(client, f"/works/{paper_id}", {"select": "authorships"})
        for position, authorship in enumerate(work.get("authorships") or []):
            if position < 100:
                continue
            tier = name_match(faculty_tokens, name_tokens(authorship["author"]["display_name"] or ""))
            if tier == "exact":
                found += 1
                break
    return found


def main() -> None:
    load_dotenv()
    import os

    key = os.environ.get("OPENALEX_API_KEY") or sys.exit("OPENALEX_API_KEY missing")
    with connect() as conn:
        manifest = json.loads((ROOT / "data" / "raw" / "openalex" / "works" / "manifest.json").read_text())
        faculty = conn.execute("SELECT id, name FROM faculty ORDER BY id").fetchall()
        capped = {
            row["paper_id"]
            for row in conn.execute("SELECT paper_id FROM paper_authors GROUP BY paper_id HAVING count(*) = 100")
        }
        picked = random.Random(SEED).sample(list(faculty), SAMPLE)
        linked_counts = {
            row["faculty_id"]: row["n"]
            for row in conn.execute(
                """SELECT faculty_id, count(DISTINCT paper_id) AS n FROM paper_authors
                   WHERE faculty_id IS NOT NULL GROUP BY faculty_id"""
            )
        }
    rows = []
    with httpx.Client(headers={"Authorization": f"Bearer {key}"}, timeout=60) as client:
        for person in picked:
            author = _author_id(client, person["name"])
            record = {
                "faculty_id": person["id"],
                "faculty_name": person["name"],
                "system_papers": linked_counts.get(person["id"], 0),
            }
            if author is None:
                record["openalex_author"] = None
                rows.append(record)
                print(f"{person['name']}: no OpenAlex author at UIUC")
                continue
            work_ids = _work_ids(client, author["id"], manifest["from"], manifest["to"])
            hidden = _truncated_hits(client, [wid for wid in work_ids if wid in capped], name_tokens(person["name"]))
            record.update(
                {
                    "openalex_author": author["id"],
                    "openalex_name": author["name"],
                    "ambiguous": author["ambiguous"],
                    "openalex_papers": len(work_ids),
                    "truncated_past_100": hidden,
                }
            )
            rows.append(record)
            print(
                f"{person['name']}: system {record['system_papers']}, "
                f"openalex {len(work_ids)}, truncated {hidden}"
            )
    comparable = [row for row in rows if row.get("openalex_author")]
    summary = {
        "sample": SAMPLE,
        "resolved": len(comparable),
        "system_papers": sum(row["system_papers"] for row in comparable),
        "openalex_papers": sum(row["openalex_papers"] for row in comparable),
        "truncated_past_100": sum(row["truncated_past_100"] for row in comparable),
        "capped_papers_in_corpus": len(capped),
    }
    GOLD.mkdir(parents=True, exist_ok=True)
    (GOLD / "faculty_recall.json").write_text(
        json.dumps({"summary": summary, "faculty": rows}, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
