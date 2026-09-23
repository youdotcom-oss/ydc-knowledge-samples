"""Shared demo tail: optional synthesis, cost, and latency."""

from __future__ import annotations

import argparse
import time

from youdotcom.models import SearchResponse

from utils.rendering import print_costs, print_latency, print_synthesis
from utils.synthesize import synthesize

SEARCH_COST_PER_CALL = 5.00 / 1000  # $5 / 1k calls


def _wants_synthesis() -> bool:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="ask GPT-5.6 Luna (OpenRouter) to summarize results; needs OPENROUTER_API_KEY",
    )
    return parser.parse_args().synthesize


def finish(
    query: str,
    response: SearchResponse,
    *,
    round_trip_s: float,
    synthesize_results: bool | None = None,
) -> None:
    """Print the optional Luna summary and costs, then latency.

    When ``synthesize_results`` is None, it follows the ``--synthesize`` CLI flag.
    """
    if synthesize_results is None:
        synthesize_results = _wants_synthesis()
    synth_s = None
    if synthesize_results:
        print()
        t0 = time.perf_counter()
        text, usage = synthesize(query, response)
        synth_s = time.perf_counter() - t0
        print_synthesis(text)
        print_costs(SEARCH_COST_PER_CALL, usage)
    print_latency(
        you_server_s=response.metadata.latency if response.metadata else None,
        you_round_trip_s=round_trip_s,
        synth_round_trip_s=synth_s,
    )
