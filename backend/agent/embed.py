"""Query embeddings from the Qwen3-Embedding vLLM server (the same one that embedded the documents)."""

import os

from dotenv import load_dotenv
import httpx

from ingestion.build_embeddings import QUERY_INSTRUCTION

load_dotenv()

_client = httpx.Client(timeout=30)


class EmbeddingUnavailable(RuntimeError):
    pass


def embed_queries(texts: list[str]) -> list[list[float]]:
    """L2-normalized vectors for search queries. Documents were embedded without an instruction; queries need it."""
    url = os.environ.get("EMBEDDING_URL", "http://localhost:8032/v1")
    model = os.environ.get("EMBEDDING_MODEL", "Qwen3-Embedding-0.6B")
    try:
        response = _client.post(
            f"{url}/embeddings",
            json={"model": model, "input": [f"Instruct: {QUERY_INSTRUCTION}\nQuery:{text}" for text in texts]},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EmbeddingUnavailable(f"embedding server unavailable: {exc}") from exc
    data = sorted(response.json()["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in data]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"
