"""The launch-post queries: one You.com Search call each, with knowledge="core"."""

from __future__ import annotations

import argparse
import sys
import time

from youdotcom import You
from youdotcom.errors import YouError

from utils.client import finish
from utils.rendering import print_query, print_results
from utils.synthesize import BLACKBOX_MODELS, MODEL, backend_for

QUERIES = {
    "big-mac": "What's the Big Mac Index for Japan versus the US?",
    "nvidia": "What's Nvidia's stock price?",
    "weather": "What's the weather in Boise, Idaho?",
    "bitcoin": "What's the BTC to USD price right now?",
    "nasa": "How much did NASA pay out in federal contract outlays in FY2025?",
}


def search(you: You, query: str, synthesize: bool, model: str | None) -> None:
    print_query(query)
    start = time.perf_counter()
    response = you.search(query=query, count=5, knowledge="core")
    round_trip_s = time.perf_counter() - start
    print_results(response)
    finish(
        query,
        response,
        round_trip_s=round_trip_s,
        synthesize_results=synthesize,
        model=model,
    )


def interactive(you: You, synthesize: bool, model: str | None) -> None:
    print("Paste a query and press enter. /synth toggles synthesis. /quit exits.\n")
    while True:
        mode = "synth on" if synthesize else "search only"
        try:
            query = input(f"query ({mode})> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not query:
            continue
        if query.lower() in {"/quit", "/exit", "quit", "exit"}:
            return
        if query.lower() in {"/synth", "/synthesize"}:
            synthesize = not synthesize
            print("synthesis on" if synthesize else "synthesis off")
            continue
        print()
        try:
            search(you, query, synthesize, model)
        except YouError as exc:
            print(f"search failed: {exc}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "names",
        nargs="*",
        metavar="NAME",
        help=f"any of: {', '.join(QUERIES)} (default: all of them)",
    )
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="paste your own queries in a loop"
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help=f"summarize each result (default {MODEL} via OpenRouter; needs OPENROUTER_API_KEY)",
    )
    parser.add_argument(
        "--model",
        help=(
            "synthesis model. Blackbox models need BB_KEY and are streamed: "
            + ", ".join(BLACKBOX_MODELS)
        ),
    )
    args = parser.parse_args()
    if args.model:
        args.synthesize = True
    try:
        backend_for(args.model)
    except ValueError as exc:
        parser.error(str(exc))
    unknown = [name for name in args.names if name not in QUERIES]
    if unknown:
        parser.error(f"unknown demo {unknown[0]!r}; choose from {', '.join(QUERIES)}")

    with You() as you:  # reads YDC_API_KEY from the environment
        if args.interactive:
            interactive(you, args.synthesize, args.model)
            return
        for name in args.names or QUERIES:
            search(you, QUERIES[name], args.synthesize, args.model)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
