"""End-to-end checks of the chat agent against the live LLM server.

    python -m eval.chat            # run, print metrics, compare to eval/gold/chat_baseline.json
    python -m eval.chat --save

Needs the vLLM chat server, the embedding server and the database. Temperature 0. Every answer is written to
eval/work/chat_run.jsonl for reading: the metrics below only catch what can be checked mechanically.
"""

import argparse
import asyncio
import json
import re
import statistics
import sys

from dotenv import load_dotenv
import httpx

from backend.agent.agent import REF, run_chat
from backend.agent.trace import Trace
from backend.app.db import make_pool

from .io import GOLD, WORK, connect, load_jsonl
from .run import compare

BASELINE = GOLD / "chat_baseline.json"
CONCURRENCY = 4

OUT_OF_DOMAIN = [
    "best pizza restaurants in Chicago",
    "Taylor Swift concert tour ticket prices",
    "how to change a flat car tire",
    "competitive speedcubing world records",
    "Who is the president of France?",
    "Write me a poem about autumn",
    "recipe for chocolate chip cookies",
    "Who won the world cup in 2022?",
    "What is on the menu at the Illini Union today?",
    "Which UIUC faculty study Renaissance lute tablature?",
]
FOLLOWUP = "What has the second person you listed published recently?"
# With a profile open, a question about something else must still be refused.
CONTEXT_OOD = ["best pizza restaurants in Chicago", "Who won the world cup in 2022?"]
TASK_QUESTIONS = [
    "What are the most recent UIUC papers on AI in war conflict?",
    "Which faculty members work on Computer Vision in Healthcare?",
]


def build_cases(conn) -> list[dict]:
    _meta, queries = load_jsonl(GOLD / "queries.jsonl")
    topics = [q for q in queries if q["kind"] == "topic"][:10]
    cases = []
    for q in topics:
        cases.append({"kind": "topic_papers", "message": f"Which UIUC papers are about {q['text']}?", "topic_id": q["topic_id"]})
        cases.append({"kind": "topic_faculty", "message": f"Which UIUC faculty members work on {q['text']}?", "topic_id": q["topic_id"]})
    rows = conn.execute(
        """SELECT f.id, f.name, count(DISTINCT pa.paper_id) AS n FROM faculty f JOIN paper_authors pa ON pa.faculty_id = f.id
           WHERE (SELECT count(*) FROM faculty g WHERE lower(g.name) = lower(f.name)) = 1
           GROUP BY f.id ORDER BY n DESC, f.id OFFSET 10 LIMIT 5"""
    ).fetchall()
    for row in rows:
        cases.append({"kind": "name", "message": f"What are the latest papers by {row['name']}?", "faculty_id": row["id"]})
    open_profiles = conn.execute(
        """SELECT f.id FROM faculty f JOIN paper_authors pa ON pa.faculty_id = f.id
           WHERE (SELECT count(*) FROM faculty g WHERE lower(g.name) = lower(f.name)) = 1
           GROUP BY f.id ORDER BY count(DISTINCT pa.paper_id) DESC, f.id OFFSET 20 LIMIT 4"""
    ).fetchall()
    for row in open_profiles:
        context = {"kind": "faculty", "id": row["id"]}
        cases.append({"kind": "context", "message": "What are the latest papers by this person?", "faculty_id": row["id"], "context": context})
    for text, row in zip(CONTEXT_OOD, open_profiles):
        cases.append({"kind": "context_ood", "message": text, "context": {"kind": "faculty", "id": row["id"]}})
    for q in topics[:4]:
        cases.append({"kind": "followup", "message": f"Which UIUC faculty members work on {q['text']}?", "followup": FOLLOWUP})
    cases += [{"kind": "ood", "message": text} for text in OUT_OF_DOMAIN]
    cases += [{"kind": "task", "message": text} for text in TASK_QUESTIONS]
    return cases


async def run_turn(pool, client, message: str, history=(), context=None, known=()) -> dict:
    text, sources, cited, error, tools = "", {}, [], None, []
    trace = Trace()
    events = run_chat(pool, client, message, list(history), temperature=0.0, context=context, known=list(known), trace=trace)
    async for event in events:
        kind = event["type"]
        if kind == "delta":
            text += event["text"]
        elif kind == "reset":
            text = ""
        elif kind == "sources":
            sources.update({s["ref"]: s for s in event["sources"]})
        elif kind == "status":
            tools.append(event["tool"])
        elif kind == "done":
            cited = event["cited"]
        elif kind == "error":
            error = event["message"]
    used = list(dict.fromkeys(REF.findall(text)))
    return {
        "answer": text,
        "tools": tools,
        "cited": cited,
        "unknown_refs": [r for r in used if r not in sources],
        "error": error,
        "sources": sources,
        "rounds": trace.attrs["rounds"],
        "ms": trace.ms(),
    }


async def run_case(pool, client, case: dict) -> dict:
    if case["kind"] != "followup":
        return {**case, **await run_turn(pool, client, case["message"], context=case.get("context"))}
    first = await run_turn(pool, client, case["message"])
    people = [first["sources"][ref]["facultyId"] for ref in first["cited"] if first["sources"][ref]["kind"] == "faculty"]
    history = [{"role": "user", "content": case["message"]}, {"role": "assistant", "content": re.sub(r"\s*\[[PF]\d+\]", "", first["answer"])}]
    known = [
        {"kind": s["kind"], "id": str(s["facultyId"] if s["kind"] == "faculty" else s["paperId"])}
        for ref, s in first["sources"].items()
        if ref in first["cited"]
    ]
    second = await run_turn(pool, client, case["followup"], history, known=known)
    return {**case, **second, "target": people[1] if len(people) > 1 else None, "first_error": first["error"]}


def score(cases: list[dict], conn) -> dict[str, float | None]:
    def ratio(hit: int, n: int) -> float | None:
        return hit / n if n else None

    paper_hit = paper_n = faculty_hit = faculty_n = 0
    answered = {"topic_papers": [0, 0], "topic_faculty": [0, 0]}
    name_hit = name_n = ood_ok = ood_n = 0
    context_hit = context_n = context_ood_ok = context_ood_n = follow_hit = follow_n = 0
    follow_tools: list[int] = []
    for case in cases:
        if case["kind"] == "topic_papers":
            ids = _cited(case, "paper", "paperId")
            paper_n += len(ids)
            paper_hit += sum(
                conn.execute("SELECT 1 FROM paper_topics WHERE paper_id = %s AND topic_id = %s", (pid, case["topic_id"])).fetchone() is not None
                for pid in ids
            )
            answered["topic_papers"][1] += 1
            answered["topic_papers"][0] += bool(ids)
        elif case["kind"] == "topic_faculty":
            ids = _cited(case, "faculty", "facultyId")
            faculty_n += len(ids)
            faculty_hit += sum(
                conn.execute(
                    """SELECT 1 FROM paper_authors pa JOIN paper_topics pt ON pt.paper_id = pa.paper_id
                       WHERE pa.faculty_id = %s AND pt.topic_id = %s LIMIT 1""",
                    (fid, case["topic_id"]),
                ).fetchone()
                is not None
                for fid in ids
            )
            answered["topic_faculty"][1] += 1
            answered["topic_faculty"][0] += bool(ids)
        elif case["kind"] == "name":
            ids = _cited(case, "paper", "paperId")
            right = case["faculty_id"] in _cited(case, "faculty", "facultyId") and bool(ids) and all(
                conn.execute("SELECT 1 FROM paper_authors WHERE paper_id = %s AND faculty_id = %s", (pid, case["faculty_id"])).fetchone()
                for pid in ids
            )
            name_n += 1
            name_hit += right
        elif case["kind"] == "ood":
            ood_n += 1
            ood_ok += not case["cited"]
        elif case["kind"] == "context":
            context_n += 1
            context_hit += _all_by(conn, _cited(case, "paper", "paperId"), case["faculty_id"])
        elif case["kind"] == "context_ood":
            context_ood_n += 1
            context_ood_ok += not case["cited"]
        elif case["kind"] == "followup" and case["target"] is not None:
            follow_n += 1
            follow_hit += _all_by(conn, _cited(case, "paper", "paperId"), case["target"])
            follow_tools.append(len(case["tools"]))
    return {
        "chat.topic_papers.precision": ratio(paper_hit, paper_n),
        "chat.topic_papers.answered": ratio(*answered["topic_papers"]),
        "chat.topic_faculty.precision": ratio(faculty_hit, faculty_n),
        "chat.topic_faculty.answered": ratio(*answered["topic_faculty"]),
        "chat.name.correct": ratio(name_hit, name_n),
        "chat.ood.no_citation": ratio(ood_ok, ood_n),
        "chat.context.correct": ratio(context_hit, context_n),
        "chat.context.ood_no_citation": ratio(context_ood_ok, context_ood_n),
        "chat.followup.correct": ratio(follow_hit, follow_n),
        "info.followup.tool_calls_mean": statistics.fmean(follow_tools) if follow_tools else None,
        "info.followup.skipped": float(sum(c["kind"] == "followup" and c["target"] is None for c in cases)),
        "info.trace.rounds_mean": statistics.fmean(c["rounds"] for c in cases),
        "info.trace.ms_p50": statistics.median(c["ms"] for c in cases),
        "info.trace.ms_p95": statistics.quantiles([c["ms"] for c in cases], n=20)[-1],
        "chat.integrity.unknown_refs": float(sum(len(c["unknown_refs"]) for c in cases)),
        "chat.integrity.errors": float(sum(c["error"] is not None for c in cases)),
        "info.cited_papers": float(paper_n),
        "info.cited_faculty": float(faculty_n),
    }


def _all_by(conn, paper_ids: list, faculty_id: int) -> bool:
    """Papers were cited and every one has this faculty member among its linked authors."""
    return bool(paper_ids) and all(
        conn.execute("SELECT 1 FROM paper_authors WHERE paper_id = %s AND faculty_id = %s", (pid, faculty_id)).fetchone()
        for pid in paper_ids
    )


def _cited(case: dict, kind: str, key: str) -> list:
    return [case["sources"][ref][key] for ref in case["cited"] if case["sources"][ref]["kind"] == kind]


async def run_all(cases: list[dict]) -> list[dict]:
    pool = make_pool()
    pool.open(wait=True)
    gate = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5, read=120)) as client:

        async def one(case: dict) -> dict:
            async with gate:
                return await run_case(pool, client, case)

        try:
            return await asyncio.gather(*(one(case) for case in cases))
        finally:
            pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    with connect() as conn:
        cases = build_cases(conn)
        results = asyncio.run(run_all(cases))
        metrics = score(results, conn)
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / "chat_run.jsonl").open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps({k: v for k, v in row.items() if k != "sources"}, ensure_ascii=False) + "\n")
    print(f"{'metric':<40} {'value':>8}")
    for key, value in metrics.items():
        print(f"{key:<40} {'n/a' if value is None else f'{value:8.3f}'}")
    print(f"answers written to {WORK / 'chat_run.jsonl'}")
    gated = {k: v for k, v in metrics.items() if k.startswith("chat.") and not k.startswith("chat.integrity") and v is not None}
    if args.save:
        BASELINE.write_text(json.dumps(gated, indent=2, sort_keys=True) + "\n")
        print(f"saved {BASELINE}")
        return
    if not BASELINE.exists():
        print("no baseline yet; rerun with --save")
        return
    failures = compare(metrics, json.loads(BASELINE.read_text()))
    # Integrity is not a ratio: any unknown ref or error is a failure.
    failures += [f"{key} is {metrics[key]:.0f}" for key in ("chat.integrity.unknown_refs", "chat.integrity.errors") if metrics[key]]
    if failures:
        print("below baseline:")
        for line in failures:
            print(f"  {line}")
        sys.exit(1)
    print("baseline: ok")


if __name__ == "__main__":
    main()
