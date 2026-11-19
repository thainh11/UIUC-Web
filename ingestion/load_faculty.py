"""Parse data/raw/illinois-researchers.csv into clean faculty records."""

from pathlib import Path
import csv
import io

CSV_PATH = Path("data/raw/illinois-researchers.csv")


def parse_keywords(raw: str) -> list[str]:
    """Parse a PostgreSQL array literal like {"a b",c,"d\\\\e"} into unique lower-cased keywords."""
    if not (raw.startswith("{") and raw.endswith("}")):
        raise ValueError(f"not an array literal: {raw[:60]!r}")
    inner = raw[1:-1]
    if not inner:
        return []
    row = next(csv.reader(io.StringIO(inner), escapechar="\\"))
    # dict preserves order while dropping duplicates
    return list(dict.fromkeys(k for k in (s.strip().lower() for s in row) if k))


def load_faculty(path: Path = CSV_PATH) -> list[dict]:
    """Return one dict per CSV row (order kept; ids are assigned by the DB, not by email)."""
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        {
            "email": r["email"].strip().lower(),
            "name": r["name"].strip(),
            "photo_url": None if r["photo_url"] in ("", "NULL") else r["photo_url"],
            "position": r["position"].strip() or None,
            "keywords": parse_keywords(r["keywords"]),
        }
        for r in rows
    ]


if __name__ == "__main__":
    fac = load_faculty()
    kws = {k for f in fac for k in f["keywords"]}
    print(f"{len(fac)} faculty, {len(kws)} unique keywords, "
          f"{sum(f['photo_url'] is None for f in fac)} without photo, "
          f"{sum(f['position'] is None for f in fac)} without position")
