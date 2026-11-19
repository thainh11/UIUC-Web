"""Download UIUC works from OpenAlex into data/raw/openalex/works/ (resumable).

Run: python -m ingestion.fetch_openalex [--from-date YYYY-MM-DD] [--to-date YYYY-MM-DD]

Selection (no ranking, no truncation): UIUC-affiliated works in the date window that
have an abstract, are not paratext, and are of type article/preprint/conference-paper/review.
Aborts if the match count exceeds --max-works rather than silently dropping works.

Output: page_00001.json, ... each {"cursor", "next_cursor", "results"}, plus manifest.json.
Re-running resumes from the last saved page's next_cursor; changed parameters abort.
"""

from datetime import date
from pathlib import Path
import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv
import httpx

API = "https://api.openalex.org"
UIUC_ID = "I157725225"
UIUC_ROR = "ror:047426m28"
TYPES = "article|preprint|conference-paper|review"
SELECT = ",".join(
    [
        "id",
        "doi",
        "title",
        "publication_date",
        "abstract_inverted_index",
        "authorships",
        "primary_topic",
        "topics",
        "keywords",
        "cited_by_count",
        "open_access",
        "type",
        "primary_location",
    ]
)
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6


def years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - years, day=28)


def get(client: httpx.Client, path: str, params: dict) -> dict:
    for attempt in range(MAX_ATTEMPTS):
        try:
            r = client.get(f"{API}{path}", params=params)
        except httpx.TransportError as e:
            err = repr(e)
        else:
            if r.status_code == 200:
                return r.json()
            if r.status_code not in RETRY_STATUS:
                sys.exit(f"{path}: HTTP {r.status_code}: {r.text[:300]}")
            err = f"HTTP {r.status_code}"
            retry_after = r.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                time.sleep(int(retry_after))
        wait = 2**attempt
        print(f"{path}: {err}; retry in {wait}s ({attempt + 1}/{MAX_ATTEMPTS})", file=sys.stderr)
        time.sleep(wait)
    sys.exit(f"{path}: giving up after {MAX_ATTEMPTS} attempts")


def verify_institution(client: httpx.Client) -> None:
    inst = get(client, f"/institutions/{UIUC_ROR}", {"select": "id,display_name,ror"})
    if inst["id"].rsplit("/", 1)[-1] != UIUC_ID:
        sys.exit(f"{UIUC_ROR} resolved to {inst['id']}, expected {UIUC_ID}")
    print(f"institution: {inst['display_name']} ({inst['id']})")


def write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, path)


def main() -> None:
    today = date.today()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--from-date", default=years_ago(today, 2).isoformat())
    ap.add_argument("--to-date", default=today.isoformat())
    ap.add_argument("--max-works", type=int, default=20_000)
    ap.add_argument("--out", type=Path, default=Path("data/raw/openalex/works"))
    args = ap.parse_args()

    load_dotenv()
    key = os.environ.get("OPENALEX_API_KEY")
    if not key:
        sys.exit("OPENALEX_API_KEY missing (set it in .env); cursor paging requires a key")

    flt = ",".join(
        [
            f"authorships.institutions.id:{UIUC_ID}",
            f"from_publication_date:{args.from_date}",
            f"to_publication_date:{args.to_date}",
            "has_abstract:true",
            "is_paratext:false",
            f"type:{TYPES}",
        ]
    )
    manifest = {"filter": flt, "select": SELECT, "per_page": 100}

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()).get("params") != manifest:
        sys.exit(f"{manifest_path} has different parameters; use another --out or delete it")

    with httpx.Client(headers={"Authorization": f"Bearer {key}"}, timeout=60) as client:
        verify_institution(client)

        total = get(client, "/works", {"filter": flt, "per_page": 1, "select": "id"})["meta"]["count"]
        print(f"matching works: {total} (window {args.from_date}..{args.to_date})")
        if total > args.max_works:
            sys.exit(f"{total} works exceed --max-works={args.max_works}; narrow the filter or raise the cap")

        pages = sorted(args.out.glob("page_*.json"))
        cursor = "*"
        fetched = 0
        if pages:
            for p in pages:
                fetched += len(json.loads(p.read_text())["results"])
            cursor = json.loads(pages[-1].read_text())["next_cursor"]
            print(f"resuming: {len(pages)} pages, {fetched} works cached")
        write_json(
            manifest_path,
            {"params": manifest, "from": args.from_date, "to": args.to_date, "count": total},
        )

        page_no = len(pages)
        while cursor:
            data = get(
                client,
                "/works",
                {"filter": flt, "per_page": 100, "select": SELECT, "cursor": cursor},
            )
            results = data["results"]
            page_no += 1
            write_json(
                args.out / f"page_{page_no:05d}.json",
                {"cursor": cursor, "next_cursor": data["meta"]["next_cursor"], "results": results},
            )
            fetched += len(results)
            cursor = data["meta"]["next_cursor"] if results else None
            print(f"page {page_no}: {fetched}/{total}", end="\r", flush=True)

    print(f"\ndone: {fetched} works in {page_no} pages -> {args.out}")
    if fetched != total:
        sys.exit(f"fetched {fetched} != reported {total}; data changed mid-run or paging bug, re-check")


if __name__ == "__main__":
    main()
