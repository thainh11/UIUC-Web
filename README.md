# UIUC Research Portal + LLM Assistant

A single page for University of Illinois Urbana-Champaign research from the last two years, plus an assistant that answers from that same data. The assistant is aimed at questions such as "What are the most recent UIUC papers on AI in war conflict?" and "Which faculty members work on Computer Vision in Healthcare?"

Bản tiếng Việt: [README.vi.md](README.vi.md)

## Table of contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Data sources and credits](#data-sources-and-credits)
- [API](#api)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

## Features

- **Overview:** campus totals (papers, author profiles, citations, open-access share, faculty) for the last two years.
- **Output and topics:** monthly publication chart and focus areas that filter the paper list.
- **Papers:** searchable, sortable list with DOI links and linked faculty.
- **Faculty directory:** cards and profile drawer with linked papers.
- **Assistant:** chat that answers only from the database, cites papers and faculty, and streams its reply.

The demo video (a full tour of the page and the assistant) is linked from the submission form. Recordings are kept out of this repository.

## Tech stack

| Layer | Technology |
|---|---|
| Data source | OpenAlex API, faculty CSV |
| Database | PostgreSQL 16 + pgvector |
| Backend | Python 3.12+, FastAPI, psycopg, `uv` |
| Embeddings | Qwen3-Embedding-0.6B (local server) |
| Chat model | Qwen3.8-27B AWQ-INT4 on vLLM, or Gemini |
| Packaging | Docker Compose, nginx |
| Frontend | React, Vite, TypeScript, Tailwind, Recharts |

## Quick start

The repository packages the whole stack in `docker-compose.yml`:

| Service | What it runs | Host port | Needs GPU |
|---|---|---|---|
| `db` | PostgreSQL 16 + pgvector | 5432 | no |
| `embedding` | vLLM serving Qwen3-Embedding-0.6B | 8032 | yes |
| `llm` | vLLM serving Qwen3.8-27B AWQ-INT4 | 8116 | yes |
| `api` | FastAPI backend (`Dockerfile`) | 8100 | no |
| `web` | React build served by nginx, proxies `/api` to `api` (`frontend/Dockerfile`) | 5180 | no |
| `ingest` | One-off data pipeline, started on demand (profile `ingest`) | | no |

Prerequisites: Docker with Compose v2, an [OpenAlex API key](https://openalex.org), and an NVIDIA GPU with the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) for `embedding` and `llm`. The two models together need about 22 GB of disk and, at the default settings, a GPU with 40 GB of memory or more (the chat server reserves 74% of its GPU and the embedding server 15%; the chat model is a 27B model quantized to 4 bits).

```sh
# 1. Configure
cp .env.example .env        # set OPENALEX_API_KEY; add GEMINI_API_KEY only if you use Gemini

# 2. Download the checkpoints into ./models (see "Models")
export HF_HOME=$PWD/models
hf download Qwen/Qwen3-Embedding-0.6B
hf download cyankiwi/Qwen3.8-27B-AWQ-INT4

# 3. Start everything
docker compose up -d --build

# 4. Load data once the embedding server is healthy (see "Data pipeline")
docker compose --profile ingest run --rm ingest
```

Open http://localhost:5180. API docs are at http://localhost:8100/docs. The first start of `llm` takes several minutes while vLLM loads the model; follow it with `docker compose logs -f llm`.

Inside Compose, `api` and `ingest` reach the other services by name (`db`, `embedding`, `llm`), so the `localhost` URLs in `.env` do not matter there. `db`, `embedding`, `llm` and `api` publish their ports on `127.0.0.1` only, so you can run `eval` and the checks from the same machine without exposing the database or the model servers; only `web` listens on every interface. To put both models on separate GPUs, set `EMBEDDING_GPU` and `LLM_GPU` (GPU indexes, default `0` for both) in `.env`. To use Gemini for chat, set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`, and start without the chat model: `docker compose up -d --build db embedding api web`.

### Run without Docker

You also need Python 3.12+, [`uv`](https://docs.astral.sh/uv/), Node, and the two vLLM servers started yourself (see "Models").

```sh
cp .env.example .env
docker compose up -d db
uv sync
cd frontend && npm install && cd ..

uv run python -m ingestion.fetch_openalex
uv run python -m ingestion.load_db
uv run python -m ingestion.build_embeddings
uv run python -m ingestion.link_authors

uv run uvicorn backend.app.main:app --reload --port 8100      # terminal 1
cd frontend && npm run dev                                    # terminal 2
```

### Models

| Role | Hugging Face repo | Size | Served name |
|---|---|---|---|
| Embedding | [`Qwen/Qwen3-Embedding-0.6B`](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | 1.2 GB | `Qwen3-Embedding-0.6B` |
| Chat | [`cyankiwi/Qwen3.8-27B-AWQ-INT4`](https://huggingface.co/cyankiwi/Qwen3.8-27B-AWQ-INT4) | ~21 GB | `qwen3.8-27b` |

Download them with the [`hf` CLI](https://huggingface.co/docs/huggingface_hub/guides/cli) (`pip install -U huggingface_hub`). With `HF_HOME=$PWD/models` the files land in `models/hub/`, which Compose mounts read-only into both vLLM containers. The containers run offline, so a model that was not downloaded fails at start instead of being fetched. `models/` is gitignored. The chat model is Apache-2.0; check each repo's license before redistributing.

`LLM_MODEL` and `EMBEDDING_MODEL` must equal the `--served-model-name` of the matching server. Without Docker, start the two servers like this (the flags are the ones in `docker-compose.yml`):

```sh
vllm serve Qwen/Qwen3-Embedding-0.6B --served-model-name Qwen3-Embedding-0.6B \
  --runner pooling --convert embed --dtype bfloat16 --max-model-len 8192 \
  --max-num-seqs 16 --max-num-batched-tokens 8192 --gpu-memory-utilization 0.15 --port 8032

vllm serve cyankiwi/Qwen3.8-27B-AWQ-INT4 --served-model-name qwen3.8-27b \
  --quantization compressed-tensors --dtype bfloat16 --max-model-len 32768 \
  --gpu-memory-utilization 0.74 --max-num-seqs 8 --max-num-batched-tokens 8192 \
  --enable-prefix-caching --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 --trust-remote-code --port 8116
```

### Data pipeline

| Step | Module | Time | Notes |
|---|---|---|---|
| Fetch | `ingestion.fetch_openalex` | ~6 min, ~$0.02 | Resumable. Writes `data/raw/openalex/works/` |
| Load | `ingestion.load_db` | ~35 s | Drops and reloads the data tables. `chat_traces` is kept |
| Embed | `ingestion.build_embeddings` | ~5 min | Needs the embedding server. Resumable |
| Link | `ingestion.link_authors` | ~1.5 min | Needs embeddings. Safe to re-run |

`docker compose --profile ingest run --rm ingest` runs the four steps in this order and keeps the files in `./data`. Embeddings and faculty links must be rebuilt after every `load_db`. The default window is the last 24 months; `--from-date`, `--to-date` and `--max-works` adjust it.

## Configuration

Set these in `.env`.

| Variable | Default | Used for |
|---|---|---|
| `OPENALEX_API_KEY` | | `ingestion.fetch_openalex` and `eval.faculty_recall` |
| `DATABASE_URL` | `postgresql://uiuc:uiuc@localhost:5432/uiuc` | API, ingestion, eval |
| `EMBEDDING_URL` | `http://localhost:8032/v1` | Embeddings and every search |
| `EMBEDDING_MODEL` | `Qwen3-Embedding-0.6B` | Same server. Vectors are 1024-d |
| `LLM_PROVIDER` | `vllm` | `vllm` or `gemini` |
| `LLM_URL` | `http://localhost:8116/v1` | vLLM chat |
| `LLM_MODEL` | `qwen3.8-27b` | vLLM chat. Must equal `--served-model-name` |
| `EMBEDDING_GPU` | `0` | Docker only: GPU index for `embedding` |
| `LLM_GPU` | `0` | Docker only: GPU index for `llm` |
| `GEMINI_API_KEY` | | Required when `LLM_PROVIDER=gemini` |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini chat |
| `GEMINI_REASONING` | `low` | Sent as `reasoning_effort` |
| `TRACE_PAYLOADS` | off | `1` stores the question and model messages in traces |
| `TRACE_RETENTION_DAYS` | `7` | Traces older than this are deleted when the API starts |
| `LOG_LEVEL` | `INFO` | Logger `uiuc` |

## Architecture

Ingestion runs offline and writes one Postgres database. The page and the assistant both read that database. A request from the browser does not call OpenAlex.

```text
OpenAlex                         illinois-researchers.csv
   |                                      |
   v                                      v
fetch_openalex                      read by load_db
   |
   v
load_db -----------------> PostgreSQL + pgvector
                           papers, authors, topics, faculty, keywords
                           full-text index; embedding columns still empty
   |
   v
build_embeddings --------> local embedding server (Qwen3-Embedding-0.6B)
   |
   v
link_authors ------------> faculty_id on each matching authorship
   |
   +--> FastAPI /api/*  -->  React page on port 5180 (nginx in Compose, Vite in dev)
   |
   +--> POST /api/chat
          three tools read the same database
          query embeddings stay on the local server
          the reply comes from local vLLM, or from Gemini when LLM_PROVIDER=gemini
```

`docker compose up` starts every box above except the one-off `ingest` job. The embedding server and, for the default provider, the vLLM chat server are separate containers.

| Path | What it holds |
|---|---|
| `data/raw/illinois-researchers.csv` | Faculty export: email, name, photo, position, keywords |
| `data/raw/openalex/` | Cached OpenAlex pages (gitignored) |
| `docs/` | `architecture.md`: ingestion, the linking rules, chat, traces, evaluation. `design.md`: page design |
| `ingestion/` | Fetch, CSV parse, database load, embeddings, author linking |
| `db/schema.sql` | Postgres schema, including `chat_traces` |
| `backend/app/` | FastAPI: `routers/`, `services/`, `schemas.py` |
| `backend/agent/` | Search, the three tools, the chat loop, traces |
| `backend/tests/` | API and agent tests against the real database, with the model scripted |
| `eval/` | Retrieval, linking, faculty recall, and live chat checks |
| `frontend/` | React + Vite + TypeScript, one page |
| `Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | Images for the API and the web page, and the full stack |
| `models/` | Downloaded checkpoints, mounted into the vLLM containers (gitignored) |

## Data sources and credits

| Data | Source | License |
|---|---|---|
| Papers, authorships, topics | [OpenAlex](https://openalex.org) works API, institution `I157725225` | CC0 |
| Faculty directory | `data/raw/illinois-researchers.csv`, supplied with the assignment | As supplied |
| Campus photo | "Main Quad - UIUC" by Daderot, [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Main_Quad_-_UIUC_-_DSC09116.JPG) | Public domain |
| Location | Urbana–Champaign, Illinois; the map pin links to [OpenStreetMap](https://www.openstreetmap.org/?mlat=40.1070&mlon=-88.2272#map=14/40.1070/-88.2272) at the Main Quad (40.1070, -88.2272) | ODbL |

## API

| Endpoint | What it returns |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `GET /api/overview` | Papers, citations, open-access share, date range, topic count, faculty, linked faculty, distinct UIUC OpenAlex author ids |
| `GET /api/stats/publications-by-month` | `{month, count, year_only}` per month. First and last months are partial. `year_only` counts papers dated 1 January, which nearly always means only the year is known |
| `GET /api/stats/topics?level=domain\|field\|subfield\|topic&limit=` | Papers per topic level |
| `GET /api/papers?query=&topic=&subfield=&field=&domain=&sort=date\|citations\|relevance&page=&page_size=` | Paginated papers. `query` is English full text on title and abstract, at most 300 characters. `page` is 1 to 100,000. `page_size` is 1 to 50, default 20 |
| `GET /api/papers/{id}` | Abstract, topics, keywords, and the full author list, with faculty ids where a link exists |
| `GET /api/faculty?query=&page=&page_size=` | Name or keyword substring, at most 300 characters. Most linked papers first. `page` is 1 to 100,000. `page_size` is 1 to 100, default 24 |
| `GET /api/faculty/{id}` | Profile, keywords, and up to 100 linked papers, newest first |
| `POST /api/chat` | `{message, history, context?, known?}`. Server-sent events. Response header `X-Trace-Id` |

`message` is at most 2,000 characters. Each history turn is at most 6,000, and `history` holds at most 20 turns. `known` holds at most 30 records.

The chat stream sends `status`, `sources`, `delta`, `reset`, `done` and `error` events. The model has three tools: `search_papers`, `search_faculty` and `get_faculty_papers`, and cites results as `[P1]`, `[F2]`.

## Testing

```sh
uv run pytest                          # backend/tests; needs the loaded database, the OpenAlex cache from fetch, and the embedding server; the chat model is scripted
uv run python -m eval.run              # linking and retrieval against eval/gold/baseline.json
uv run python -m eval.chat             # live model; compares to eval/gold/chat_baseline.json
uv run python -m eval.faculty_recall   # 30 faculty, linked papers vs the OpenAlex work count (needs OPENALEX_API_KEY)
```

Frontend:

```sh
cd frontend
npm run dev        # http://localhost:5180, proxies /api to API_URL (default http://localhost:8100)
npm run gen:api    # regenerate src/api/schema.d.ts from the running API's OpenAPI
npm run build && npm run lint
npm test           # vitest, src/**/*.test.ts
npm run e2e        # Playwright + axe against the real API; needs the DB and uvicorn on :8100
                   # first time: npx playwright install chromium
```

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Search or chat fails, or `build_embeddings` errors | The embedding server is not reachable. Check `EMBEDDING_URL`. Search needs it even when chat uses Gemini |
| Chat never calls tools or returns tool errors | Start vLLM with `--enable-auto-tool-choice` and a tool-call parser |
| Chat fails immediately with `LLM_PROVIDER=gemini` | `GEMINI_API_KEY` is missing |
| Faculty show no papers, or search returns nothing | Embeddings and links were not rebuilt after `load_db`. Run `build_embeddings` then `link_authors` |
| `fetch_openalex` aborts on start | The date arguments differ from the cached run. Use the same dates, or clear `data/raw/openalex/works/` |
| Chat error ending in a 12-character id | Look it up: `uv run python -m backend.agent.trace_cli show <id>` |
| Database connection refused | `docker compose up -d db`, and check `DATABASE_URL` |
| `llm` or `embedding` exits at start with a model-not-found error | The checkpoint is not in `./models`. Run the `hf download` commands with `HF_HOME=$PWD/models` |
| `llm` exits with an out-of-memory error | Another process holds the GPU. Set `LLM_GPU` and `EMBEDDING_GPU` to different GPUs, or free the card |
| `docker compose up` cannot start `llm` or `embedding` (no GPU driver) | Install the NVIDIA Container Toolkit, or use Gemini and start only `db embedding api web` |
| Host ports 5432, 8032, 8100, 8116 or 5180 already in use | Stop the other process, or change the host port in the `ports` entry in `docker-compose.yml` (the number before the container port, e.g. `127.0.0.1:15432:5432`) |
