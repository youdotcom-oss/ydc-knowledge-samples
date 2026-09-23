"""The Stirrup agent, wired to one search provider."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from functools import partial
from typing import Annotated, Any

from anyio import to_thread
from pydantic import BaseModel, Field
from stirrup import (
    Agent,
    AssistantMessage,
    Tool,
    ToolResult,
    ToolUseCountMetadata,
    aggregate_metadata,
    final_text,
)
from stirrup.clients.open_responses_client import OpenResponsesClient
from stirrup.utils.logging import AgentLoggerBase
from stirrup.utils.text import truncate_msg

from benchmarks import config
from benchmarks.providers import SearchResponse, run_search


class WebSearchParams(BaseModel):
    """Query-only, so no provider can win by exposing filters another lacks."""

    query: Annotated[str, Field(description=config.QUERY_DESCRIPTION)]


class SearchMetadata(BaseModel):
    """Per-call bookkeeping; Stirrup sums these per question via ``__add__``."""

    num_uses: int = 1
    refused: int = 0
    n_results: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    errors: int = 0
    queries: list[str] = Field(default_factory=list)
    counters: dict[str, int] = Field(default_factory=dict)

    def __add__(self, other: SearchMetadata) -> SearchMetadata:
        merged = dict(self.counters)
        for k, v in other.counters.items():
            merged[k] = merged.get(k, 0) + v
        return SearchMetadata(
            num_uses=self.num_uses + other.num_uses,
            refused=self.refused + other.refused,
            n_results=self.n_results + other.n_results,
            cost_usd=self.cost_usd + other.cost_usd,
            latency_ms=self.latency_ms + other.latency_ms,
            errors=self.errors + other.errors,
            queries=self.queries + other.queries,
            counters=merged,
        )


class FinalAnswer(BaseModel):
    answer: Annotated[
        str,
        Field(
            description=(
                "The final answer, stated directly. Include the specific value, name, or "
                "date asked for, with units and the period the figure covers."
            )
        ),
    ]
    reason: Annotated[str, Field(description="Brief justification citing your sources.")]


async def _finish(params: FinalAnswer) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=params.answer, metadata=ToolUseCountMetadata(), success=True)


# Stirrup's default finish tool returns file paths; this one returns the answer.
FINISH_TOOL = Tool[FinalAnswer, ToolUseCountMetadata](
    name="submit_answer",
    description="Submit your final answer and finish.",
    parameters=FinalAnswer,
    executor=_finish,
)


def _search_entry(query: str, result: SearchResponse) -> dict[str, Any]:
    results = result.raw.get("results") or {}
    return {
        "query": query,
        "ok": True,
        "latency_ms": result.latency_ms,
        "server_latency_ms": result.counters.get("server_latency_ms"),
        "knowledge": [
            {
                "title": c.get("title"),
                "attribution": [a.get("name") for a in c.get("attribution") or []],
                "as_of": c.get("as_of"),
                "description": c.get("description"),
            }
            for c in results.get("knowledge") or []
        ],
        "web": [
            {
                "title": w.get("title"),
                "url": w.get("url"),
                "highlights": (w.get("contents") or {}).get("highlights") or [],
            }
            for w in results.get("web") or []
        ],
    }


def build_web_search_tool(
    provider: str,
    blocklist: Iterable[str] = (),
    max_searches: int | None = None,
    max_result_chars: int = config.MAX_SEARCH_RESULT_CHARS,
    exclude_domains: Iterable[str] = (),
    search: Callable[..., SearchResponse] = run_search,
    log: list[dict[str, Any]] | None = None,
) -> Tool:
    """The search tool for one question. ``max_searches`` is a per-question
    budget, so build a fresh tool for each question. ``log`` receives one entry
    per call."""
    used = 0
    failed = 0
    max_failures = 3

    async def executor(params: WebSearchParams) -> ToolResult[SearchMetadata]:
        nonlocal used, failed
        if failed >= max_failures:
            return ToolResult(
                content=(
                    f"Search is failing ({failed} consecutive errors). "
                    "Answer from the results you already have."
                ),
                success=False,
                metadata=SearchMetadata(num_uses=0, refused=1),
            )
        if max_searches is not None and used >= max_searches:
            return ToolResult(
                content=(
                    f"Search budget exhausted ({max_searches} allowed). "
                    "Answer from the results you already have."
                ),
                success=False,
                metadata=SearchMetadata(num_uses=0, refused=1),
            )
        try:
            result = await to_thread.run_sync(
                partial(
                    search,
                    provider,
                    params.query,
                    count=config.MAX_SEARCH_RESULTS,
                    blocklist=blocklist,
                    exclude_domains=exclude_domains,
                ),
                abandon_on_cancel=True,
            )
        except Exception as exc:
            # A failed search doesn't count against the budget; `max_failures`
            # stops a dead provider from looping.
            failed += 1
            if log is not None:
                log.append({"query": params.query, "ok": False, "error": str(exc)})
            return ToolResult(
                content=f"<error>{exc}</error>",
                success=False,
                metadata=SearchMetadata(queries=[params.query], errors=1),
            )

        used += 1
        failed = 0
        if log is not None:
            log.append(_search_entry(params.query, result))
        return ToolResult(
            content=truncate_msg(result.content, max_result_chars) or "No results found.",
            metadata=SearchMetadata(
                n_results=result.n_results,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
                queries=[params.query],
                counters=dict(result.counters),
            ),
        )

    return Tool[WebSearchParams, SearchMetadata](
        name="web_search",
        description=(
            "Search the live web. Use specific, keyword-rich queries with named entities, "
            "dates, and identifiers. Call this multiple times in parallel in one turn when "
            "independent sub-questions need separate queries."
        ),
        parameters=WebSearchParams,
        executor=executor,
    )


def build_agent(
    provider: str,
    blocklist: Iterable[str] = (),
    max_searches: int | None = None,
    *,
    max_result_chars: int = config.MAX_SEARCH_RESULT_CHARS,
    exclude_domains: Iterable[str] = (),
    search: Callable[..., SearchResponse] = run_search,
    log: list[dict[str, Any]] | None = None,
    api_key: str | None = None,
    verbose: bool = False,
) -> Agent:
    """Responses API, not Chat Completions: gpt-5.6-luna rejects function tools
    combined with ``reasoning_effort`` on /v1/chat/completions.

    ``tools`` must be explicit; Stirrup substitutes its own defaults when None.
    """
    return Agent(
        client=OpenResponsesClient(
            model=config.CANDIDATE_MODEL,
            max_tokens=config.MAX_OUTPUT_TOKENS,
            context_window_tokens=config.CONTEXT_WINDOW_TOKENS,
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            reasoning_effort=config.REASONING_EFFORT,
            timeout=config.MODEL_TIMEOUT_SECONDS,
            kwargs={} if config.TEMPERATURE is None else {"temperature": config.TEMPERATURE},
        ),
        name=f"knowledge_benchmark_{provider}",
        max_turns=config.MAX_TURNS,
        system_prompt=config.system_prompt(),
        tools=[
            build_web_search_tool(
                provider,
                blocklist,
                max_searches,
                max_result_chars,
                exclude_domains,
                search,
                log,
            )
        ],
        finish_tool=FINISH_TOOL,
        logger=None if verbose else QuietLogger(),
    )


class QuietLogger(AgentLoggerBase):
    """Drops Stirrup's per-turn output; warnings and errors still reach logging."""

    _log = logging.getLogger("stirrup")

    def __init__(self) -> None:
        # Read by Agent before it assigns them, so they need defaults.
        self.name = "agent"
        self.model = None
        self.max_turns = None
        self.depth = 0
        self.finish_params = None
        self.run_metadata = None
        self.output_dir = None

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def on_step(self, *args: Any, **kwargs: Any) -> None: ...
    def assistant_message(self, *args: Any, **kwargs: Any) -> None: ...
    def user_message(self, *args: Any, **kwargs: Any) -> None: ...
    def task_message(self, *args: Any, **kwargs: Any) -> None: ...
    def tool_result(self, *args: Any, **kwargs: Any) -> None: ...
    def context_summarization_start(self, *args: Any, **kwargs: Any) -> None: ...
    def context_summarization_complete(self, *args: Any, **kwargs: Any) -> None: ...
    def debug(self, message: str, *args: object) -> None: ...
    def info(self, message: str, *args: object) -> None: ...

    def warning(self, message: str, *args: object) -> None:
        self._log.warning(message, *args)

    def error(self, message: str, *args: object) -> None:
        self._log.error(message, *args)


def _unwrap(value: Any) -> dict[str, Any]:
    """aggregate_metadata wraps token_usage in a single-element list."""
    if isinstance(value, list):
        value = value[0] if value else None
    return value or {}


def _last_text(history: list[list[Any]]) -> str | None:
    for group in reversed(history):
        for msg in reversed(group):
            if isinstance(msg, AssistantMessage) and (t := final_text(msg.content)):
                return t
    return None


URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def cited_urls(text: str | None, searches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """URLs written into the answer, each flagged by whether a search returned it."""
    returned = {(w.get("url") or "").rstrip("/") for s in searches for w in s.get("web") or []}
    out, seen = [], set()
    for url in URL_RE.findall(text or ""):
        url = url.rstrip(".,;:").rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "returned_by_search": url in returned})
    return out


def sources(searches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every distinct knowledge card and web result the agent was shown, in order."""
    out, seen = [], set()
    for s in searches:
        for c in s.get("knowledge") or []:
            key = ("knowledge", c.get("title"))
            if key not in seen:
                seen.add(key)
                out.append(
                    {
                        "type": "knowledge",
                        "title": c.get("title"),
                        "attribution": c.get("attribution"),
                        "as_of": c.get("as_of"),
                    }
                )
        for w in s.get("web") or []:
            key = ("web", w.get("url"))
            if key not in seen:
                seen.add(key)
                out.append({"type": "web", "title": w.get("title"), "url": w.get("url")})
    return out


def costs(input_tokens: int, output_tokens: int, search_cost_usd: float) -> dict[str, float]:
    synthesis = config.synthesis_cost_usd(input_tokens, output_tokens)
    return {
        "search_cost_usd": search_cost_usd,
        "synthesis_cost_usd": synthesis,
        "tco_usd": search_cost_usd + synthesis,
    }


async def run_question(
    query: str,
    provider: str,
    blocklist: Iterable[str] = (),
    max_searches: int | None = None,
    exclude_domains: Iterable[str] = (),
    verbose: bool = False,
) -> dict[str, Any]:
    """Run one question through one provider. Returns a JSON-serializable record."""
    searches: list[dict[str, Any]] = []
    agent = build_agent(
        provider,
        blocklist,
        max_searches,
        exclude_domains=exclude_domains,
        log=searches,
        verbose=verbose,
    )
    started = time.monotonic()
    async with agent.session() as session:
        finish, history, meta = await session.run(query)
    total_time_s = time.monotonic() - started

    totals = aggregate_metadata(meta)
    usage = _unwrap(totals.get("token_usage"))
    search = _unwrap(totals.get("web_search"))
    speed = meta.get("_model_speed") or {}
    answer = finish.answer if finish else _last_text(history)
    reason = finish.reason if finish else None
    server_ms = [s["server_latency_ms"] for s in searches if s.get("server_latency_ms") is not None]
    input_tokens = usage.get("input", 0)
    answer_tokens = usage.get("answer", 0)
    reasoning_tokens = usage.get("reasoning", 0)

    return {
        "provider": provider,
        "answer": answer,
        "reason": reason,
        # False: the agent ran out of turns; any answer was taken from the transcript.
        "finished": finish is not None,
        "model": config.CANDIDATE_MODEL,
        "search_budget": max_searches,
        "input_tokens": input_tokens,
        "answer_tokens": answer_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_time_s": total_time_s,
        "model_time_s": float(speed.get("duration", 0.0)),
        "search_time_s": sum(meta.get("_tool_durations", {}).get("web_search", [])),
        "model_calls": int(speed.get("num_calls", 0)),
        "search_calls": search.get("num_uses", 0),
        "search_refused": search.get("refused", 0),
        "search_errors": search.get("errors", 0),
        **costs(input_tokens, answer_tokens + reasoning_tokens, search.get("cost_usd", 0.0)),
        "search_counters": search.get("counters", {}),
        "server_latency_ms": server_ms,
        "cited_urls": cited_urls(f"{answer or ''}\n{reason or ''}", searches),
        "sources": sources(searches),
        "searches": searches,
    }
