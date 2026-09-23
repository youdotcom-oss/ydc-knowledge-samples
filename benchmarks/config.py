"""Constants held fixed across providers, so that search is the only variable.

https://artificialanalysis.ai/methodology/search-api
"""

from __future__ import annotations

from datetime import UTC, date, datetime

CANDIDATE_MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 127_999
CONTEXT_WINDOW_TOKENS = 1_050_000
MAX_TURNS = 25
MAX_SEARCH_RESULTS = 10
MODEL_TIMEOUT_SECONDS = 600.0

# gpt-5.6-luna rejects `temperature`, so AA's documented 0.6 can't apply.
TEMPERATURE: float | None = None

MAX_SEARCH_RESULT_CHARS = 40_000

JUDGE_MODEL = "gpt-5.6-luna"
JUDGE_REASONING_EFFORT = "medium"

DEFAULT_SEARCH_BUDGET = 1

# OpenAI list price for CANDIDATE_MODEL, USD per 1M tokens (standard tier, short
# context). Stirrup doesn't report cached input, so all input is billed uncached.
PRICE_PER_1M = {"input": 0.20, "output": 1.20}

SYSTEM_PROMPT = (
    "You answer questions using a web_search tool backed by a live search API.\n\n"
    "Search when the answer depends on real-time data, recent events, or specific facts "
    "you are not confident about. Prefer searching over guessing for numbers, names, and "
    "dates. Issue independent sub-questions as parallel web_search calls in the same turn "
    "rather than searching serially.\n\n"
    "Ground every factual claim in the results you retrieved; do not invent. Only search "
    "again if the results you have do not contain the answer.\n\n"
    "When you have the answer, call the finish tool with it. A partial or uncertain answer "
    "is more useful than none."
)

# Unused by the search arms, but hashed into agent_prompt_sha; editing it changes the hash.
NO_TOOL_SYSTEM_PROMPT = (
    "You answer questions from your own knowledge. You have no tools and no web access.\n\n"
    "When you have the answer, call the finish tool with it. If you are not confident, give "
    "your best current estimate -- a partial or uncertain answer is more useful than none."
)

QUERY_DESCRIPTION = (
    "Concise keyword query, 3-6 words. ALLOWED search operators: "
    '`"exact phrase"`, `intitle:term`, `inbody:term`, `-term`, `+term`, and `AND`/`OR` '
    "(MUST be uppercase; never mix `AND` with `OR`). DO NOT use `site:`, `lang:`, `loc:`, "
    "`filetype:`, `ext:`, `inpage:`, or `NOT`."
)


def system_prompt(today: date | None = None) -> str:
    """SYSTEM_PROMPT with today's date prepended, so "latest" means now."""
    day = today or datetime.now(UTC).date()
    return f"Today's date is {day:%Y-%m-%d} ({day:%A}).\n\n" + SYSTEM_PROMPT


# Appended to FinSearchComp's judge system prompt at run time, so the files in
# prompts/ stay byte-identical to the published rubric.
JUDGE_NORMALIZATION_RULE = (
    "\n\nAdditional rule on numeric form. Compare the numerical value, not its "
    "written form. A <Student Answer> matches the <Reference Answer> when the two "
    "denote the same quantity after accounting for:\n"
    "- Scale words and separators: 2,313.4 million == 2313436000 == 2.3134 billion.\n"
    "- Currency symbols and codes for the same currency: MXN 2,313.4 million == "
    "MX$2,313,436,000.\n"
    "- Rounding of the reference to fewer significant figures: a <Student Answer> "
    "of 115.567 billion matches a <Reference Answer> of 115.6B, because 115.567 "
    "rounds to 115.6 at the reference's stated precision.\n"
    "This is not a tolerance band. Two values that differ once both are expressed "
    "at the same scale and the reference's own precision do NOT match: 96.1 does "
    "not match 96.2, and 1,398 does not match 1,382. Where the <Reference Answer> "
    "states an explicit acceptable range, apply that range as written."
)

# Passed to each provider's own exclusion parameter, so every provider still
# returns the full result count.
DOMAIN_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "answer_farms": (
        "ainvest.com",
        "chegg.com",
        "cdn3.f-cdn.com",
        "coursehero.com",
        "scribd.com",
        "quizlet.com",
        "homework.study.com",
        "numerade.com",
        "askfilo.com",
        "studocu.com",
        "bartleby.com",
        "transtutors.com",
        "vaia.com",
        "doubtnut.com",
        "brainly.com",
        "cliffsnotes.com",
        "coursesidekick.com",
        "collegesidekick.com",
        "nursinghero.com",
    ),
    "none": (),
}

# VerticalRTK's answer key is public on GitHub; drop results that point at it.
VERTICALRTK_BLOCKLIST: tuple[str, ...] = ("verticalrtk", "takodata")


def synthesis_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * PRICE_PER_1M["input"] + output_tokens * PRICE_PER_1M["output"]
    ) / 1_000_000
