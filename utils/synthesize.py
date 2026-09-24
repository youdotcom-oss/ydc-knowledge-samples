"""Synthesize You.com search results with an OpenAI-compatible chat model.

The default is GPT-5.6 Luna on OpenRouter. Pass a Blackbox model id to stream
from ``https://enterprise.blackbox.ai/chat/completions`` instead (``BB_KEY``).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple

import httpx
from youdotcom.models import SearchResponse

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
BLACKBOX_URL = "https://enterprise.blackbox.ai/chat/completions"
MODEL = "openai/gpt-5.6-luna"
MODEL_LABEL = "GPT-5.6 Luna"
DESCRIPTION_LIMIT = 400

# Ids are sent as ``model``. Labels are what the terminal prints.
BLACKBOX_MODELS = {
    "nvidia/nemotron-3-ultra-550b-a55b": "Nemotron 3 Ultra",
    "openai/gpt-oss-120b": "GPT-OSS 120B",
    "minimax/minimax-m3": "MiniMax M3",
    "zai/glm-5.3-flash": "GLM 5.3 Flash",
    "zai/glm-5.3": "GLM 5.3",
    "moonshotai/kimi-k3": "Kimi K3",
    "deepseek/deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
}

_SYSTEM = (
    "Answer the user from the You.com search results only. "
    "Prefer knowledge cards for facts and figures. "
    "Cite source names inline. If the results do not support a "
    "number, say so. Keep it to 1–3 short paragraphs. "
    "Plain terminal text only: no markdown, no bold, no asterisks, no headings."
)


class Synthesis(NamedTuple):
    text: str
    usage: dict
    label: str


def backend_for(model: str | None) -> tuple[str, str, str]:
    """Return ``(backend, model id, label)``.

    ``backend`` is ``openrouter`` or ``blackbox``.
    """
    if model is None or model == MODEL:
        return "openrouter", MODEL, MODEL_LABEL
    label = BLACKBOX_MODELS.get(model)
    if label is None:
        known = ", ".join((MODEL, *BLACKBOX_MODELS))
        raise ValueError(f"unknown model {model!r}; choose from {known}")
    return "blackbox", model, label


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("Missing OPENROUTER_API_KEY. Copy .env.example to .env.")
    return key


def blackbox_key() -> str:
    key = os.environ.get("BB_KEY")
    if not key:
        sys.exit("Missing BB_KEY. Copy .env.example to .env.")
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


def _messages(query: str, evidence: dict) -> list[dict]:
    payload = json.dumps(evidence, ensure_ascii=False)
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Query: {query}\n\nResults:\n{payload}"},
    ]


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            chunks.append(str(part.get("text") or ""))
    return "".join(chunks)


def _sse_data(raw: str) -> str | None:
    line = raw.strip()
    if not line or line.startswith(":"):
        return None
    if line.startswith("data:"):
        line = line[5:].strip()
    return line or None


def read_chat_stream(lines: Iterable[str]) -> tuple[str, dict]:
    """Collect assistant text and usage from an OpenAI-style server-sent stream."""
    parts: list[str] = []
    usage: dict = {}
    for raw in lines:
        payload = _sse_data(raw)
        if payload is None:
            continue
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        error = event.get("error")
        if error:
            message = error.get("message") if isinstance(error, dict) else error
            raise ValueError(str(message or error))
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        for choice in event.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or choice.get("message") or {}
            if isinstance(delta, dict):
                parts.append(_content_text(delta.get("content")))
    return _squeeze("".join(parts)), usage


def blackbox_body(model: str, messages: list[dict]) -> dict:
    """JSON body for ``POST /chat/completions`` with streaming on."""
    return {"model": model, "messages": messages, "stream": True}


def _post_openrouter(model: str, messages: list[dict]) -> tuple[str, dict]:
    reply = httpx.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "HTTP-Referer": "https://github.com/youdotcom-oss/ydc-knowledge-samples",
            "X-OpenRouter-Title": "You.com Knowledge demos",
        },
        json={"model": model, "temperature": 0.2, "messages": messages},
        timeout=60.0,
    )
    if reply.is_error:
        sys.exit(f"OpenRouter HTTP {reply.status_code}: {reply.text}")
    body = reply.json()
    choices = body.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    text = _squeeze(_content_text(message.get("content")))
    if not text:
        sys.exit(f"OpenRouter returned no synthesis: {json.dumps(body)[:500]}")
    return text, body.get("usage") or {}


def _post_blackbox(model: str, messages: list[dict]) -> tuple[str, dict]:
    with httpx.Client(timeout=120.0) as client:
        with client.stream(
            "POST",
            BLACKBOX_URL,
            headers={
                "Authorization": f"Bearer {blackbox_key()}",
                "Content-Type": "application/json",
            },
            json=blackbox_body(model, messages),
        ) as reply:
            if reply.is_error:
                detail = reply.read().decode(errors="replace")
                sys.exit(f"Blackbox HTTP {reply.status_code}: {detail[:500]}")
            return read_chat_stream(reply.iter_lines())


def synthesize(
    query: str,
    response: SearchResponse,
    *,
    model: str | None = None,
) -> Synthesis:
    backend, model_id, label = backend_for(model)
    messages = _messages(query, compact_results(response))
    try:
        if backend == "blackbox":
            text, usage = _post_blackbox(model_id, messages)
        else:
            text, usage = _post_openrouter(model_id, messages)
    except ValueError as exc:
        sys.exit(f"{label} synthesis failed: {exc}")
    if not text:
        sys.exit(f"{label} returned no synthesis.")
    return Synthesis(text, usage, label)
