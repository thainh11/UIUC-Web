"""Trace storage and the chat endpoint's contract (the model is scripted; the database is real)."""

import asyncio
import json
import time

import httpx
import pytest

from backend.agent.trace import Trace, purge, save


def scripted_llm(text: str) -> httpx.AsyncClient:
    body = f"data: {json.dumps({'choices': [{'delta': {'content': text}, 'finish_reason': None}]})}\n\ndata: [DONE]\n\n"
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    )


@pytest.fixture
def scripted(client):
    original = client.app.state.llm
    client.app.state.llm = scripted_llm("Hello from the model.")
    yield client
    client.app.state.llm = original


def test_a_chat_request_saves_its_trace_under_the_id_in_the_header(scripted, db):
    res = scripted.post("/api/chat", json={"message": "hi"})
    trace_id = res.headers["x-trace-id"]
    row = db.execute("SELECT status, attrs, spans, payload FROM chat_traces WHERE id = %s", [trace_id]).fetchone()
    assert "event: done" in res.text
    assert row["status"] == "ok" and row["attrs"]["message_chars"] == 2 and row["payload"] is None
    assert [s["name"] for s in row["spans"]] == ["preload", "llm.round"]
    db.execute("DELETE FROM chat_traces WHERE id = %s", [trace_id])


@pytest.mark.parametrize(
    "extra",
    [
        {"context": {"kind": "paper", "id": 1}},
        {"context": {"kind": "faculty", "id": "abc"}},
        {"known": [{"kind": "faculty", "id": str(i)} for i in range(31)]},
        {"known": [{"kind": "author", "id": "1"}]},
    ],
)
def test_malformed_context_or_known_is_rejected(scripted, extra):
    assert scripted.post("/api/chat", json={"message": "hi", **extra}).status_code == 422


class _Hold(httpx.AsyncByteStream):
    """One SSE chunk, then block. Closing the portal stream must cancel this wait."""

    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        await asyncio.Event().wait()


def test_a_client_that_leaves_mid_answer_is_traced_as_aborted(client, db):
    original = client.app.state.llm

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Hold(), headers={"content-type": "text/event-stream"})

    client.app.state.llm = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    trace_id = ""
    try:
        with client.stream("POST", "/api/chat", json={"message": "hi"}) as res:
            trace_id = res.headers["x-trace-id"]
            seen = ""
            for chunk in res.iter_text():
                seen += chunk
                if "Hi" in seen:
                    break
            assert "event: delta" in seen and "Hi" in seen
        row = None
        for _ in range(50):
            row = db.execute("SELECT status FROM chat_traces WHERE id = %s", [trace_id]).fetchone()
            if row:
                break
            time.sleep(0.05)
        assert row is not None and row["status"] == "aborted"
    finally:
        client.app.state.llm = original
        if trace_id:
            db.execute("DELETE FROM chat_traces WHERE id = %s", [trace_id])


def test_purge_removes_only_old_traces(pool, db):
    fresh, old = Trace(), Trace()
    for trace in (fresh, old):
        save(pool, trace)
    db.execute("UPDATE chat_traces SET created_at = now() - interval '8 days' WHERE id = %s", [old.id])
    purge(pool)
    ids = {r["id"] for r in db.execute("SELECT id FROM chat_traces WHERE id = ANY(%s)", [[fresh.id, old.id]])}
    assert ids == {fresh.id}
    db.execute("DELETE FROM chat_traces WHERE id = %s", [fresh.id])
