from collections.abc import AsyncIterator
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from psycopg_pool import ConnectionPool

from ...agent.agent import run_chat
from ...agent.trace import Trace, save
from ..schemas import ChatRequest

router = APIRouter(prefix="/api/chat")


async def _sse(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    async for event in events:
        kind = event["type"]
        yield f"event: {kind}\ndata: {json.dumps({k: v for k, v in event.items() if k != 'type'}, ensure_ascii=False)}\n\n"


async def _traced(chunks: AsyncIterator[str], pool: ConnectionPool, trace: Trace) -> AsyncIterator[str]:
    try:
        async for chunk in chunks:
            yield chunk
    finally:
        # A client that leaves cancels this task, and every plain await in a cancelled task raises again.
        # The shielded save still runs to the end.
        await asyncio.shield(asyncio.to_thread(save, pool, trace))


@router.post("", response_class=StreamingResponse, responses={200: {"content": {"text/event-stream": {}}}})
async def chat(body: ChatRequest, request: Request):
    """Answer a question with a tool-calling agent. Server-sent events: status, sources, delta, reset, done, error.

    `context` is the faculty profile the user has open; `known` are records cited earlier in the conversation.
    The response carries `X-Trace-Id`; the trace is saved in `chat_traces`.
    """
    pool = request.app.state.pool
    trace = Trace()
    events = run_chat(
        pool,
        request.app.state.llm,
        body.message,
        [turn.model_dump() for turn in body.history],
        context=body.context.model_dump() if body.context else None,
        known=[item.model_dump() for item in body.known],
        trace=trace,
    )
    return StreamingResponse(
        _traced(_sse(events), pool, trace),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Trace-Id": trace.id},
    )
