"""Grading with FinSearchComp's rubric, which ends with ``{"answer_score": 0|1}``."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from openai import AsyncOpenAI

from benchmarks import config

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SCORE_RE = re.compile(r'"answer_score"\s*:\s*([01])')


@lru_cache(maxsize=1)
def rubric() -> tuple[str, str]:
    """(system_prompt, prompt_template), with ``config.JUDGE_NORMALIZATION_RULE``
    appended to the system prompt."""
    return (
        (PROMPTS_DIR / "judge_system_prompt.txt").read_text() + config.JUDGE_NORMALIZATION_RULE,
        (PROMPTS_DIR / "judge_prompt_template.txt").read_text(),
    )


def build_prompt(question: str, expected: str, answer: str) -> str:
    _system, template = rubric()
    return template.format(prompt=question, response_reference=expected, response=answer)


async def grade(
    client: AsyncOpenAI | None, question: str, expected: str | None, answer: str | None
) -> tuple[float | None, str | None]:
    """``(score, verdict)``. Score is None with no reference or an unreadable
    verdict, so an ungraded row is never counted as wrong."""
    if not expected:
        return None, None
    if not answer:
        return 0.0, "empty answer"

    system, _template = rubric()
    response = await client.responses.create(
        model=config.JUDGE_MODEL,
        instructions=system,
        input=build_prompt(question, expected, answer),
        reasoning={"effort": config.JUDGE_REASONING_EFFORT},
    )
    verdict = response.output_text
    match = SCORE_RE.search(verdict)
    if match:
        return float(match.group(1)), verdict
    print(f"  unparseable judge verdict: {verdict[-160:]!r}")
    return None, verdict


def make_client(api_key: str | None = None) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
