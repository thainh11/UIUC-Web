from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
import httpx

from ..agent.trace import purge
from .db import make_pool
from .routers import chat, faculty, overview, papers

_log = logging.getLogger("uiuc")
_log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s"))
_log.addHandler(_handler)
_log.propagate = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = make_pool()
    app.state.pool.open(wait=True)
    purge(app.state.pool)
    # No overall deadline: an answer streams for as long as the model writes. A stalled server still fails on `read`.
    app.state.llm = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5, read=120))
    yield
    await app.state.llm.aclose()
    app.state.pool.close()


app = FastAPI(title="UIUC Research Portal API", lifespan=lifespan)
app.include_router(overview.router)
app.include_router(papers.router)
app.include_router(faculty.router)
app.include_router(chat.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
