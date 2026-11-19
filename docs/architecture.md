# Ingestion, chat and trace internals

## Ingestion

`fetch_openalex` asks OpenAlex for institution `I157725225` (`ror:047426m28`). It keeps works in the date window that have an abstract, are not paratext, and are an article, preprint, conference paper, or review. The default window is the last 24 months. On 2026-11-16 that was 19,787 works. Pages land in `data/raw/openalex/works/` as `page_00001.json` and so on, plus `manifest.json`. A rerun continues from the last cursor. Changed date arguments abort, so two windows are not mixed. `--max-works` aborts when the match count is over the cap. `--from-date` and `--to-date` override the window.

`load_db` rebuilds abstracts from OpenAlex inverted indexes and loads faculty from the CSV (`email`, `name`, `photo_url`, `position`, `keywords`). Email is not unique in that file (one address belongs to two people), so faculty ids are assigned by the database. An authorship is marked `is_uiuc` when it lists `I157725225`. OpenAlex caps the stored author list at 100 names.

`build_embeddings` calls the Qwen3-Embedding-0.6B server. Documents are the paper title plus abstract, and each faculty keyword on its own. They are embedded with no instruction. Queries get an instruction prefix at search time, because this model expects one. The job fills only rows whose embedding is still null. Text is cut at 8,000 characters.

`link_authors` writes `faculty_id` on an authorship, not on an OpenAlex author id. One person can have several author ids, and some authorships have none. A link is considered when the authorship lists UIUC, or lists no institution. Authorships that list only some other institution are skipped. Three methods set `match_method`:

- `keywords`: same last name, a compatible first name, and enough of that person's keywords in the title, abstract, OpenAlex keywords, and topics. The score is a sum of IDF. If two faculty both pass, the winner has to beat the next score by a margin, or the authorship stays unlinked.
- `name`: a UIUC authorship that failed the keyword test, when the first names agree, the faculty name is unique in the directory, and the last name is not shared widely.
- `semantic`: a still-unlinked UIUC authorship with a common last name. The paper embedding is compared with that person's keyword embeddings. The paper has to sit at or above the 97th percentile of papers for that person, the first names have to agree, the faculty name has to be unique, and only one faculty member may pass.

Name compatibility allows equal first names, common nicknames, or an initial or a prefix of at least three letters, and middle initials must not conflict. The keyword score is an IDF sum: at least 10 when the first names are equal, and at least 20 when the match is only an initial or a prefix, or when the authorship lists no institution. Two faculty passing the same authorship need a gap of 1.5 or the row stays unlinked. A name-only link also requires the last name to be shared by fewer than four faculty.

## Chat

`LLM_PROVIDER=vllm` posts to `{LLM_URL}/chat/completions`. Start that vLLM process with `--enable-auto-tool-choice` and a tool-call parser. The request sets `chat_template_kwargs.enable_thinking` to false and `max_tokens` to 1500.

`LLM_PROVIDER=gemini` posts to `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` with `Authorization: Bearer $GEMINI_API_KEY`. The model is `GEMINI_MODEL`. Thinking level is `GEMINI_REASONING`, sent as `reasoning_effort`. A missing key fails before any request. Tool-call chunks from this endpoint often leave out `index` and put a `thought_signature` on the call; the loop stores that signature and sends it back on the next turn. Embeddings stay on `EMBEDDING_URL` for both providers.

The model can call `search_papers`, `search_faculty`, and `get_faculty_papers`. The prompt tells it to answer only from those results and to cite with refs such as `[P1]` and `[F2]`. The server drops a ref it never issued. Five rounds may call tools. The sixth round has tools turned off, so the model has to answer. The API uses temperature 0.3. `eval.chat` uses 0.

`search_papers` takes up to 60 full-text candidates and 60 embedding candidates, fuses them by reciprocal rank (`RRF_K` is 60), and weights full text at 0.25 (`FTS_WEIGHT`). Rows under cosine 0.45 are dropped (`MIN_SIMILARITY` in `backend/agent/search.py`). For "most recent", "latest", or "newest", the pool is the 20 best fused hits within 0.10 cosine of the top one (`RECENT_POOL`, `RECENT_MARGIN`). The most similar `limit` papers of that pool are kept and then sorted by date, so relevance decides which papers appear and the date only decides their order. `eval.run` reports this list as `retrieval.hybrid.recent.date_sorted_precision@6`. The tool's default limit is 6 and the cap is 10. Abstracts handed to the model are cut at 450 characters.

`search_faculty` embeds the topic phrase and each concept separately. Paper evidence is faculty linked to papers inside the 200 closest to the topic. Keyword evidence is the single closest keyword for each concept, kept from cosine 0.58 (`KEYWORD_MIN` in `backend/agent/faculty.py`). A person can rank on papers, on keywords, or on both. The default limit is 8. `get_faculty_papers` lists one person's papers, newest first, default 8, cap 10. The `faculty_id` has to come from an earlier search or from the records already named in the prompt.

Stream events:

- `status`: a tool started, with a short sentence for the UI
- `sources`: records the model may cite, keyed by ref
- `delta`: a piece of the answer
- `reset`: drop text that was streamed before a tool call
- `done`: `cited` refs, in order of first use
- `error`: the stream ends because something failed: the model, the embedding server, or a database or tool error; the message ends with the trace id

The request's `history` is plain text, at most 20 turns. The model sees the last 8. `context` is `{kind: "faculty", id}` when a profile is open. `known` is `[{kind: "paper"|"faculty", id}]` for records cited earlier. The server looks each id up, drops unknown ids, assigns refs for this turn, and adds the names to the system prompt. A follow-up such as "what has the second one published" can call `get_faculty_papers` with that `faculty_id` instead of searching by name again. The browser keeps the last 20 messages, their sources, and the open profile in `sessionStorage`. New chat clears them.

## Traces

Every chat request inserts one `chat_traces` row: status `ok`, `error`, or `aborted` when the client left first, plus duration and spans. Spans include `preload`, `llm.round` (with time to first token), `tool`, `embed`, and `retrieval.*` (candidate counts, top cosine scores, and how many rows the 0.45 floor removed). The id is 12 hex characters. It is sent as `X-Trace-Id` and appended to the error text.

```sh
uv run python -m backend.agent.trace_cli tail -n 20 [--status error]
uv run python -m backend.agent.trace_cli show <id>
```

A normal row stores counts, timings, and tool arguments. `TRACE_PAYLOADS=1` also stores the question and every message sent to the model, tool results included. That is visitor text, so leave it off except while debugging one answer. Rows older than `TRACE_RETENTION_DAYS` are deleted when the API process starts. If the save fails, the failure is logged and the chat still finishes. `LOG_LEVEL` sets the `uiuc` logger. One INFO line is written per chat.

## Evaluation details

`eval.run` exits 1 when a gated test-split metric falls under the saved baseline. Coverage and raw link counts are printed and are not gated. `--save` rewrites `eval/gold/baseline.json`. `--sweep` walks linking thresholds.

`eval.chat` needs the database, the embedding server, and whichever chat model `LLM_PROVIDER` points at. It writes each answer to `eval/work/chat_run.jsonl`. With at least ten gold topics and the faculty queries returning their full limits, the run has 47 cases: ten topics asked once for papers and once for faculty, five people by name, four open profiles, two off-topic questions asked while a profile is open, four follow-ups, ten off-topic questions, and the two task questions. Temperature is 0. `--save` rewrites `eval/gold/chat_baseline.json`. The saved baseline is the vLLM run. A Gemini run will not match it.

`eval.faculty_recall` calls OpenAlex, so it needs `OPENALEX_API_KEY`. It also checks works whose author list was cut at 100 names: the single-work endpoint still returns the full list.
