"""Stratified gold sample and threshold sweep for faculty linking.

Strata are listed in STRATA below. Scores and match methods are not
written to the blinded sample: the labeler only sees names, title, keywords, abstract,
authors, and institutions.
"""

from dataclasses import dataclass
import collections
import json
import math
import os
import random
import sys

from dotenv import load_dotenv
from pgvector.psycopg import register_vector
import psycopg

from ingestion.link_authors import (
    COMMON_LAST_MIN,
    SCORE_MARGIN,
    SEM_PERCENTILE,
    T_EXACT,
    T_LOOSE,
    T_NO_INSTITUTION,
    SemanticScorer,
    name_match,
    name_tokens,
    paper_grams,
    unique_names,
    words,
)

from .io import HOLDOUT

# The common-name challenge: last names shared by COMMON_LAST_MIN faculty (Wang, Zhang, Chen, Li, ...)
# plus exact full-name collisions (the two Bo Li, the two Yi Lu).
KEYWORD_SAMPLE = 24
STRATA = (
    ("common_name", 30),
    ("no_institution", 30),
    ("loose_name", 40),
    ("name_unique", 40),
    ("semantic", 60),
    ("keywords_borderline", 60),
    ("keywords_high", 40),
    ("rejected", 80),
)


def stratum_of_linked(*, common: bool, has_institution: bool, tier: str | None, method: str, score: float) -> str | None:
    """Disjoint bucket for one linked authorship. None if the link fits no planned stratum."""
    if common:
        return "common_name"
    if not has_institution:
        return "no_institution"
    if tier == "loose":
        return "loose_name"
    if method == "name":
        return "name_unique"
    if method == "semantic":
        return "semantic"
    if method == "keywords" and T_EXACT <= score < T_LOOSE:
        return "keywords_borderline"
    if method == "keywords" and score >= T_LOOSE:
        return "keywords_high"
    return None


def keyword_sample(keywords: list[str], n: int = KEYWORD_SAMPLE) -> list[str]:
    """Evenly spaced keywords, so the sample is stable and not chosen to favor the link."""
    ordered = sorted(set(keywords))
    if len(ordered) <= n:
        return ordered
    indexes = [round(i * (len(ordered) - 1) / (n - 1)) for i in range(n)]
    return [ordered[i] for i in indexes]


@dataclass(frozen=True)
class Candidate:
    faculty_id: int
    tier: str
    score: float
    exact_unique: bool
    percentile: float | None
    name_only: bool = False  # exact_unique and a last name too rare to be a common-name risk


def decide(candidates: list[Candidate], t_exact: float, t_loose: float, t_none: float, margin: float, sem_percentile: float, is_uiuc: bool) -> int | None:
    """Same accept/reject rule as ingestion.link_authors, for one authorship."""
    passing = []
    for cand in candidates:
        if not is_uiuc and cand.tier != "exact":
            continue
        need = t_none if not is_uiuc else (t_exact if cand.tier == "exact" else t_loose)
        if cand.score >= need:
            passing.append((cand.score, cand.faculty_id))
    if passing:
        passing.sort(reverse=True)
        if len(passing) > 1 and passing[0][0] < margin * passing[1][0]:
            return None
        return passing[0][1]
    named = [cand.faculty_id for cand in candidates if is_uiuc and cand.name_only]
    if len(named) == 1:
        return named[0]
    semantic = [
        (cand.percentile, cand.faculty_id)
        for cand in candidates
        if is_uiuc and cand.exact_unique and cand.percentile is not None and cand.percentile >= sem_percentile
    ]
    if len(semantic) == 1:
        return semantic[0][1]
    return None


def _faculty_index(conn: psycopg.Connection) -> dict[int, dict]:
    rows = conn.execute(
        """SELECT f.id, f.name, f.position,
                  coalesce(array_agg(k.text ORDER BY k.text) FILTER (WHERE k.text IS NOT NULL), '{}') AS keywords
           FROM faculty f
           LEFT JOIN faculty_keywords fk ON fk.faculty_id = f.id
           LEFT JOIN keywords k ON k.id = fk.keyword_id
           GROUP BY f.id"""
    ).fetchall()
    tokens = {}
    for row in rows:
        tokens[row["id"]] = name_tokens(row["name"])
    last_counts = collections.Counter(t[-1] for t in tokens.values() if len(t) >= 2)
    name_counts = collections.Counter(" ".join(t) for t in tokens.values() if len(t) >= 2)
    by_last = collections.defaultdict(list)
    faculty = {}
    for row in rows:
        toks = tokens[row["id"]]
        common = len(toks) >= 2 and (last_counts[toks[-1]] >= COMMON_LAST_MIN or name_counts[" ".join(toks)] >= 2)
        faculty[row["id"]] = {
            "name": row["name"],
            "position": row["position"],
            "keywords": keyword_sample(list(row["keywords"])),
            "tokens": toks,
            "common": common,
        }
        if len(toks) >= 2:
            by_last[toks[-1]].append((row["id"], toks))
    faculty["by_last"] = by_last
    return faculty


def sample_pairs(conn: psycopg.Connection, rng: random.Random) -> list[dict]:
    """Draw the fixed gold pairs. The returned dicts include stratum; callers strip it for labeling."""
    faculty = _faculty_index(conn)
    by_last = faculty.pop("by_last")
    authorships = conn.execute(
        """SELECT pa.paper_id, pa.position, pa.name, pa.is_uiuc, pa.has_institution,
                  pa.faculty_id, pa.match_method, pa.match_score, p.title, p.abstract
           FROM paper_authors pa JOIN papers p ON p.id = pa.paper_id
           WHERE pa.is_uiuc OR NOT pa.has_institution"""
    ).fetchall()

    buckets = collections.defaultdict(list)

    def pair(row: dict, faculty_id: int) -> dict:
        fac = faculty[faculty_id]
        return {
            "paper_id": row["paper_id"],
            "position": row["position"],
            "faculty_id": faculty_id,
            "faculty_name": fac["name"],
            "faculty_position": fac["position"],
            "faculty_keywords": fac["keywords"],
            "authorship_name": row["name"],
            "title": row["title"],
            "abstract": row["abstract"],
            "is_uiuc": row["is_uiuc"],
        }

    for row in authorships:
        author = name_tokens(row["name"])
        if len(author) < 2:
            continue
        matches = []
        for faculty_id, fac_tokens in by_last.get(author[-1], ()):
            tier = name_match(fac_tokens, author)
            if tier is None or (not row["is_uiuc"] and tier != "exact"):
                continue
            matches.append((faculty_id, tier))
        linked = row["faculty_id"]
        if linked is not None:
            tier = next((item for fid, item in matches if fid == linked), None)
            stratum = stratum_of_linked(
                common=faculty[linked]["common"],
                has_institution=row["has_institution"],
                tier=tier,
                method=row["match_method"],
                score=row["match_score"] or 0.0,
            )
            if stratum:
                buckets[stratum].append(pair(row, linked))
        for faculty_id, _tier in matches:
            if faculty_id != linked:
                buckets["rejected"].append(pair(row, faculty_id))

    picked = []
    for name, n in STRATA:
        pool = buckets[name]
        if len(pool) < n:
            sys.exit(f"{name}: need {n} pairs, pool has {len(pool)}")
        chosen = rng.sample(pool, n)
        rng.shuffle(chosen)
        n_test = round(n * HOLDOUT)
        for i, row in enumerate(chosen):
            row["stratum"] = name
            row["split"] = "test" if i < n_test else "tune"
        picked.extend(chosen)
        print(f"{name}: sampled {n} from {len(pool)} ({n_test} test)")
    rng.shuffle(picked)
    for i, row in enumerate(picked, start=1):
        row["id"] = f"L{i:04d}"
    return picked


def attach_authors(pairs: list[dict], works_dir) -> None:
    """Add institutions and the author list from the OpenAlex cache. Abstracts stay as stored in the DB."""
    from ingestion.load_db import authorship_name

    wanted = {row["paper_id"] for row in pairs}
    found = {}
    for page in sorted(works_dir.glob("page_*.json")):
        for work in json.loads(page.read_text())["results"]:
            wid = work["id"].rsplit("/", 1)[-1]
            if wid not in wanted:
                continue
            authors = []
            for auth in work["authorships"]:
                institutions = [inst.get("display_name") for inst in auth.get("institutions") or [] if inst.get("display_name")]
                if not institutions:
                    institutions = [raw for raw in auth.get("raw_affiliation_strings") or [] if raw]
                authors.append({"name": authorship_name(auth), "institutions": institutions})
            found[wid] = authors
        if len(found) == len(wanted):
            break
    missing = wanted - found.keys()
    if missing:
        sys.exit(f"{len(missing)} sampled papers are missing from the OpenAlex cache")

    mismatches = 0
    for row in pairs:
        authors = found[row["paper_id"]]
        if row["position"] >= len(authors):
            sys.exit(f"{row['paper_id']} position {row['position']} is past the cached author list")
        cached = authors[row["position"]]
        if name_tokens(cached["name"]) != name_tokens(row["authorship_name"]):
            mismatches += 1
        row["authorship_institutions"] = cached["institutions"]
        row["author_count"] = len(authors)
        shown = authors[:12]
        if row["position"] >= 12:
            shown = shown + [authors[row["position"]]]
        row["authors"] = [{"name": a["name"], "institutions": a["institutions"]} for a in shown]
    if mismatches:
        print(f"warning: {mismatches} cached author names differ from the DB at the same position", file=sys.stderr)


def blind_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "faculty_name": row["faculty_name"],
        "faculty_position": row["faculty_position"],
        "faculty_keywords": row["faculty_keywords"],
        "authorship_name": row["authorship_name"],
        "authorship_institutions": row["authorship_institutions"],
        "title": row["title"],
        "abstract": row["abstract"],
        "author_count": row["author_count"],
        "authors": row["authors"],
    }


def key_view(row: dict) -> dict:
    return {
        "id": row["id"],
        "stratum": row["stratum"],
        "split": row["split"],
        "paper_id": row["paper_id"],
        "position": row["position"],
        "faculty_id": row["faculty_id"],
    }


def gold_view(row: dict, label: str, note: str | None) -> dict:
    item = {**key_view(row), **blind_view(row), "label": label}
    if note:
        item["note"] = note
    return item


def format_case(row: dict, abstract_chars: int = 500) -> str:
    keywords = "; ".join(row["faculty_keywords"])
    institutions = "; ".join(row["authorship_institutions"]) or "(no institution listed)"
    authors = " | ".join(
        f"{a['name']} [{'; '.join(a['institutions'])}]" if a["institutions"] else a["name"] for a in row["authors"]
    )
    return (
        f"{row['id']}\n"
        f"Faculty: {row['faculty_name']} — {row['faculty_position'] or '(no title)'}\n"
        f"Keywords: {keywords}\n"
        f"Authorship: {row['authorship_name']} — {institutions}\n"
        f"Title: {row['title']}\n"
        f"Authors ({row['author_count']}): {authors}\n"
        f"Abstract: {row['abstract'][:abstract_chars]}\n"
    )


def current_links(conn: psycopg.Connection) -> dict[tuple[str, int], int]:
    rows = conn.execute("SELECT paper_id, position, faculty_id FROM paper_authors WHERE faculty_id IS NOT NULL").fetchall()
    return {(row["paper_id"], row["position"]): row["faculty_id"] for row in rows}


def agreement(rows: list[dict], links: dict[tuple[str, int], int], split: str | None = None) -> dict:
    """Precision of affirmed pairs, and recall of `same` labels inside the originally linked strata."""
    chosen = [row for row in rows if split is None or row["split"] == split]
    per_stratum = {}
    affirmed_same = affirmed_n = 0
    linked_same_hit = linked_same_n = 0
    rejected_same = rejected_same_hit = rejected_n = 0
    for row in chosen:
        judged = row["label"] in ("same", "different")
        predicted = links.get((row["paper_id"], row["position"])) == row["faculty_id"]
        if row["stratum"] == "rejected":
            if not judged:
                continue
            rejected_n += 1
            if row["label"] == "same":
                rejected_same += 1
                rejected_same_hit += predicted
            continue
        if not judged:
            continue
        if row["label"] == "same":
            linked_same_n += 1
            linked_same_hit += predicted
        bucket = per_stratum.setdefault(row["stratum"], {"same": 0, "n": 0})
        if predicted:
            bucket["n"] += 1
            affirmed_n += 1
            if row["label"] == "same":
                bucket["same"] += 1
                affirmed_same += 1
    return {
        "precision": (affirmed_same, affirmed_n),
        "recall_linked": (linked_same_hit, linked_same_n),
        "rejected_same": (rejected_same, rejected_n),
        "rejected_recovery": (rejected_same_hit, rejected_same),
        "by_stratum": per_stratum,
    }


def _keyword_model(conn: psycopg.Connection):
    """IDF tables for a threshold sweep. Mirrors ingestion.link_authors without writing links."""
    cur = conn.cursor()
    cur.execute(
        """SELECT f.id, f.name, coalesce(array_agg(k.text) FILTER (WHERE k.text IS NOT NULL), '{}')
           FROM faculty f
           LEFT JOIN faculty_keywords fk ON fk.faculty_id = f.id
           LEFT JOIN keywords k ON k.id = fk.keyword_id GROUP BY f.id"""
    )
    faculty = cur.fetchall()
    cur.execute(
        """SELECT p.id, p.title || ' ' || p.abstract || ' ' || array_to_string(p.keywords, ' ') || ' '
                  || coalesce((SELECT string_agg(t.name, ' ') FROM paper_topics pt
                               JOIN topics t ON t.id = pt.topic_id WHERE pt.paper_id = p.id), '')
           FROM papers p"""
    )
    texts = dict(cur.fetchall())
    fac_kws = {}
    for fid, _name, kws in faculty:
        fac_kws[fid] = {" ".join(words(k)) for k in kws} - {""}
    vocab = set().union(*fac_kws.values())
    grams = {pid: paper_grams(text, vocab) for pid, text in texts.items()}
    df = collections.Counter(gram for grams_of_paper in grams.values() for gram in grams_of_paper)
    n_papers = len(grams)
    idf = {gram: math.log(n_papers / count) for gram, count in df.items()}
    by_last = collections.defaultdict(list)
    for fid, name, _kws in faculty:
        tokens = name_tokens(name)
        if len(tokens) >= 2:
            by_last[tokens[-1]].append((fid, tokens))
    return {
        "faculty": faculty,
        "fac_kws": fac_kws,
        "grams": grams,
        "idf": idf,
        "by_last": by_last,
        "unique": unique_names(faculty),
    }


def candidates_for(model: dict, authorships: list[tuple], scorer: SemanticScorer | None) -> dict[tuple[str, int], list[Candidate]]:
    """Keyword score every name-matching faculty of the given authorships. Semantic percentile is filled when asked."""
    out = {}
    for paper_id, position, name, is_uiuc in authorships:
        author = name_tokens(name)
        if len(author) < 2 or paper_id not in model["grams"]:
            continue
        cands = []
        for faculty_id, fac_tokens in model["by_last"].get(author[-1], ()):
            tier = name_match(fac_tokens, author)
            if tier is None or (not is_uiuc and tier != "exact"):
                continue
            score = sum(model["idf"][gram] for gram in model["fac_kws"][faculty_id] & model["grams"][paper_id])
            exact_unique = bool(is_uiuc and tier == "exact" and faculty_id in model["unique"])
            name_only = exact_unique and len(model["by_last"][author[-1]]) < COMMON_LAST_MIN
            percentile = scorer.percentile(faculty_id, paper_id) if scorer is not None and exact_unique else None
            cands.append(Candidate(faculty_id, tier, score, exact_unique, percentile, name_only))
        out[(paper_id, position)] = cands
    return out


def _needs_semantic(cands: list[Candidate], is_uiuc: bool) -> bool:
    """True when some grid point would fall through to the semantic rule. The grid's strictest bars are 15 / 30."""
    for cand in cands:
        need = 30 if (not is_uiuc or cand.tier != "exact") else 15
        if cand.score >= need:
            return False
    return any(cand.exact_unique and not cand.name_only for cand in cands)


def sweep(gold: list[dict]) -> dict:
    """Pick a threshold on the tune split, then report that setting on the untouched test split."""
    load_dotenv()
    url = os.environ.get("DATABASE_URL") or sys.exit("DATABASE_URL missing")
    with psycopg.connect(url, autocommit=True) as conn:
        register_vector(conn)
        print("sweep: loading keyword model")
        model = _keyword_model(conn)
        keys = {(row["paper_id"], row["position"]) for row in gold}
        cur = conn.cursor()
        cur.execute(
            """SELECT paper_id, position, name, is_uiuc FROM paper_authors
               WHERE is_uiuc OR NOT has_institution"""
        )
        authorships = [row for row in cur.fetchall() if (row[0], row[1]) in keys]
        scored = candidates_for(model, authorships, None)
        is_uiuc = {(row[0], row[1]): row[3] for row in authorships}
        semantic_keys = [key for key, cands in scored.items() if _needs_semantic(cands, is_uiuc[key])]
        print(f"sweep: semantic percentiles for {len(semantic_keys)} authorships")
        if semantic_keys:
            scorer = SemanticScorer(cur)
            for index, key in enumerate(semantic_keys, start=1):
                scored[key] = [
                    Candidate(
                        c.faculty_id, c.tier, c.score, c.exact_unique,
                        scorer.percentile(c.faculty_id, key[0]) if c.exact_unique else None, c.name_only,
                    )
                    for c in scored[key]
                ]
                if index % 25 == 0:
                    print(f"sweep: {index}/{len(semantic_keys)}", end="\r", flush=True)
            print()
        db_links = {
            (row[0], row[1]): row[2]
            for row in conn.execute(
                "SELECT paper_id, position, faculty_id FROM paper_authors WHERE faculty_id IS NOT NULL"
            ).fetchall()
        }
        resim = {
            key: decide(cands, T_EXACT, T_LOOSE, T_NO_INSTITUTION, SCORE_MARGIN, SEM_PERCENTILE, is_uiuc[key])
            for key, cands in scored.items()
        }
        mismatches = [key for key in keys if resim.get(key) != db_links.get(key)]
        print(f"sweep: default thresholds disagree with the DB on {len(mismatches)} gold authorships")

    grid = []
    for t_exact in (8, 10, 12, 15):
        for t_loose in (15, 20, 25, 30):
            for margin in (1.2, 1.5, 2.0):
                for sem in (0.95, 0.97, 0.99):
                    grid.append((t_exact, t_loose, t_loose, margin, sem))

    def evaluate(params, split):
        t_exact, t_loose, t_none, margin, sem = params
        links = {
            key: decide(cands, t_exact, t_loose, t_none, margin, sem, is_uiuc[key])
            for key, cands in scored.items()
        }
        # agreement() expects the gold faculty to be the value, so map authorship -> predicted faculty
        return agreement(gold, {key: fid for key, fid in links.items() if fid is not None}, split)

    def ratio(pair):
        hit, n = pair
        return hit / n if n else 0.0

    def semantic(report):
        bucket = report["by_stratum"].get("semantic", {"same": 0, "n": 0})
        return bucket["same"] / bucket["n"] if bucket["n"] else 0.0

    best = None
    for params in grid:
        report = evaluate(params, "tune")
        # Meet the proposed bars, then recover true misses. Ties keep the stricter thresholds.
        t_exact, t_loose, _t_none, margin, sem = params
        key = (
            ratio(report["precision"]) >= 0.95 and semantic(report) >= 0.85,
            ratio(report["rejected_recovery"]),
            ratio(report["precision"]),
            t_exact,
            t_loose,
            margin,
            sem,
        )
        if best is None or key > best[0]:
            best = (key, params, report)
    assert best is not None
    _key, params, tune = best
    test = evaluate(params, "test")
    return {
        "params": params,
        "tune_precision": ratio(tune["precision"]),
        "tune_recall": ratio(tune["recall_linked"]),
        "tune_recovery": ratio(tune["rejected_recovery"]),
        "test_precision": ratio(test["precision"]),
        "test_recall": ratio(test["recall_linked"]),
        "test_recovery": ratio(test["rejected_recovery"]),
        "test_semantic": semantic(test),
        "mismatches": len(mismatches),
    }
