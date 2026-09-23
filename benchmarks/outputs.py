"""The run folder: summary.csv, details.jsonl and manifest.json per provider, and
comparison.csv when more than one provider ran.

Rows are written as they finish, so a run stopped halfway keeps what it paid for.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics as st
import subprocess
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from benchmarks import config, judge

MANIFEST_SCHEMA = 1

SUMMARY_FIELDS = (
    "id",
    "input",
    "expected",
    "answer",
    "grade",
    "searches",
    "knowledge_cards",
    "search_time_s",
    "model_time_s",
    "total_time_s",
    "search_cost_usd",
    "tco_usd",
    "finished",
    "error",
)


def run_dir(base: Path, dataset: str, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", dataset).strip("-") or "queries"
    return base / f"{stamp}-{slug}"


def build_manifest(
    *,
    provider: str,
    exclusion_mechanism: str,
    queries: dict[str, Any],
    search_budget: int | None,
    exclude_domains_name: str,
    exclude_domains: Sequence[str],
    blocklist: Sequence[str],
    concurrency: int,
    max_result_chars: int = config.MAX_SEARCH_RESULT_CHARS,
) -> dict[str, Any]:
    """manifest.json: every setting that changes the numbers."""
    return {
        "schema": MANIFEST_SCHEMA,
        "started_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": provider,
        "exclusion_mechanism": exclusion_mechanism,
        "queries": queries,
        "search_budget": search_budget,
        "exclude_domains_name": exclude_domains_name,
        "exclude_domains_count": len(exclude_domains),
        "exclude_domains": list(exclude_domains),
        "blocklist": list(blocklist),
        "concurrency": concurrency,
        "candidate_model": config.CANDIDATE_MODEL,
        "reasoning_effort": config.REASONING_EFFORT,
        "judge_model": config.JUDGE_MODEL,
        "judge_reasoning_effort": config.JUDGE_REASONING_EFFORT,
        "max_search_results": config.MAX_SEARCH_RESULTS,
        "price_per_1m_tokens": dict(config.PRICE_PER_1M),
        "agent_prompt_sha": prompt_sha(
            config.SYSTEM_PROMPT,
            config.NO_TOOL_SYSTEM_PROMPT,
            config.QUERY_DESCRIPTION,
        ),
        "judge_prompt_sha": prompt_sha(*judge.rubric()),
        "agent_knows_date": True,
        "max_result_chars": max_result_chars,
        "harness": "stirrup",
        "stirrup_version": _version("stirrup"),
        "youdotcom_version": _version("youdotcom"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "python": sys.version.split()[0],
    }


def prompt_sha(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode())
        h.update(b"\x00")
    return h.hexdigest()[:12]


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ("git", *args),
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def _version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def summary_row(rec: dict[str, Any]) -> dict[str, Any]:
    grade = rec.get("grade")
    return {
        "id": rec["id"],
        "input": rec["input"],
        "expected": rec.get("expected") or "",
        "answer": rec.get("answer") or "",
        "grade": "" if grade is None else int(grade),
        "searches": rec.get("search_calls", 0),
        "knowledge_cards": (rec.get("search_counters") or {}).get("knowledge_card_count", 0),
        "search_time_s": round(rec.get("search_time_s", 0.0), 2),
        "model_time_s": round(rec.get("model_time_s", 0.0), 2),
        "total_time_s": round(rec.get("total_time_s", 0.0), 2),
        "search_cost_usd": round(rec.get("search_cost_usd", 0.0), 6),
        "tco_usd": round(rec.get("tco_usd", 0.0), 6),
        "finished": rec.get("finished", False),
        "error": rec.get("error") or "",
    }


class RunWriter:
    def __init__(self, path: Path, manifest: dict[str, Any]):
        self.path = path
        self.manifest = manifest
        self.n = 0
        path.mkdir(parents=True, exist_ok=True)
        self._write_manifest()
        self._details = (path / "details.jsonl").open("w")
        self._summary_fh = (path / "summary.csv").open("w", newline="")
        self._summary = csv.DictWriter(self._summary_fh, fieldnames=SUMMARY_FIELDS)
        self._summary.writeheader()

    def _write_manifest(self) -> None:
        (self.path / "manifest.json").write_text(json.dumps(self.manifest, indent=2) + "\n")

    def append(self, rec: dict[str, Any]) -> None:
        self._details.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self._details.flush()
        self._summary.writerow(summary_row(rec))
        self._summary_fh.flush()
        self.n += 1

    def close(self, totals: dict[str, Any]) -> None:
        self._details.close()
        self._summary_fh.close()
        self.manifest["totals"] = totals
        self._write_manifest()


def totals(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    graded = [r["grade"] for r in records if r.get("grade") is not None]
    ok = [r for r in records if not r.get("error")]
    server = [ms for r in ok for ms in r.get("server_latency_ms") or []]

    def mean(key: str, digits: int = 4) -> float:
        vals = [r.get(key, 0) or 0 for r in ok]
        return round(st.mean(vals), digits) if vals else 0.0

    def total(key: str) -> float:
        return round(sum(r.get(key, 0) or 0 for r in ok), 4)

    return {
        "questions": len(records),
        "graded": len(graded),
        "correct": int(sum(graded)),
        "accuracy": round(st.mean(graded), 4) if graded else None,
        "errored": len(records) - len(ok),
        "unfinished": sum(1 for r in ok if not r.get("finished")),
        "searches_per_question": mean("search_calls"),
        "server_latency_ms_p50": int(st.median(server)) if server else None,
        "server_latency_ms_mean": int(st.mean(server)) if server else None,
        "search_time_s_per_question": mean("search_time_s"),
        "model_time_s_per_question": mean("model_time_s"),
        "total_time_s_per_question": mean("total_time_s"),
        "search_cost_usd_per_question": mean("search_cost_usd", 6),
        "synthesis_cost_usd_per_question": mean("synthesis_cost_usd", 6),
        "tco_usd_per_question": mean("tco_usd", 6),
        "search_cost_usd_total": total("search_cost_usd"),
        "tco_usd_total": total("tco_usd"),
        "search_errors": sum(r.get("search_errors", 0) for r in ok),
        "search_refused": sum(r.get("search_refused", 0) for r in ok),
    }


def report(t: dict[str, Any]) -> str:
    lines = [f"  questions        {t['questions']}"]
    if t["graded"]:
        lines.append(
            f"  accuracy         {t['accuracy']:.3f}  "
            f"({t['correct']} correct of {t['graded']} graded / {t['questions']} total)"
        )
    else:
        lines.append("  accuracy         n/a (no rows have an `expected` answer)")
    if t["server_latency_ms_p50"] is not None:
        lines.append(
            f"  query time       p50 {t['server_latency_ms_p50']} ms server-side, "
            f"mean {t['server_latency_ms_mean']} ms"
        )
    lines += [
        f"  total time       {t['total_time_s_per_question']:.1f}s per question "
        f"(search {t['search_time_s_per_question']:.1f}s, "
        f"model {t['model_time_s_per_question']:.1f}s)",
        f"  query cost       ${t['search_cost_usd_per_question']:.5f} per question",
        f"  TCO              ${t['tco_usd_per_question']:.5f} per question "
        f"(synthesis ${t['synthesis_cost_usd_per_question']:.5f}), "
        f"${t['tco_usd_total']:.4f} total",
        f"  searches         {t['searches_per_question']:.1f} per question",
    ]
    if t["search_refused"]:
        lines.append(f"  hit the cap      {t['search_refused']} refused searches")
    if t["errored"] or t["unfinished"] or t["search_errors"]:
        lines.append(
            f"  problems         {t['errored']} rows errored, {t['unfinished']} unfinished, "
            f"{t['search_errors']} failed searches"
        )
    return "\n".join(lines)


def compare(
    rows: list[dict[str, Any]], runs: dict[str, list[dict[str, Any]]]
) -> tuple[str, list[dict[str, Any]]]:
    """Side-by-side report of two or more providers on the same questions, and one
    row per question for comparison.csv. The first provider is the reference."""
    names = list(runs)
    ref, others = names[0], names[1:]
    by_id = {n: {r["id"]: r for r in recs} for n, recs in runs.items()}

    def grade(name: str, qid: str) -> float | None:
        return by_id[name].get(qid, {}).get("grade")

    graded = [r for r in rows if all(grade(n, r["id"]) is not None for n in names)]
    groups: dict[str, list[dict[str, Any]]] = {"all": graded}
    for r in graded:
        if vertical := r["metadata"].get("vertical"):
            groups.setdefault(vertical, []).append(r)

    col = max(12, *(len(n) for n in names))
    label = 22

    def line(name: str, cells: Iterable[str]) -> str:
        return f"  {name:<{label}}" + "".join(f"{c:>{col + 2}}" for c in cells)

    out = [
        f"=== {' vs '.join(names)}: {len(graded)} questions graded by every provider ===",
        line("", names),
    ]
    for group, qs in groups.items():
        cells = [f"{sum(grade(n, r['id']) for r in qs) / len(qs):.1%}" for n in names]
        out.append(line(f"{group} ({len(qs)})", cells))

    t = {n: totals(recs) for n, recs in runs.items()}

    def p50(n: str) -> str:
        ms = t[n]["server_latency_ms_p50"]
        return "-" if ms is None else f"{ms / 1000:.2f}s"

    out += [
        line("query time (p50)", [p50(n) for n in names]),
        line("total time", [f"{t[n]['total_time_s_per_question']:.1f}s" for n in names]),
        line("query cost", [f"${t[n]['search_cost_usd_per_question']:.5f}" for n in names]),
        line("TCO", [f"${t[n]['tco_usd_per_question']:.5f}" for n in names]),
    ]

    for other in others:
        for a, b in ((ref, other), (other, ref)):
            won = [r for r in graded if grade(a, r["id"]) == 1 and grade(b, r["id"]) == 0]
            out.append(f"\n  right with {a}, wrong with {b}: {len(won)}")
            out += [f"    {r['id']}  {_clip(r['input'], 80)}" for r in won]

    table = []
    for r in rows:
        row = {
            "id": r["id"],
            "input": r["input"],
            "expected": r["expected"] or "",
            "vertical": r["metadata"].get("vertical") or "",
        }
        for n in names:
            rec = by_id[n].get(r["id"], {})
            g = rec.get("grade")
            row[f"{n}_grade"] = "" if g is None else int(g)
            row[f"{n}_answer"] = rec.get("answer") or rec.get("error") or ""
        table.append(row)
    return "\n".join(out), table


def write_comparison(path: Path, table: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0]) if table else ["id"])
        w.writeheader()
        w.writerows(table)


def latest_run(base: Path) -> Path | None:
    runs = sorted(d for d in base.glob("*") if d.is_dir() and any(d.glob("*/details.jsonl")))
    return runs[-1] if runs else None


def show(run: Path, qid: str | None = None, max_web: int = 5) -> str:
    """Each provider's answer, grade, knowledge cards and web highlights for one
    question, or for every question the providers graded differently."""
    arms: dict[str, dict[str, dict[str, Any]]] = {}
    for d in sorted(run.glob("*/details.jsonl")):
        with d.open() as fh:
            arms[d.parent.name] = {r["id"]: r for r in map(json.loads, fh)}
    if not arms:
        return f"no provider results under {run}"

    ids = list(next(iter(arms.values())))
    if qid:
        if not any(qid in recs for recs in arms.values()):
            return f"{qid} is not in {run}"
        ids = [qid]
    else:
        ids = [i for i in ids if len({recs.get(i, {}).get("grade") for recs in arms.values()}) > 1]
        if not ids:
            return f"every provider got the same grade on every question in {run}"

    out: list[str] = []
    for i in ids:
        first = next(recs[i] for recs in arms.values() if i in recs)
        out += ["=" * 80, f"{i}  {first['input']}", f"expected: {first.get('expected') or '-'}"]
        for name, recs in arms.items():
            rec = recs.get(i)
            if rec is None:
                continue
            g = rec.get("grade")
            out += ["", f"--- {name}   grade {'-' if g is None else int(g)}"]
            out.append(f"answer: {_clip(rec.get('answer') or rec.get('error') or '', 300)}")
            for s in rec.get("searches") or []:
                out.append(f'search: "{s.get("query")}"')
                for c in s.get("knowledge") or []:
                    meta = " · ".join([*(c.get("attribution") or []), f"as of {c.get('as_of')}"])
                    out.append(f"  [knowledge] {c.get('title')}  ({meta})")
                    out.append(f"      {_clip(c.get('description') or '', 300)}")
                web = s.get("web") or []
                for w in web[:max_web]:
                    out.append(f"  [web] {w.get('title')}  {w.get('url')}")
                    if hl := w.get("highlights"):
                        out.append(f"      {_clip(hl[0], 200)}")
                if len(web) > max_web:
                    out.append(f"  ... {len(web) - max_web} more web results in details.jsonl")
    return "\n".join(out)


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"
