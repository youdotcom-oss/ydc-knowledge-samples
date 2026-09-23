"""Paste queries in a loop. Search-only by default; --synthesize or /synth for Luna."""

from __future__ import annotations

import argparse
import sys
import time

from youdotcom import You
from youdotcom.errors import YouError

from utils.client import finish
from utils.rendering import print_query, print_results


def _prompt(synth: bool) -> str:
    mode = "synth on" if synth else "search only"
    return f"query ({mode})> "


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive You.com Knowledge search. Empty line or Ctrl-D to quit."
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="GPT-5.6 Luna summary on every query (needs OPENROUTER_API_KEY)",
    )
    args = parser.parse_args()
    synth = args.synthesize

    print("Paste a query and press enter. /synth toggles Luna. /quit exits.\n")
    with You() as you:  # reads YDC_API_KEY from the environment
        _loop(you, synth)


def _loop(you: You, synth: bool) -> None:
    while True:
        try:
            raw = input(_prompt(synth))
        except (EOFError, KeyboardInterrupt):
            print()
            return
        query = raw.strip()
        if not query:
            continue
        lowered = query.lower()
        if lowered in {"/quit", "/exit", "quit", "exit"}:
            return
        if lowered in {"/synth", "/synthesize"}:
            synth = not synth
            print("synthesis on" if synth else "synthesis off")
            continue
        print()
        print_query(query)
        start = time.perf_counter()
        try:
            response = you.search(query=query, count=5, knowledge="core")
        except YouError as exc:
            print(f"search failed: {exc}\n")
            continue
        round_trip_s = time.perf_counter() - start
        print_results(response)
        finish(query, response, round_trip_s=round_trip_s, synthesize_results=synth)
        print()


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
