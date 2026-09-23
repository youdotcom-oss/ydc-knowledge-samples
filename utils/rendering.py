"""Terminal rendering for search results, Luna synthesis, and TCO."""

from __future__ import annotations

import re
import shutil
import sys
import textwrap
from datetime import datetime

from youdotcom.models import KnowledgeResult, SearchResponse

from utils.synthesize import MODEL_LABEL, cost_usd

MAX_WIDTH = 100
DESCRIPTION_LIMIT = 320


def width() -> int:
    return min(shutil.get_terminal_size((80, 24)).columns, MAX_WIDTH)


def _style(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def _squeeze(text: str) -> str:
    return " ".join((text or "").split())


def _trim(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    clean = _squeeze(text)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip(" ,.;:-") + "…"


def _wrap(text: str, cols: int, indent: str = "") -> str:
    return textwrap.fill(text, width=cols, initial_indent=indent, subsequent_indent=indent)


def _section(label: str, cols: int, count: int | None = None) -> None:
    title = f"{label} ({count})" if count is not None else label
    bar = "─" * max(cols - len(title) - 5, 3)
    print(_style(f"─── {title} {bar}", "1;36"))


def _date(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return _squeeze(value or "").split("T")[0]


def _usd(amount: float) -> str:
    if amount >= 0.01:
        return f"${amount:.4f}"
    return f"${amount:.6f}"


METRIC_LABEL_WIDTH = 20


def _metric(label: str, value: str, note: str = "", *, bold: bool = False) -> None:
    line = f"  {label:<{METRIC_LABEL_WIDTH}} {value}"
    if note:
        line += f"   {note}"
    print(_style(line, "1") if bold else line)


def print_query(query: str) -> None:
    print(f"{_style('query:', '1')} {query}\n")


def _print_knowledge(cards: list[KnowledgeResult], cols: int) -> None:
    for index, card in enumerate(cards, start=1):
        print(f"{index}. {_style(_squeeze(card.title or 'Untitled'), '1')}")
        meta = [name for a in card.attribution if (name := _squeeze(a.name))]
        if as_of := _date(card.as_of):
            meta.append(f"as of {as_of}")
        if meta:
            print(_style(_wrap(" · ".join(meta), cols, "   "), "2"))
        if description := _squeeze(card.description or ""):
            print(_wrap(description, cols, "   "))
        print()


def _print_links(items: list, cols: int, show_date: bool = False) -> None:
    for index, item in enumerate(items, start=1):
        print(f"{index}. {_style(_squeeze(item.title or 'Untitled'), '1')}")
        print(_style(f"   {_squeeze(item.url or '')}", "4;34"))
        if show_date and (published := _date(item.page_age)):
            print(_style(f"   {published}", "2"))
        if description := _trim(item.description or ""):
            print(_wrap(description, cols, "   "))
        print()


def print_results(response: SearchResponse) -> None:
    results = response.results
    cols = width()
    knowledge = (results.knowledge if results else None) or []
    web = (results.web if results else None) or []
    news = (results.news if results else None) or []

    if not (knowledge or web or news):
        print("No results.")
        return

    _section("KNOWLEDGE", cols, len(knowledge))
    print()
    if knowledge:
        _print_knowledge(knowledge, cols)
    else:
        print(_style("   no knowledge cards for this query\n", "2"))

    for label, items in (("WEB", web), ("NEWS", news)):
        if not items:
            continue
        _section(label, cols, len(items))
        print()
        _print_links(items, cols, show_date=label == "NEWS")


def _plain(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    return text


def print_synthesis(text: str) -> None:
    cols = width()
    _section(f"SYNTHESIS · {MODEL_LABEL}", cols)
    print()
    print(_wrap(_plain(text), cols))
    print()


def print_costs(search_cost: float, usage: dict) -> None:
    cols = width()
    llm_cost = cost_usd(usage)
    tco = search_cost + llm_cost
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    _section("COST", cols)
    print()
    _metric("You.com Search", _usd(search_cost), "1 call @ $5 / 1k")
    tokens = ""
    if prompt is not None and completion is not None:
        tokens = f"{prompt} in / {completion} out"
    _metric(MODEL_LABEL, _usd(llm_cost), tokens)
    _metric("Total TCO", _usd(tco), bold=True)
    print()


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:8.0f} ms"


def print_latency(
    *,
    you_server_s: float | None,
    you_round_trip_s: float,
    synth_round_trip_s: float | None,
) -> None:
    cols = width()
    _section("LATENCY", cols)
    print()
    server = _ms(you_server_s) if you_server_s is not None else "       —"
    _metric("You.com server", server)
    total = you_round_trip_s
    if synth_round_trip_s is not None:
        _metric(MODEL_LABEL, _ms(synth_round_trip_s))
        total += synth_round_trip_s
    _metric("Total e2e", _ms(total), bold=True)
    print()
