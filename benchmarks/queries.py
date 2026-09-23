"""Load the questions to benchmark.

Braintrust-style JSONL, one record per line:

    {"id": "q1", "input": "question", "expected": "reference answer", "metadata": {...}}

Only ``input`` is required; rows without ``expected`` run but aren't graded.
With no file, the default is VerticalRTK fast, fetched at a pinned commit.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from benchmarks import config

VERTICALRTK_REPO = "TakoData/VerticalRTK"
VERTICALRTK_PATH = "data/verticalrtk_fast.jsonl"
# Upstream answers change over time; scores are only comparable at the same commit.
VERTICALRTK_REF = "ae470841aef53080bfeb87add5704278198114ef"

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
_SHA_RE = re.compile(r"[0-9a-f]{40}")


class QueryFileError(ValueError):
    pass


@dataclass
class QuerySet:
    name: str
    rows: list[dict[str, Any]]
    source: dict[str, Any]
    blocklist: tuple[str, ...] = field(default_factory=tuple)

    @property
    def n_graded(self) -> int:
        return sum(1 for r in self.rows if r["expected"])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_records(text: str, *, where: str) -> list[dict[str, Any]]:
    """Braintrust-style JSONL into ``{id, input, expected, metadata}`` rows."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise QueryFileError(f"{where}:{n}: not valid JSON ({exc.msg})") from None
        if not isinstance(rec, dict):
            raise QueryFileError(f"{where}:{n}: each line must be a JSON object")
        question = rec.get("input")
        if not isinstance(question, str) or not question.strip():
            raise QueryFileError(f"{where}:{n}: `input` must be a non-empty string")
        expected = rec.get("expected")
        if expected is not None and not isinstance(expected, str):
            raise QueryFileError(f"{where}:{n}: `expected` must be a string or omitted")
        metadata = rec.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise QueryFileError(f"{where}:{n}: `metadata` must be an object")
        row_id = str(rec["id"]) if rec.get("id") is not None else f"row-{n:04d}"
        if row_id in seen:
            raise QueryFileError(f"{where}:{n}: duplicate id {row_id!r}")
        seen.add(row_id)
        rows.append(
            {
                "id": row_id,
                "input": question.strip(),
                "expected": (expected or "").strip() or None,
                "metadata": metadata,
            }
        )
    if not rows:
        raise QueryFileError(f"{where}: no records")
    return rows


def from_verticalrtk(text: str) -> str:
    """VerticalRTK rows as Braintrust-style JSONL, text unchanged."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        out.append(
            json.dumps(
                {
                    "id": r["id"],
                    "input": r["query"],
                    "expected": r["answer"],
                    "metadata": {"vertical": r.get("vertical"), "as_of": r.get("as_of")},
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(out)


def verticalrtk_url(ref: str) -> str:
    return f"https://raw.githubusercontent.com/{VERTICALRTK_REPO}/{ref}/{VERTICALRTK_PATH}"


def fetch_verticalrtk(ref: str = VERTICALRTK_REF) -> bytes:
    """The upstream file at ``ref``, cached only when ``ref`` is a commit SHA."""
    pinned = bool(_SHA_RE.fullmatch(ref))
    cached = CACHE_DIR / f"verticalrtk_fast-{ref}.jsonl"
    if pinned and cached.is_file():
        return cached.read_bytes()
    r = httpx.get(verticalrtk_url(ref), timeout=60.0, follow_redirects=True)
    r.raise_for_status()
    if pinned:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(r.content)
    return r.content


def load_verticalrtk(ref: str = VERTICALRTK_REF) -> QuerySet:
    data = fetch_verticalrtk(ref)
    url = verticalrtk_url(ref)
    return QuerySet(
        name="verticalrtk_fast",
        rows=parse_records(from_verticalrtk(data.decode()), where=url),
        source={
            "name": "verticalrtk_fast",
            "repo": f"https://github.com/{VERTICALRTK_REPO}",
            "url": url,
            "ref": ref,
            "sha256": _sha256(data),
            "license": "CC BY 4.0",
        },
        blocklist=config.VERTICALRTK_BLOCKLIST,
    )


def load_file(path: str | Path) -> QuerySet:
    p = Path(path)
    if p.suffix != ".jsonl":
        raise QueryFileError(f"{p}: expected a .jsonl file")
    data = p.read_bytes()
    rows = parse_records(data.decode(), where=str(p))
    # An edited copy of VerticalRTK still needs its answer key filtered out.
    is_vrtk = any(r["id"].startswith("vrtk_") for r in rows)
    return QuerySet(
        name=p.stem,
        rows=rows,
        source={"name": p.stem, "path": str(p), "sha256": _sha256(data)},
        blocklist=config.VERTICALRTK_BLOCKLIST if is_vrtk else (),
    )


def load(
    path: str | None = None, *, ref: str = VERTICALRTK_REF, limit: int | None = None
) -> QuerySet:
    qs = load_file(path) if path else load_verticalrtk(ref)
    if limit:
        qs.rows = qs.rows[:limit]
    qs.source["n_rows"] = len(qs.rows)
    qs.source["n_graded"] = qs.n_graded
    return qs


def export(qs: QuerySet, path: str | Path) -> Path:
    """Write ``qs`` as Braintrust-style JSONL that ``load_file`` reads back."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as fh:
        for r in qs.rows:
            rec = {"id": r["id"], "input": r["input"], "expected": r["expected"]}
            if r["metadata"]:
                rec["metadata"] = r["metadata"]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return p
