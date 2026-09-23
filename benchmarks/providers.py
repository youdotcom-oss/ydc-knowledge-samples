"""Search providers the benchmark can run. See benchmarks/README.md to add one."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from youdotcom import You

# How a provider withholds `exclude_domains`; recorded in the manifest.
EXCLUSION_API = "api_parameter"  # withheld at retrieval, full result count kept
EXCLUSION_QUERY = "query_operator"  # `-site:` in the query -- advisory only
EXCLUSION_NONE = "unsupported"  # endpoint exposes no exclusion at all


@dataclass(slots=True)
class SearchResponse:
    """``content`` is what the agent reads. ``raw`` is the provider's full
    response, kept for the details file and never shown to the agent."""

    content: str
    cost_usd: float = 0.0
    n_results: int = 0
    latency_ms: int = 0
    counters: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class SearchFn(Protocol):
    def __call__(
        self,
        query: str,
        *,
        count: int,
        blocklist: Iterable[str] = (),
        exclude_domains: Iterable[str] = (),
    ) -> SearchResponse: ...


@dataclass(frozen=True, slots=True)
class Provider:
    search: SearchFn
    api_key_env: str
    exclusion: str


YOU_COST_PER_SEARCH = 0.005  # $5 / 1k calls
YOU_TIMEOUT_MS = 60_000


def you_search(
    query: str,
    *,
    count: int,
    blocklist: Iterable[str] = (),
    exclude_domains: Iterable[str] = (),
    knowledge: bool = True,
    client: httpx.Client | None = None,
    api_key: str | None = None,
) -> SearchResponse:
    """You.com Search in highlights mode. ``knowledge=True`` sends
    ``knowledge="core"``. A key not provisioned for Knowledge gets plain web
    results back, so check ``knowledge_card_count``.

    ``client`` and ``api_key`` are for tests; by default the SDK reads
    YDC_API_KEY from the environment.
    """
    excluded = list(exclude_domains)
    started = time.monotonic()
    with You(api_key_auth=api_key, client=client) as you:
        response = you.search(
            query=query,
            count=count,
            extraction={"extraction_mode": "highlights"},
            knowledge="core" if knowledge else None,
            exclude_domains=excluded or None,
            # None sends no `language` field; omitting it would send the SDK's "en".
            language=None,
            timeout_ms=YOU_TIMEOUT_MS,
        )
    latency_ms = round((time.monotonic() - started) * 1000)
    payload: dict[str, Any] = response.model_dump(mode="json", by_alias=True)
    results = payload.get("results") or {}

    web, dropped = filter_blocked(results.get("web") or [], blocklist)

    blocks, with_highlights = [], 0
    for res in web:
        hl = (res.get("contents") or {}).get("highlights") or []
        if hl:
            with_highlights += 1
        blocks.append(
            f"[{res.get('title', '')}]({res.get('url', '')})\n"
            + ("\n".join(hl) or res.get("description", ""))
        )

    server_s = (payload.get("metadata") or {}).get("latency")
    counters = {
        "highlights_success_count": with_highlights,
        "highlights_failure_count": len(web) - with_highlights,
        "contamination_drops": dropped,
        "excluded_domain_hits": excluded_hits(web, excluded),
        **({"server_latency_ms": round(server_s * 1000)} if server_s is not None else {}),
    }

    # Cards go first because the agent truncates the payload from the tail.
    cards = results.get("knowledge") or []
    if knowledge:
        counters["knowledge_card_count"] = len(cards)
    card_blocks: list[str] = []
    for card in cards:
        names = ", ".join(
            a.get("name", "") for a in (card.get("attribution") or []) if isinstance(a, dict)
        )
        lines = [f"[KNOWLEDGE: {card.get('type', '')}] {card.get('title', '')}"]
        if names:
            lines.append(f" attribution: {names}")
        if card.get("as_of"):
            lines.append(f" as_of: {card['as_of']}")
        if card.get("description"):
            lines.append(f" description: {card['description']}")
        card_blocks.append("\n".join(lines))

    return SearchResponse(
        content="\n\n".join(card_blocks + blocks),
        cost_usd=YOU_COST_PER_SEARCH,
        n_results=len(web) + len(cards),
        latency_ms=latency_ms,
        counters=counters,
        raw={**payload, "results": {**results, "web": web}},
    )


PROVIDERS: dict[str, Provider] = {
    "you_knowledge": Provider(
        search=you_search, api_key_env="YDC_API_KEY", exclusion=EXCLUSION_API
    ),
    "you_web": Provider(
        search=partial(you_search, knowledge=False),
        api_key_env="YDC_API_KEY",
        exclusion=EXCLUSION_API,
    ),
}

DEFAULT_PROVIDERS = ("you_knowledge", "you_web")


def run_search(
    name: str,
    query: str,
    *,
    count: int,
    blocklist: Iterable[str] = (),
    exclude_domains: Iterable[str] = (),
) -> SearchResponse:
    try:
        provider = PROVIDERS[name]
    except KeyError:
        raise ValueError(f"Unknown provider '{name}'. Known: {', '.join(PROVIDERS)}") from None
    return with_retry(
        lambda: provider.search(
            query, count=count, blocklist=blocklist, exclude_domains=exclude_domains
        )
    )


def keep(url: str | None, blocklist: Iterable[str]) -> bool:
    lowered = (url or "").lower()
    return not any(p in lowered for p in blocklist)


def filter_blocked(items: list[dict], blocklist: Iterable[str]) -> tuple[list[dict], int]:
    patterns = tuple(blocklist)
    if not patterns:
        return items, 0
    kept = [i for i in items if keep(i.get("url"), patterns)]
    return kept, len(items) - len(kept)


def excluded_hits(items: list[dict], domains: Iterable[str]) -> int:
    """Results from a domain we asked to exclude. Counted, not dropped, so a
    provider that ignores the exclusion keeps its full result count."""
    suffixes = tuple(domains)
    if not suffixes:
        return 0
    hits = 0
    for item in items:
        host = urlparse((item.get("url") or "").lower()).hostname or ""
        if any(host == d or host.endswith(f".{d}") for d in suffixes):
            hits += 1
    return hits


RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY_S = 1.0


def retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUS
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    # SDK errors (e.g. youdotcom.errors.YouError) carry the HTTP status directly.
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status in RETRY_STATUS


def with_retry(
    call: Callable[[], SearchResponse],
    *,
    attempts: int = RETRY_ATTEMPTS,
    base_delay: float = RETRY_BASE_DELAY_S,
):
    """Call a provider, backing off on throttling, timeouts and 5xx. Runs in a
    worker thread, so the blocking sleep doesn't stall the event loop."""
    for attempt in range(attempts):
        try:
            return call()
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            if not retryable(exc) or attempt == attempts - 1:
                raise
            time.sleep(random.uniform(0, base_delay * (2**attempt)))
    raise AssertionError("unreachable")
