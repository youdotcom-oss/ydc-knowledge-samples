"""POST helper for https://ydc-index.io/v1/search with knowledge=core."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

SEARCH_URL = "https://ydc-index.io/v1/search"


def _load_dotenv() -> None:
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if not candidate.is_file():
            continue
        for raw in candidate.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))
        return


def api_key() -> str:
    _load_dotenv()
    key = os.environ.get("YOU_API_KEY") or os.environ.get("YDC_API_KEY")
    if not key:
        sys.exit("Missing YOU_API_KEY (or YDC_API_KEY). Copy .env.example to .env.")
    return key


def search(query: str, count: int = 5, knowledge: str = "core") -> dict:
    response = httpx.post(
        SEARCH_URL,
        headers={"X-API-Key": api_key()},
        json={"query": query, "count": count, "knowledge": knowledge},
        timeout=30.0,
    )
    if response.is_error:
        sys.exit(f"HTTP {response.status_code}: {response.text}")
    return response.json()


def print_results(payload: dict) -> None:
    results = payload.get("results") or {}
    print(json.dumps(results.get("knowledge") or [], indent=2, ensure_ascii=False))
    web = results.get("web") or []
    if web:
        print("\n--- first web hit ---")
        print(json.dumps(web[0], indent=2, ensure_ascii=False))


def run(query: str) -> None:
    print(f"query: {query}\n")
    print_results(search(query))
