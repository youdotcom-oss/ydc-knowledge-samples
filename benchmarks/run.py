"""Benchmark search providers with the Stirrup agent harness.

    uv run --group bench python -m benchmarks.run --preflight
    uv run --group bench python -m benchmarks.run --limit 5
    uv run --group bench python -m benchmarks.run --provider you_knowledge
    uv run --group bench python -m benchmarks.run --queries benchmarks/example_queries.jsonl

With no --queries, runs Tako's VerticalRTK fast set at a pinned commit. With more
than one --provider, each runs on the same questions and the results are compared.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from benchmarks import config, outputs, queries
from benchmarks.agent import run_question
from benchmarks.judge import grade, make_client
from benchmarks.providers import DEFAULT_PROVIDERS, PROVIDERS, run_search

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def receipt(args, qs: queries.QuerySet, excluded: tuple[str, ...]) -> None:
    budget = "unlimited" if args.search_budget is None else args.search_budget
    src = qs.source.get("url") or qs.source.get("path")
    print("\n" + "=" * 68)
    arms = ", ".join(f"{p} ({PROVIDERS[p].exclusion})" for p in args.provider)
    print(f"PROVIDERS  {arms}")
    print(f"QUERIES    {qs.name}: {len(qs.rows)} rows, {qs.n_graded} with an expected answer")
    print(f"           {src}")
    print(f"BUDGET     {budget} searches per question")
    print(f"EXCLUDE    {args.exclude_domains} ({len(excluded)} domains)")
    print(f"BLOCKLIST  {list(qs.blocklist) or 'none'}")
    print(f"MODELS     agent {config.CANDIDATE_MODEL}, judge {config.JUDGE_MODEL}")
    print("=" * 68)


def preflight(provider: str, exclude_domains: tuple[str, ...] = ()) -> bool:
    """One live search before a full run. A provider that can't authenticate
    doesn't crash the run; it scores like weak search, so catch it here."""
    ok = True
    if not os.getenv("OPENAI_API_KEY"):
        print("[FAIL] OPENAI_API_KEY is not set (needed for the agent and the judge)")
        ok = False
    key = PROVIDERS[provider].api_key_env
    if key and not os.getenv(key):
        print(f"[FAIL] {provider:16} {key} is not set")
        return False
    try:
        r = run_search(
            provider,
            "current US federal funds rate",
            count=config.MAX_SEARCH_RESULTS,
            exclude_domains=exclude_domains,
        )
        if not r.content.strip():
            raise RuntimeError("authenticated but returned no content")
        print(
            f"[PASS] {provider:16} results={r.n_results} cost=${r.cost_usd:.4f} "
            f"latency={r.latency_ms}ms {r.counters}"
        )
        if "knowledge_card_count" in r.counters and not r.counters["knowledge_card_count"]:
            print(
                "       WARNING: no knowledge results returned. This key may not be "
                "provisioned for Knowledge, in which case this run is measuring "
                "plain web search."
            )
    except Exception as exc:
        ok = False
        print(f"[FAIL] {provider:16} {type(exc).__name__}: {exc}")
    return ok


async def main_async(args) -> int:
    excluded = config.DOMAIN_EXCLUSIONS[args.exclude_domains]
    qs = queries.load(args.queries, ref=args.queries_ref, limit=args.limit)

    receipt(args, qs, excluded)
    if args.dry_run:
        print("\nNothing has run. Re-invoke without --dry-run to spend.")
        return 0
    passed = [preflight(p, excluded) for p in args.provider]
    if args.preflight:
        return 0 if all(passed) else 1
    if not all(passed):
        print("\nPre-flight failed; a broken provider would score as weak search. Aborting.")
        return 1

    root = outputs.run_dir(Path(args.out_dir), qs.name)
    client = make_client()
    runs = {}
    for provider in args.provider:
        runs[provider] = await run_arm(args, provider, qs, excluded, root / provider, client)

    if len(runs) > 1:
        text, table = outputs.compare(qs.rows, runs)
        outputs.write_comparison(root / "comparison.csv", table)
        print(f"\n{text}")
    print(f"\nwrote {root}/")
    return 0


async def run_arm(
    args, provider: str, qs: queries.QuerySet, excluded: tuple[str, ...], out: Path, client
) -> list[dict[str, Any]]:
    manifest = outputs.build_manifest(
        provider=provider,
        exclusion_mechanism=PROVIDERS[provider].exclusion,
        queries=qs.source,
        search_budget=args.search_budget,
        exclude_domains_name=args.exclude_domains,
        exclude_domains=excluded,
        blocklist=qs.blocklist,
        concurrency=args.concurrency,
    )
    writer = outputs.RunWriter(out, manifest)
    sem = asyncio.Semaphore(args.concurrency)
    done = 0

    async def one(row: dict[str, Any]) -> dict[str, Any]:
        nonlocal done
        base = {
            "id": row["id"],
            "input": row["input"],
            "expected": row["expected"],
            "metadata": row["metadata"],
        }
        async with sem:
            try:
                rec = await run_question(
                    row["input"],
                    provider,
                    qs.blocklist,
                    args.search_budget,
                    exclude_domains=excluded,
                    verbose=args.verbose,
                )
                rec["grade"], rec["verdict"] = await grade(
                    client, row["input"], row["expected"], rec["answer"]
                )
                rec = {**base, **rec}
            except Exception as exc:
                # Keep the failed row, so it stays in the denominator.
                rec = {**base, "grade": None, "error": f"{type(exc).__name__}: {exc}"}
        writer.append(rec)
        done += 1
        g = rec.get("grade")
        mark = "error" if rec.get("error") else ("-" if g is None else int(g))
        print(f"  [{done}/{len(qs.rows)}] {provider} {row['id']}: {mark}")
        return rec

    print(f"\nrunning {provider} on {len(qs.rows)} questions -> {out}")
    # return_exceptions=True so one escaped row can't cancel the others.
    settled = await asyncio.gather(*(one(r) for r in qs.rows), return_exceptions=True)
    records = [r for r in settled if not isinstance(r, BaseException)]

    t = outputs.totals(records)
    writer.close(t)
    print(f"\n=== {provider} on {qs.name} ===")
    print(outputs.report(t))
    return records


def export(args) -> int:
    qs = queries.load(args.queries, ref=args.queries_ref, limit=args.limit)
    path = queries.export(qs, args.export_queries)
    print(f"wrote {len(qs.rows)} rows ({qs.n_graded} with an expected answer) to {path}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--queries",
        help="Braintrust-style JSONL: one {input, expected?, id?, metadata?} per line. "
        "Default: VerticalRTK fast from GitHub",
    )
    p.add_argument(
        "--queries-ref",
        default=queries.VERTICALRTK_REF,
        help="VerticalRTK commit or branch to fetch (default: the pinned commit)",
    )
    p.add_argument("--limit", type=int, help="first N questions only")
    p.add_argument(
        "--provider",
        nargs="+",
        default=list(DEFAULT_PROVIDERS),
        choices=list(PROVIDERS),
        help="one or more providers; with two or more, the first is compared to the rest "
        f"(default: {' '.join(DEFAULT_PROVIDERS)})",
    )
    p.add_argument(
        "--search-budget",
        type=int,
        default=config.DEFAULT_SEARCH_BUDGET,
        help="searches allowed per question; 0 means unlimited",
    )
    p.add_argument(
        "--exclude-domains",
        default="answer_farms",
        choices=list(config.DOMAIN_EXCLUSIONS),
        help="domain set withheld from the provider; 'none' disables",
    )
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--out-dir", default=str(RESULTS_DIR))
    p.add_argument("--preflight", action="store_true", help="check keys and provider, then exit")
    p.add_argument(
        "--dry-run", action="store_true", help="print what would run, then exit without spending"
    )
    p.add_argument(
        "--export-queries",
        metavar="PATH",
        help="write the question set as editable JSONL, then exit",
    )
    p.add_argument(
        "--show",
        nargs="?",
        const="",
        metavar="ID",
        help="print each provider's answer, knowledge cards and web highlights for one "
        "question, or for every question they graded differently, then exit",
    )
    p.add_argument("--run", help="results folder for --show (default: the latest)")
    p.add_argument("--verbose", action="store_true", help="show Stirrup's per-turn agent log")
    args = p.parse_args()
    args.provider = list(dict.fromkeys(args.provider))
    if args.search_budget <= 0:
        args.search_budget = None
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.export_queries:
        raise SystemExit(export(args))
    if args.show is not None:
        run = Path(args.run) if args.run else outputs.latest_run(Path(args.out_dir))
        if run is None:
            raise SystemExit(f"no results under {args.out_dir}; run `make bench` first")
        print(outputs.show(run, args.show or None))
        raise SystemExit(0)

    import utils  # noqa: F401  loads .env and checks YDC_API_KEY

    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
