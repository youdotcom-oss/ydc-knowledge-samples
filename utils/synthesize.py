"""Synthesize You.com search results with GPT-5.6 Luna via OpenRouter."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import httpx
from youdotcom.models import SearchResponse

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-5.6-luna"
MODEL_LABEL = "GPT-5.6 Luna"
DESCRIPTION_LIMIT = 400


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Missing OPENROUTER_API_KEY. Copy .env.example to .env.")
    return key


def cost_usd(usage: dict) -> float:
    """Billed credits, or upstream inference cost when the key is BYOK (credits are 0)."""
    cost = float(usage.get("cost") or 0)
    if cost:
        return cost
    details = usage.get("cost_details") or {}
    return float(details.get("upstream_inference_cost") or 0)


def _squeeze(text: str) -> str:
    return " ".join((text or "").split())


def _trim(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    clean = _squeeze(text)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip(" ,.;:-") + "…"


def _page_age(value: datetime | str | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def compact_results(response: SearchResponse) -> dict:
    results = response.results

    def links(items) -> list[dict]:
        return [
            {
                "title": item.title,
                "url": item.url,
                "page_age": _page_age(item.page_age),
                "description": _trim(item.description or ""),
            }
            for item in items or []
        ]

    knowledge = [
        {
            "title": card.title,
            "as_of": card.as_of,
            "description": card.description,
            "attribution": [a.name for a in card.attribution if a.name],
        }
        for card in (results.knowledge if results else None) or []
    ]
    return {
        "knowledge": knowledge,
        "web": links(results.web if results else None),
        "news": links(results.news if results else None),
    }


def synthesize(query: str, response: SearchResponse) -> tuple[str, dict]:
    evidence = compact_results(response)
    reply = httpx.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "HTTP-Referer": "https://github.com/youdotcom-oss/ydc-knowledge-samples",
            "X-OpenRouter-Title": "You.com Knowledge demos",
        },
        json={
            "model": MODEL,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer the user from the You.com search results only. "
                        "Prefer knowledge cards for facts and figures. "
                        "Cite source names inline. If the results do not support a "
                        "number, say so. Keep it to 1–3 short paragraphs. "
                        "Plain terminal text only: no markdown, no bold, no asterisks, no headings."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Query: {query}\n\nResults:\n"
                        f"{json.dumps(evidence, ensure_ascii=False)}"
                    ),
                },
            ],
        },
        timeout=60.0,
    )
    if reply.is_error:
        sys.exit(f"OpenRouter HTTP {reply.status_code}: {reply.text}")
    body = reply.json()
    choices = body.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    text = _squeeze(message.get("content") or "")
    if not text:
        sys.exit(f"OpenRouter returned no synthesis: {json.dumps(body)[:500]}")
    return text, body.get("usage") or {}
