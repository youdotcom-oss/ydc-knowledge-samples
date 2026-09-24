"""Shared demo tail: optional synthesis, cost, and latency."""

from __future__ import annotations

import time

from youdotcom.models import SearchResponse

from utils.rendering import print_costs, print_latency, print_synthesis
from utils.synthesize import synthesize

SEARCH_COST_PER_CALL = 5.00 / 1000  # $5 / 1k calls


def finish(
    query: str,
    response: SearchResponse,
    *,
    round_trip_s: float,
    synthesize_results: bool = False,
    model: str | None = None,
) -> None:
    """Print the optional synthesis, costs, and latency."""
    synth_s = None
    label = None
    if synthesize_results:
        print()
        t0 = time.perf_counter()
        result = synthesize(query, response, model=model)
        synth_s = time.perf_counter() - t0
        label = result.label
        print_synthesis(result.text, label=label)
        print_costs(SEARCH_COST_PER_CALL, result.usage, label=label)
    print_latency(
        you_server_s=response.metadata.latency if response.metadata else None,
        you_round_trip_s=round_trip_s,
        synth_round_trip_s=synth_s,
        synth_label=label or "",
    )
