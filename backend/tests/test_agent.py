"""Chat agent loop with a scripted LLM (no model needed), plus the search gate against the real database."""

from typing import Any
import asyncio
import json

import httpx
import pytest

from backend.agent.agent import run_chat
from backend.agent.search import search_papers
from backend.agent.tools import Citations, run_tool
from backend.agent.trace import Trace


def sse(*chunks: dict[str, Any]) -> httpx.Response:
    body = "".join(f"data: {json.dumps({'choices': [{'delta': c, 'finish_reason': None}]})}\n\n" for c in chunks)
    return httpx.Response(200, content=body + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})


def tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


def collect(
    pool,
    replies: list[httpx.Response | Exception],
    message: str = "question",
    *,
    history: list[dict[str, Any]] | None = None,
    seen: list[dict[str, Any]] | None = None,
    auths: list[str] | None = None,
    **options: Any,
) -> list[dict[str, Any]]:
    """Run the agent against scripted model replies. `seen` collects the request bodies the model received."""
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        if auths is not None:
            auths.append(request.headers.get("authorization", ""))
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def go() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return [event async for event in run_chat(pool, client, message, history or [], **options)]

    return asyncio.run(go())


@pytest.fixture(scope="module")
def busy_faculty(db) -> int:
    return db.execute(
        """SELECT faculty_id FROM paper_authors WHERE faculty_id IS NOT NULL
           GROUP BY faculty_id ORDER BY count(DISTINCT paper_id) DESC LIMIT 1"""
    ).fetchone()["faculty_id"]


def test_answer_cites_only_records_that_were_retrieved(pool, busy_faculty):
    events = collect(
        pool,
        [
            sse(tool_call("get_faculty_papers", {"faculty_id": busy_faculty, "limit": 2})),
            sse({"content": "Newest: [P1] "}, {"content": "and an invented one [P99] and [F1]."}),
        ],
    )
    kinds = [e["type"] for e in events]
    assert kinds[0] == "status" and kinds[1] == "sources" and kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Newest: [P1] and an invented one [P99] and [F1]."
    sources = {s["ref"]: s for s in events[1]["sources"]}
    assert sources["F1"]["facultyId"] == busy_faculty and sources["P1"]["kind"] == "paper"
    assert events[-1]["cited"] == ["P1", "F1"]  # P99 was never retrieved


def test_text_written_before_a_tool_call_is_dropped(pool, busy_faculty):
    events = collect(
        pool,
        [
            sse({"content": "Let me look. "}, tool_call("get_faculty_papers", {"faculty_id": busy_faculty, "limit": 1})),
            sse({"content": "Done [P1]."}),
        ],
    )
    kinds = [e["type"] for e in events]
    assert kinds == ["delta", "status", "sources", "reset", "delta", "done"]
    assert events[-1] == {"type": "done", "cited": ["P1"]}


def test_unreachable_model_ends_with_an_error_event(pool):
    events = collect(pool, [httpx.ConnectError("down")])
    assert [e["type"] for e in events] == ["error"]


def test_an_error_inside_the_model_stream_ends_with_an_error_event(pool):
    body = 'data: {"choices": [{"delta": {"content": "Hel"}}]}\n\ndata: {"error": {"message": "out of memory"}}\n\n'
    trace = Trace()
    events = collect(pool, [httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})], trace=trace)
    assert [e["type"] for e in events] == ["delta", "error"]
    assert trace.status == "error" and "out of memory" in trace.attrs["error"]


def test_an_unexpected_failure_still_ends_with_an_error_event(pool, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("pool exhausted")

    monkeypatch.setattr("backend.agent.agent.run_tool", broken)
    trace = Trace()
    events = collect(pool, [sse(tool_call("search_papers", {"query": "robotics"}))], trace=trace)
    assert events[-1]["type"] == "error" and events[-1]["message"].endswith(f"(trace {trace.id})")
    assert trace.status == "error" and "pool exhausted" in trace.attrs["error"]


def test_bad_tool_input_comes_back_to_the_model_as_an_error(pool):
    citations = Citations()
    assert "unknown tool" in run_tool(pool, "drop_tables", "{}", citations)
    assert "not valid JSON" in run_tool(pool, "search_papers", "{oops", citations)
    assert "faculty_id must be an integer" in run_tool(pool, "get_faculty_papers", '{"faculty_id": "x"}', citations)
    assert "no faculty member with id" in run_tool(pool, "get_faculty_papers", '{"faculty_id": 999999999}', citations)
    assert citations.sources == {}


def test_a_record_keeps_one_ref_across_tool_calls(pool, busy_faculty):
    citations = Citations()
    first = json.loads(run_tool(pool, "get_faculty_papers", json.dumps({"faculty_id": busy_faculty, "limit": 3}), citations))
    again = json.loads(run_tool(pool, "get_faculty_papers", json.dumps({"faculty_id": busy_faculty, "limit": 3}), citations))
    assert [r["ref"] for r in first["results"]] == [r["ref"] for r in again["results"]]
    assert len(citations.sources) == 1 + len(first["results"])


def test_search_returns_nothing_for_an_out_of_domain_query_and_something_for_a_topical_one(db):
    with_conn = lambda q, **kw: search_papers(db, q, **kw)
    assert with_conn("best pizza restaurants in Chicago") == []
    papers = with_conn("reinforcement learning for robotic manipulation", limit=5)
    assert 0 < len(papers) <= 5 and all(p["similarity"] >= 0.45 for p in papers)


def test_recent_sort_orders_the_on_topic_pool_by_date(db):
    papers = search_papers(db, "large language models", sort_by_date=True, limit=8)
    dates = [p["publication_date"] for p in papers]
    assert dates == sorted(dates, reverse=True) and len(papers) > 1


def test_recent_sort_keeps_the_best_match(db):
    # Newer, loosely related papers used to push the strongest hit out of a date-sorted list.
    query = "AI in war conflict"
    best = max(search_papers(db, query, limit=6), key=lambda p: p["similarity"])["id"]
    assert best in {p["id"] for p in search_papers(db, query, sort_by_date=True, limit=6)}


def person_named(db, faculty_id: int) -> dict[str, Any]:
    return db.execute("SELECT id, name FROM faculty WHERE id = %s", [faculty_id]).fetchone()


def a_paper(db) -> dict[str, Any]:
    return db.execute("SELECT id, title FROM papers ORDER BY id LIMIT 1").fetchone()


def system_prompt(seen: list[dict[str, Any]]) -> str:
    first = seen[0]["messages"]
    assert first[0]["role"] == "system" and sum(m["role"] == "system" for m in first) == 1
    return first[0]["content"]


def test_open_profile_is_named_in_the_prompt_and_citable(pool, db, busy_faculty):
    seen: list[dict[str, Any]] = []
    events = collect(
        pool,
        [sse({"content": "He wrote a lot [F1]."})],
        seen=seen,
        context={"kind": "faculty", "id": busy_faculty},
    )
    person = person_named(db, busy_faculty)
    prompt = system_prompt(seen)
    assert f"[F1] open: faculty_id={busy_faculty}, {person['name']}" in prompt
    assert events[0]["type"] == "sources" and events[0]["sources"][0]["facultyId"] == busy_faculty
    assert events[-1] == {"type": "done", "cited": ["F1"]}


def test_context_naming_a_missing_profile_is_ignored(pool):
    seen: list[dict[str, Any]] = []
    events = collect(pool, [sse({"content": "Hi."})], seen=seen, context={"kind": "faculty", "id": 999999999})
    assert "open: faculty_id=" not in system_prompt(seen)
    assert [e["type"] for e in events] == ["delta", "done"]


def test_earlier_records_are_listed_with_database_text_and_unknown_ids_are_dropped(pool, db, busy_faculty):
    paper, person = a_paper(db), person_named(db, busy_faculty)
    seen: list[dict[str, Any]] = []
    known = [
        {"kind": "faculty", "id": str(busy_faculty)},
        {"kind": "faculty", "id": "999999999"},
        {"kind": "faculty", "id": "not-a-number"},
        {"kind": "paper", "id": paper["id"]},
        {"kind": "paper", "id": "Wdoesnotexist"},
        {"kind": "faculty", "id": str(busy_faculty)},
    ]
    events = collect(pool, [sse({"content": "ok"})], seen=seen, known=known)
    prompt = system_prompt(seen)
    assert f"- [F1] faculty_id={busy_faculty} {person['name']}\n" in prompt
    assert f'- [P1] "{paper["title"]}"' in prompt
    assert prompt.count("[F1]") == 1 and "999999999" not in prompt and "Wdoesnotexist" not in prompt
    assert {s["ref"] for s in events[0]["sources"]} == {"F1", "P1"}


def test_a_trace_records_rounds_tools_and_spans_in_order(pool, busy_faculty):
    trace = Trace()
    collect(
        pool,
        [sse(tool_call("get_faculty_papers", {"faculty_id": busy_faculty, "limit": 1})), sse({"content": "Done [P1]."})],
        trace=trace,
    )
    names = [s["name"] for s in trace.spans]
    assert names == ["preload", "llm.round", "tool", "tool.result", "llm.round"]
    assert trace.status == "ok" and trace.attrs["rounds"] == 2 and trace.attrs["tool_calls"] == 1
    assert trace.attrs["cited"] == ["P1"] and trace.attrs["history_turns"] == 0
    assert trace.spans[1]["tool_calls"] == ["get_faculty_papers"] and trace.spans[3]["results"] == 1
    starts = [s["start_ms"] for s in trace.spans]
    assert starts == sorted(starts)
    assert trace.payload is None and "message" not in trace.attrs  # user text is only kept with TRACE_PAYLOADS=1


def test_payloads_are_kept_only_when_asked(pool, monkeypatch):
    monkeypatch.setenv("TRACE_PAYLOADS", "1")
    trace = Trace()
    collect(pool, [sse({"content": "Hello"})], message="what is up", trace=trace)
    assert trace.attrs["message"] == "what is up"
    assert [m["role"] for m in trace.payload] == ["system", "user", "assistant"]


def test_the_model_only_sees_the_last_eight_history_messages(pool):
    seen: list[dict[str, Any]] = []
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(12)]
    trace = Trace()
    collect(pool, [sse({"content": "ok"})], message="now", history=history, seen=seen, trace=trace)
    sent = [m["content"] for m in seen[0]["messages"] if m["role"] != "system"]
    assert sent == [f"m{i}" for i in range(4, 12)] + ["now"]
    assert trace.attrs["history_turns"] == 8


def test_a_failed_run_is_traced_as_an_error_and_tells_the_user_its_id(pool):
    trace = Trace()
    events = collect(pool, [httpx.ConnectError("down")], trace=trace)
    assert trace.status == "error" and "ConnectError" in trace.attrs["error"]
    assert events[-1]["message"].endswith(f"(trace {trace.id})")


def _use_gemini(monkeypatch: pytest.MonkeyPatch, key: str | None = "test-key") -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_REASONING", "low")
    if key is None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GEMINI_API_KEY", key)


def test_vllm_request_still_disables_thinking(pool, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "vllm")
    seen: list[dict[str, Any]] = []
    collect(pool, [sse({"content": "ok"})], seen=seen)
    assert seen[0]["model"] == "qwen3.8-27b"
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen[0]["max_tokens"] == 1500
    assert "reasoning_effort" not in seen[0]


def test_gemini_request_uses_the_api_key_and_skips_vllm_fields(pool, monkeypatch):
    _use_gemini(monkeypatch)
    seen: list[dict[str, Any]] = []
    auths: list[str] = []
    collect(pool, [sse({"content": "ok"})], seen=seen, auths=auths)
    assert auths == ["Bearer test-key"]
    assert seen[0]["model"] == "gemini-3.8-flash"
    assert seen[0]["reasoning_effort"] == "low"
    assert "chat_template_kwargs" not in seen[0]
    assert "max_tokens" not in seen[0]


def test_gemini_without_a_key_fails_before_calling_the_model(pool, monkeypatch):
    _use_gemini(monkeypatch, key=None)
    events = collect(pool, [sse({"content": "should not be sent"})])
    assert [e["type"] for e in events] == ["error"]
    assert "GEMINI_API_KEY" in events[-1]["message"]


def test_gemini_keeps_thought_signatures_and_separates_indexless_calls(pool, busy_faculty, monkeypatch):
    _use_gemini(monkeypatch)
    seen: list[dict[str, Any]] = []
    arguments = json.dumps({"faculty_id": busy_faculty, "limit": 1})
    events = collect(
        pool,
        [
            sse(
                {
                    "tool_calls": [
                        {
                            "id": "call_a",
                            "extra_content": {"google": {"thought_signature": "sig-a"}},
                            "function": {"name": "get_faculty_papers", "arguments": arguments},
                        },
                        {
                            "id": "call_b",
                            "extra_content": {"google": {"thought_signature": "sig-b"}},
                            "function": {"name": "get_faculty_papers", "arguments": arguments},
                        },
                    ]
                }
            ),
            sse({"content": "Done [P1]."}),
        ],
        seen=seen,
    )
    assistant = next(m for m in seen[1]["messages"] if m["role"] == "assistant")
    assert [c["extra_content"]["google"]["thought_signature"] for c in assistant["tool_calls"]] == ["sig-a", "sig-b"]
    assert [e["type"] for e in events if e["type"] == "status"] == ["status", "status"]
    assert events[-1] == {"type": "done", "cited": ["P1"]}


def test_argument_fragments_without_an_index_stay_on_one_call(pool, busy_faculty, monkeypatch):
    _use_gemini(monkeypatch)
    seen: list[dict[str, Any]] = []
    arguments = json.dumps({"faculty_id": busy_faculty, "limit": 1})
    collect(
        pool,
        [
            sse(
                {"tool_calls": [{"id": "call_1", "extra_content": {"google": {"thought_signature": "sig"}}, "function": {"name": "get_faculty_papers", "arguments": ""}}]},
                {"tool_calls": [{"function": {"arguments": arguments}}]},
            ),
            sse({"content": "Done [P1]."}),
        ],
        seen=seen,
    )
    assistant = next(m for m in seen[1]["messages"] if m["role"] == "assistant")
    assert len(assistant["tool_calls"]) == 1
    assert assistant["tool_calls"][0]["function"]["arguments"] == arguments
    assert assistant["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig"
