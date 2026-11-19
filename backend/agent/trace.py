"""Per-request chat trace: timed spans, saved to Postgres (`chat_traces`).

`run_chat` fills a `Trace`; the endpoint saves it when the stream ends, however it ends. Retrieval code, which
runs in a worker thread, reports into the active trace through `note` / `span` without any signature change.

By default a trace holds timings, counts and tool arguments only. TRACE_PAYLOADS=1 also stores the user's message
and every message sent to the model (tool results included): useful to debug one answer, but it is user text.
Tracing must never take a chat request down, so a failed save or purge is logged and dropped.
"""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from typing import Any
import contextvars
import logging
import os
import secrets
import time

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

log = logging.getLogger("uiuc.chat")

RETENTION_DAYS = 7

_active: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar("chat_trace", default=None)


def payloads_enabled() -> bool:
    return os.environ.get("TRACE_PAYLOADS") == "1"


@dataclass
class Trace:
    id: str = field(default_factory=lambda: secrets.token_hex(6))
    t0: float = field(default_factory=time.perf_counter)
    status: str = "aborted"  # run_chat sets ok / error; it stays "aborted" when the client left first
    attrs: dict[str, Any] = field(default_factory=dict)
    spans: list[dict[str, Any]] = field(default_factory=list)
    payload: list[dict[str, Any]] | None = None

    def ms(self) -> int:
        return round((time.perf_counter() - self.t0) * 1000)

    @contextmanager
    def span(self, name: str, /, **attrs: Any) -> Iterator[dict[str, Any]]:
        record: dict[str, Any] = {"name": name, "start_ms": self.ms(), "ms": 0, **attrs}
        self.spans.append(record)
        try:
            yield record
        finally:
            record["ms"] = self.ms() - record["start_ms"]

    def event(self, name: str, /, **attrs: Any) -> None:
        self.spans.append({"name": name, "start_ms": self.ms(), "ms": 0, **attrs})


@contextmanager
def active(trace: "Trace | None") -> Iterator[None]:
    """Make `trace` the target of `note` / `span` in this thread (a worker thread starts with a copied context)."""
    token = _active.set(trace)
    try:
        yield
    finally:
        _active.reset(token)


def note(name: str, /, **attrs: Any) -> None:
    trace = _active.get()
    if trace is not None:
        trace.event(name, **attrs)


def span(name: str, /, **attrs: Any):
    trace = _active.get()
    return trace.span(name, **attrs) if trace is not None else nullcontext({})


def save(pool: ConnectionPool, trace: Trace) -> None:
    try:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO chat_traces (id, status, duration_ms, attrs, spans, payload) VALUES (%s, %s, %s, %s, %s, %s)",
                [trace.id, trace.status, trace.ms(), Jsonb(trace.attrs), Jsonb(trace.spans), Jsonb(trace.payload) if trace.payload else None],
            )
    except Exception:
        log.warning("could not save trace %s", trace.id, exc_info=True)
        return
    log.info(
        "chat %s %s %dms rounds=%s tools=%s",
        trace.id,
        trace.status,
        trace.ms(),
        trace.attrs.get("rounds"),
        trace.attrs.get("tool_calls"),
    )


def purge(pool: ConnectionPool) -> None:
    days = int(os.environ.get("TRACE_RETENTION_DAYS", RETENTION_DAYS))
    try:
        with pool.connection() as conn:
            conn.execute("DELETE FROM chat_traces WHERE created_at < now() - make_interval(days => %s)", [days])
    except Exception:
        log.warning("could not purge old traces", exc_info=True)
