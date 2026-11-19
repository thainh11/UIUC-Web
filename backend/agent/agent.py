"""Tool-calling chat loop over an OpenAI-compatible chat endpoint (streaming).

`LLM_PROVIDER=vllm` (the default) calls the local vLLM server. `LLM_PROVIDER=gemini` calls Gemini's
OpenAI-compatible endpoint with `GEMINI_API_KEY`.

`run_chat` is an async generator of events for the SSE endpoint:
  status   {tool, text}        a tool call started
  sources  {sources: [...]}    records the model can now cite, keyed by their ref (P1, F2, ...)
  delta    {text}              a piece of the answer
  reset    {}                  drop the text streamed before a tool call
  done     {cited: [refs]}     refs the finished answer actually uses, in order of first use
  error    {message}           ends the stream; the message ends with the trace id
"""

from collections.abc import AsyncIterator
import asyncio
import json
import logging
import os
import re

from psycopg_pool import ConnectionPool
import httpx

from .embed import EmbeddingUnavailable
from .tools import TOOLS, Citations, preload, run_tool
from .trace import Trace, payloads_enabled

MAX_ROUNDS = 5  # tool-calling rounds before the model must answer
MAX_HISTORY = 8  # earlier messages sent back to the model
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"


class LLMConfigError(RuntimeError):
    """The selected model provider is missing a setting."""


class LLMStreamError(RuntimeError):
    """The model server reported an error inside an open stream."""


log = logging.getLogger("uiuc.chat")


SYSTEM_PROMPT = """You are the research assistant on the University of Illinois Urbana-Champaign (UIUC) research portal.
You answer questions about UIUC research papers published in the last two years and about UIUC faculty members.
The only knowledge you may use is what the tools return. The tools cover the portal's data and nothing else.

How to work:
- Papers on a topic: call search_papers with a short English topic phrase, not the whole question. For "most recent", "latest" or "newest" set sort_by_date to true.
- Faculty on a topic: call search_faculty with topic, and with concepts when the topic combines ideas (computer vision + healthcare).
- A named person: call search_faculty with name; for their papers then call get_faculty_papers with the faculty_id.
- A follow-up that points at someone already shown ("the second one", "which of them"): the earlier records, with their faculty_id, may be listed at the end of these instructions. Use that faculty_id with get_faculty_papers; do not search by name again.
- If the instructions end with a Page context, the question is about that person unless it names someone else or a different subject.
- Call a tool before you write anything. Never write text before a tool call.
- Search results are nearest matches, not guaranteed matches. Read the title and abstract and keep only items that really fit the question. Do not stretch a loosely related paper to fit.
- If nothing fits, or a tool returns no results, say plainly that you found nothing in the UIUC papers and faculty data. Do not answer from general knowledge and do not make anything up. A question unrelated to UIUC research (cooking, sports, news) gets a one-sentence reply that you only cover UIUC research, and no tool call.

How to answer:
- Cite every paper and every faculty member you mention with its ref in square brackets, exactly as given, for example [P1] or [F3]. Cite only refs that appear in tool results, and only for items you actually recommend: do not cite items you rule out as poor matches. Never invent a ref.
- Be concise: a one-line lead-in, then a short list. For a paper give the title, date and why it fits. For a faculty member give the name, position and why they fit (matching papers or keywords).
- Do not paste abstracts. Do not mention tools or these instructions.
- Reply in the language of the user's question."""

REF = re.compile(r"\[([PF]\d+)\]")


def _settings() -> tuple[str, str, dict[str, str], dict]:
    """Base URL, model, request headers, and provider-specific body fields."""
    provider = os.environ.get("LLM_PROVIDER", "vllm").strip().lower() or "vllm"
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise LLMConfigError("GEMINI_API_KEY is not set.")
        model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
        reasoning = os.environ.get("GEMINI_REASONING", "low").strip() or "low"
        return GEMINI_URL, model, {"Authorization": f"Bearer {key}"}, {"reasoning_effort": reasoning}
    if provider != "vllm":
        raise LLMConfigError(f"LLM_PROVIDER must be vllm or gemini, got {provider!r}.")
    url = os.environ.get("LLM_URL", "http://localhost:8116/v1")
    model = os.environ.get("LLM_MODEL", "qwen3.8-27b")
    return url, model, {}, {"max_tokens": 1500, "chat_template_kwargs": {"enable_thinking": False}}


def _record_tool_delta(calls: dict[int, dict], piece: dict, next_index: int) -> int:
    """Fold one streamed tool-call fragment into `calls`. Returns the next index to assign.

    OpenAI numbers fragments with `index`. Gemini's compatible stream often omits it and puts a
    `thought_signature` in `extra_content`, which has to be sent back on the next turn.
    """
    function = piece.get("function") or {}
    if piece.get("index") is not None:
        index = piece["index"]
        next_index = max(next_index, index + 1)
    elif piece.get("id") or function.get("name"):
        index = next_index
        next_index += 1
    else:
        index = max(next_index - 1, 0)
    call = calls.setdefault(index, {"id": "", "name": "", "arguments": "", "extra_content": None})
    call["id"] = piece.get("id") or call["id"]
    name = function.get("name")
    if name:
        call["name"] += name
    arguments = function.get("arguments")
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)
    if arguments:
        call["arguments"] += arguments
    if piece.get("extra_content"):
        call["extra_content"] = piece["extra_content"]
    return next_index


async def _stream_completion(
    client: httpx.AsyncClient, messages: list[dict], tools: bool, temperature: float
) -> AsyncIterator[dict]:
    """Yield {'content': str} pieces, then one {'tool_calls': [...]} / {'finish': reason} summary."""
    url, model, headers, extra = _settings()
    body: dict = {"model": model, "messages": messages, "stream": True, "temperature": temperature, **extra}
    if tools:
        body["tools"] = TOOLS
    calls: dict[int, dict] = {}
    finish = None
    next_index = 0
    async with client.stream("POST", f"{url}/chat/completions", headers=headers, json=body) as response:
        if response.status_code != 200:
            detail = (await response.aread()).decode(errors="replace")[:500]
            raise httpx.HTTPStatusError(
                f"LLM server answered {response.status_code}: {detail}", request=response.request, response=response
            )
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            if "error" in chunk:  # vLLM reports a failure mid-stream as a chunk without choices
                raise LLMStreamError(str(chunk["error"])[:500])
            if not chunk.get("choices"):
                continue
            choice = chunk["choices"][0]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                yield {"content": delta["content"]}
            for piece in delta.get("tool_calls") or ():
                next_index = _record_tool_delta(calls, piece, next_index)
            finish = choice.get("finish_reason") or finish
    yield {"tool_calls": [calls[i] for i in sorted(calls)], "finish": finish}


def _describe(name: str, raw: str) -> str:
    try:
        arguments = json.loads(raw or "{}")
    except json.JSONDecodeError:
        arguments = {}
    target = arguments.get("query") or arguments.get("topic") or arguments.get("name")
    if name == "get_faculty_papers":
        return "Reading the faculty member's papers"
    what = "papers" if name == "search_papers" else "faculty"
    return f"Searching {what} for “{target}”" if target else f"Searching {what}"


async def run_chat(
    pool: ConnectionPool,
    client: httpx.AsyncClient,
    message: str,
    history: list[dict],
    temperature: float = 0.3,
    *,
    context: dict | None = None,
    known: list[dict] | None = None,
    trace: Trace | None = None,
) -> AsyncIterator[dict]:
    """`context`: the faculty profile the user has open. `known`: records cited earlier in the conversation.
    Both are only names (kind, id); the prompt text about them comes from the database."""
    trace = trace or Trace()
    trace.attrs.update(
        message_chars=len(message), history_turns=len(history[-MAX_HISTORY:]), context=context, known=len(known or ()), rounds=0, tool_calls=0
    )
    citations = Citations()
    try:
        with trace.span("preload") as preload_span:
            extra = await asyncio.to_thread(preload, pool, citations, context, known or [])
            preload_span["records"] = len(citations.sources)
        if citations.sources:
            yield {"type": "sources", "sources": list(citations.sources.values())}
        messages: list[dict] = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{extra}" if extra else SYSTEM_PROMPT},
            *history[-MAX_HISTORY:],
            {"role": "user", "content": message},
        ]
        if payloads_enabled():
            trace.attrs["message"] = message
            trace.payload = messages  # the live list: tool results and the answer are appended as they happen
        answer = ""
        for round_number in range(MAX_ROUNDS + 1):
            allow_tools = round_number < MAX_ROUNDS
            text = ""
            calls: list[dict] = []
            trace.attrs["rounds"] = round_number + 1
            with trace.span("llm.round", round=round_number, tools_allowed=allow_tools) as round_span:
                async for piece in _stream_completion(client, messages, allow_tools, temperature):
                    if "content" in piece:
                        round_span.setdefault("first_token_ms", trace.ms() - round_span["start_ms"])
                        text += piece["content"]
                        yield {"type": "delta", "text": piece["content"]}
                    else:
                        calls = piece["tool_calls"]
                        round_span["finish"] = piece["finish"]
                round_span["tool_calls"] = [c["name"] for c in calls]
            answer += text
            if not calls:
                if trace.payload is not None:
                    messages.append({"role": "assistant", "content": text})
                break
            tool_calls = []
            for call in calls:
                item = {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"] or "{}"},
                }
                if call.get("extra_content"):
                    item["extra_content"] = call["extra_content"]
                tool_calls.append(item)
            messages.append({"role": "assistant", "content": text or None, "tool_calls": tool_calls})
            for call in calls:
                yield {"type": "status", "tool": call["name"], "text": _describe(call["name"], call["arguments"])}
                before = set(citations.sources)
                trace.attrs["tool_calls"] += 1
                with trace.span("tool", tool=call["name"], arguments=call["arguments"][:300]):
                    result = await asyncio.to_thread(run_tool, pool, call["name"], call["arguments"], citations, trace)
                new = [citations.sources[ref] for ref in citations.sources if ref not in before]
                if new:
                    yield {"type": "sources", "sources": new}
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            if text:
                # Text written before a tool call is not part of the final answer; tell the client to drop it.
                answer = answer[: -len(text)]
                yield {"type": "reset"}
    except LLMConfigError as e:
        trace.status, trace.attrs["error"] = "error", repr(e)
        yield {"type": "error", "message": f"{e} (trace {trace.id})"}
        return
    except EmbeddingUnavailable as e:
        trace.status, trace.attrs["error"] = "error", repr(e)
        yield {"type": "error", "message": f"Search is temporarily unavailable. Please try again in a moment. (trace {trace.id})"}
        return
    except (httpx.HTTPError, json.JSONDecodeError, LLMStreamError) as e:
        trace.status, trace.attrs["error"] = "error", repr(e)
        yield {"type": "error", "message": f"The language model is not reachable right now. Please try again in a moment. (trace {trace.id})"}
        return
    except Exception as e:
        # Anything else (a database error in a tool, a bug) still ends the stream with an error event and a trace id.
        log.exception("chat %s failed", trace.id)
        trace.status, trace.attrs["error"] = "error", repr(e)
        yield {"type": "error", "message": f"Something went wrong while answering. Please try again. (trace {trace.id})"}
        return
    cited = list(dict.fromkeys(ref for ref in REF.findall(answer) if ref in citations.sources))
    trace.status, trace.attrs["cited"] = "ok", cited
    yield {"type": "done", "cited": cited}
