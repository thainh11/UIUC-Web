"""Embed papers (title + abstract) and faculty keywords via the vLLM embedding server.

Run: python -m ingestion.build_embeddings   (after load_db; resumable: only fills NULL embeddings)

The server is the Qwen3-Embedding-0.6B vLLM server (OpenAI-compatible, 1024-d,
L2-normalized). Documents are embedded without an instruction; queries must be prefixed with
QUERY_INSTRUCTION at search time (Qwen3-Embedding is instruction-aware).
"""

import os
import sys
import time

from dotenv import load_dotenv
import httpx
import psycopg

DIM = 1024  # must match VECTOR(1024) in db/schema.sql
BATCH = 32
MAX_CHARS = 8000  # ~2k tokens; the server accepts 8192 tokens, abstracts are far shorter
QUERY_INSTRUCTION = "Given a search query about academic research, retrieve relevant papers and researchers"


def embed(client: httpx.Client, url: str, model: str, texts: list[str]) -> list[list[float]]:
    for attempt in range(5):
        try:
            r = client.post(f"{url}/embeddings", json={"model": model, "input": texts})
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            vecs = [d["embedding"] for d in data]
            if len(vecs) != len(texts) or any(len(v) != DIM for v in vecs):
                sys.exit(f"unexpected embedding shape from {url} (expected {DIM}-d)")
            return vecs
        except httpx.HTTPError as e:
            wait = 2**attempt
            print(f"embedding request failed ({e!r}); retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    sys.exit("embedding server unreachable")


def fill(cur: psycopg.Cursor, client: httpx.Client, url: str, model: str, table: str, rows: list[tuple]) -> None:
    """rows: (id, text) for rows whose embedding is NULL."""
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        vecs = embed(client, url, model, [t[:MAX_CHARS] for _, t in chunk])
        cur.executemany(
            f"UPDATE {table} SET embedding = %s::vector WHERE id = %s",
            [(str(v), rid) for (rid, _), v in zip(chunk, vecs)],
        )
        print(f"{table}: {min(i + BATCH, len(rows))}/{len(rows)}", end="\r", flush=True)
    print()


def main() -> None:
    load_dotenv()
    url = os.environ.get("EMBEDDING_URL", "http://localhost:8032/v1")
    model = os.environ.get("EMBEDDING_MODEL", "Qwen3-Embedding-0.6B")
    db = os.environ.get("DATABASE_URL") or sys.exit("DATABASE_URL missing")
    with httpx.Client(timeout=120) as client, psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, title || E'\\n' || abstract FROM papers WHERE embedding IS NULL ORDER BY id")
        fill(cur, client, url, model, "papers", cur.fetchall())
        conn.commit()
        cur.execute("SELECT id, text FROM keywords WHERE embedding IS NULL ORDER BY id")
        fill(cur, client, url, model, "keywords", cur.fetchall())


if __name__ == "__main__":
    main()
