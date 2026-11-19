"""Link UIUC authorships to faculty (sets paper_authors.faculty_id / match_score).

Run: python -m ingestion.link_authors   (after load_db; safe to re-run)

An authorship (with or without an OpenAlex author id) is linked to a faculty member when
  1. it lists UIUC, or lists no institution at all (OpenAlex lost the affiliation). Authorships
     listing only other institutions are skipped: in the data they are mostly namesakes or
     colleagues who moved away (e.g. John A Rogers -> Northwestern),
  2. the normalized names are compatible (same last name; first names equal or common
     nicknames of each other, or one is an initial / a >=3-letter prefix of the other; middle
     initials do not conflict), and
  3. the paper's text shares enough faculty keywords: sum of IDF over the faculty keywords
     found in title+abstract+OpenAlex keywords+topics >= threshold (stricter when the first
     names are only loosely compatible or the authorship has no institution).
If several faculty pass for one authorship (e.g. the two Bo Li), the best is taken only
when it beats the runner-up by SCORE_MARGIN; otherwise the authorship stays unlinked.

Name-only link (match_method='name'), for UIUC authorships that passed no keyword test: the
first names are equal/nicknames, the faculty name is unique among the faculty (no second Bo Li)
and the last name is shared by fewer than COMMON_LAST_MIN faculty. The keywords of a faculty
member are a noisy summary of their work, so topic is not required here; in a hand-labeled sample
the topic gate rejected 41/41 true matches of this kind.

Semantic fallback (match_method='semantic'), for the UIUC authorships that passed neither test
(common last names such as Wang or Li): the faculty's keyword embeddings are compared with the
paper embedding (mean of the top-3 cosine similarities); the paper must rank in the top 3% of
all papers for that faculty (SEM_PERCENTILE). Only when the first names are equal/nicknames, the
faculty name is unique among the faculty and exactly one faculty passes.
"""

import collections
import math
import os
import re
import sys
import unicodedata

from dotenv import load_dotenv
from pgvector.psycopg import register_vector
import numpy as np
import psycopg

T_EXACT = 10.0  # idf-sum threshold when first names are equal
T_LOOSE = 20.0  # ... when only initial/prefix compatible
T_NO_INSTITUTION = 20.0  # ... for authorships without any institution (first names must be equal)
SCORE_MARGIN = 1.5
COMMON_LAST_MIN = 4  # a last name shared by this many faculty is too common to link on name alone
SEM_PERCENTILE = 0.97
SEM_TOP_K = 3
MAX_NGRAM = 6

NICKNAMES = [
    "alex alexander",
    "andy andrew",
    "ben benjamin",
    "bill billy will william",
    "bob bobby rob robert",
    "chris christopher",
    "dan danny daniel",
    "dave david",
    "ed eddie edward",
    "greg gregory",
    "jeff jeffrey",
    "jim jimmy james",
    "joe joseph",
    "kate katie kathy kathleen katherine catherine",
    "matt matthew",
    "mike michael",
    "nick nicholas",
    "pat patrick",
    "rick rich richard",
    "sam samuel",
    "steve steven stephen",
    "tim timothy",
    "tom thomas",
    "tony anthony",
]
NICKNAME_GROUP = {n: i for i, g in enumerate(NICKNAMES) for n in g.split()}

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")


def name_tokens(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", name.translate(_DASHES))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("-", " ").replace(".", " ")
    return re.sub(r"[^a-z ]", "", s).split()


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def name_match(f: list[str], a: list[str]) -> str | None:
    """'exact' (equal or nickname) | 'loose' | None for faculty tokens f vs authorship tokens a (both len >= 2)."""
    if f[-1] != a[-1]:
        return None
    if any(x[0] != y[0] for x, y in zip(f[1:-1], a[1:-1])):
        return None
    x, y = f[0], a[0]
    if x == y or (x in NICKNAME_GROUP and NICKNAME_GROUP.get(y) == NICKNAME_GROUP[x]):
        return "exact"
    if len(x) == 1 or len(y) == 1:
        return "loose" if x[0] == y[0] else None
    short = min(x, y, key=len)
    return "loose" if len(short) >= 3 and (x.startswith(y) or y.startswith(x)) else None


def paper_grams(text: str, vocab: set[str]) -> set[str]:
    w = words(text)
    return {
        g
        for n in range(1, MAX_NGRAM + 1)
        for i in range(len(w) - n + 1)
        if (g := " ".join(w[i : i + n])) in vocab
    }


def unique_names(faculty: list[tuple]) -> set[int]:
    """Faculty ids whose name is not compatible with any other faculty member's name."""
    toks = {fid: name_tokens(name) for fid, name, _ in faculty}
    by_last = collections.defaultdict(list)
    for fid, t in toks.items():
        if len(t) >= 2:
            by_last[t[-1]].append(fid)
    return {
        fid
        for fid, t in toks.items()
        if len(t) >= 2
        and not any(o != fid and name_match(toks[o], t) for o in by_last[t[-1]])
    }


class SemanticScorer:
    """Percentile of a paper among all papers by similarity to a faculty member's keywords."""

    def __init__(self, cur: psycopg.Cursor) -> None:
        cur.execute("SELECT id, embedding FROM papers ORDER BY id")
        rows = cur.fetchall()
        self.index = {pid: i for i, (pid, _) in enumerate(rows)}
        self.papers = np.vstack([e.to_numpy() for _, e in rows]).astype(np.float32)
        cur.execute(
            "SELECT fk.faculty_id, k.embedding FROM faculty_keywords fk JOIN keywords k ON k.id = fk.keyword_id"
        )
        kws = collections.defaultdict(list)
        for fid, e in cur.fetchall():
            kws[fid].append(e.to_numpy())
        self.kws = {fid: np.vstack(v).astype(np.float32) for fid, v in kws.items()}
        self.cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def percentile(self, fid: int, pid: str) -> float:
        if fid not in self.kws:
            return 0.0
        if fid not in self.cache:
            sims = self.papers @ self.kws[fid].T
            k = min(SEM_TOP_K, sims.shape[1])
            top = np.partition(sims, -k, axis=1)[:, -k:].mean(axis=1)
            self.cache[fid] = (top, np.sort(top))
        top, srt = self.cache[fid]
        return float(np.searchsorted(srt, top[self.index[pid]], side="right") / len(srt))


def main() -> None:
    load_dotenv()
    url = os.environ.get("DATABASE_URL") or sys.exit("DATABASE_URL missing")
    with psycopg.connect(url) as conn:
        register_vector(conn)  # before the cursor exists, so it picks up the adapter
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
        cur.execute(
            "SELECT paper_id, position, name, is_uiuc FROM paper_authors WHERE is_uiuc OR NOT has_institution"
        )
        authorships = cur.fetchall()

        # keyword vocabulary in the same tokenization as paper text
        fac_kws: dict[int, set[str]] = {}
        for fid, _, kws in faculty:
            fac_kws[fid] = {" ".join(words(k)) for k in kws} - {""}
        vocab = set().union(*fac_kws.values())
        grams = {pid: paper_grams(t, vocab) for pid, t in texts.items()}
        df = collections.Counter(g for s in grams.values() for g in s)
        n_papers = len(grams)

        by_last = collections.defaultdict(list)
        for fid, name, _ in faculty:
            t = name_tokens(name)
            if len(t) >= 2:
                by_last[t[-1]].append((fid, t))
        unique = unique_names(faculty)

        links: list[tuple[int, float, str, str, int]] = []  # faculty, score, method, paper, position
        semantic_pending: list[tuple[str, int, list[int]]] = []
        ambiguous = 0
        for pid, pos, name, is_uiuc in authorships:
            a = name_tokens(name)
            if len(a) < 2:
                continue
            passing = []  # (score, faculty_id)
            exact_unique = []  # (score, faculty_id)
            for fid, ft in by_last.get(a[-1], ()):
                tier = name_match(ft, a)
                if tier is None or (not is_uiuc and tier != "exact"):
                    continue
                score = sum(math.log(n_papers / df[g]) for g in fac_kws[fid] & grams[pid])
                if is_uiuc and tier == "exact" and fid in unique:
                    exact_unique.append((score, fid))
                if not is_uiuc:
                    need = T_NO_INSTITUTION
                else:
                    need = T_EXACT if tier == "exact" else T_LOOSE
                if score >= need:
                    passing.append((score, fid))
            if not passing:
                if len(exact_unique) == 1 and len(by_last[a[-1]]) < COMMON_LAST_MIN:
                    links.append((exact_unique[0][1], exact_unique[0][0], "name", pid, pos))
                elif exact_unique:
                    semantic_pending.append((pid, pos, [fid for _, fid in exact_unique]))
                continue
            passing.sort(reverse=True)
            if len(passing) > 1 and passing[0][0] < SCORE_MARGIN * passing[1][0]:
                ambiguous += 1
                continue
            links.append((passing[0][1], passing[0][0], "keywords", pid, pos))

        scorer = SemanticScorer(cur)
        for pid, pos, fids in semantic_pending:
            passing = [(pct, fid) for fid in fids if (pct := scorer.percentile(fid, pid)) >= SEM_PERCENTILE]
            if len(passing) == 1:
                links.append((passing[0][1], passing[0][0], "semantic", pid, pos))
            elif passing:
                ambiguous += 1

        cur.execute("UPDATE paper_authors SET faculty_id = NULL, match_score = NULL, match_method = NULL")
        cur.executemany(
            """UPDATE paper_authors SET faculty_id = %s, match_score = %s, match_method = %s
               WHERE paper_id = %s AND position = %s""",
            links,
        )

    by_method = collections.Counter(method for _, _, method, _, _ in links)
    linked_fac = len({fid for fid, *_ in links})
    keyword_fac = len({fid for fid, _, method, _, _ in links if method == "keywords"})
    print(
        f"{len(authorships)} candidate authorships: {len(links)} linked ("
        + ", ".join(f"{n} by {method}" for method, n in sorted(by_method.items()))
        + f") to {linked_fac}/{len(faculty)} faculty ({linked_fac - keyword_fac} not reached by keywords), "
        f"{ambiguous} skipped as ambiguous"
    )


if __name__ == "__main__":
    main()
