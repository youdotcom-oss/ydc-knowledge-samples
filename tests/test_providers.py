"""Offline tests for the search providers. No network: the You.com SDK is driven
through an ``httpx.MockTransport`` that records the request and returns a canned
response."""

from __future__ import annotations

import json

import httpx
import pytest

from benchmarks import config
from benchmarks.providers import (
    DEFAULT_PROVIDERS,
    EXCLUSION_API,
    PROVIDERS,
    filter_blocked,
    retryable,
    run_search,
    with_retry,
    you_search,
)

LEAKS = config.VERTICALRTK_BLOCKLIST

PAYLOAD = {
    "results": {
        "web": [
            {
                "url": "https://www.sec.gov/x",
                "title": "Filing",
                "description": "desc",
                "contents": {"highlights": ["h1", "h2"]},
            },
            {"url": "https://github.com/TakoData/VerticalRTK", "title": "leak", "description": "x"},
            {
                "url": "https://www.example.com/y",
                "title": "No highlights",
                "description": "fallback",
            },
        ],
        "knowledge": [
            {
                "type": "answer",
                "title": "Card",
                "attribution": [{"name": "BIS"}],
                "as_of": "2026-09-22",
                "description": "card body",
            }
        ],
    },
    "metadata": {"latency": 0.91, "query": "q", "search_uuid": "u"},
}


def _search(payload=PAYLOAD, status=200, **kwargs):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = you_search("fed funds rate", count=10, client=client, api_key="test-key", **kwargs)
    return result, seen


KNOWLEDGE_BODY = {
    "query": "fed funds rate",
    "count": 10,
    "extraction": {"extraction_mode": "highlights"},
    "exclude_domains": list(config.DOMAIN_EXCLUSIONS["answer_farms"]),
    "knowledge": "core",
}


class TestYouRequest:
    """The exact request body behind the published numbers."""

    def test_knowledge_body(self):
        _, seen = _search(exclude_domains=config.DOMAIN_EXCLUSIONS["answer_farms"])
        assert json.loads(seen[0].content) == KNOWLEDGE_BODY

    def test_web_body_is_the_knowledge_body_without_knowledge(self):
        _, seen = _search(exclude_domains=config.DOMAIN_EXCLUSIONS["answer_farms"], knowledge=False)
        want = {k: v for k, v in KNOWLEDGE_BODY.items() if k != "knowledge"}
        assert json.loads(seen[0].content) == want

    def test_you_web_is_registered_without_knowledge(self):
        assert PROVIDERS["you_web"].search.keywords == {"knowledge": False}

    def test_no_exclusions_sends_no_field(self):
        _, seen = _search()
        body = json.loads(seen[0].content)
        assert "exclude_domains" not in body
        assert "language" not in body and "crawl_timeout" not in body

    def test_authenticates_with_the_key(self):
        _, seen = _search()
        assert seen[0].url == "https://ydc-index.io/v1/search"
        assert seen[0].headers["x-api-key"] == "test-key"


class TestYouResponse:
    def test_knowledge_cards_come_first_and_are_labeled(self):
        r, _ = _search()
        assert r.content.startswith("[KNOWLEDGE: answer] Card")
        assert "attribution: BIS" in r.content and "as_of: 2026-09-22" in r.content
        assert r.content.index("[KNOWLEDGE") < r.content.index("[Filing]")

    def test_highlights_preferred_description_as_fallback(self):
        r, _ = _search(blocklist=LEAKS)
        assert "h1\nh2" in r.content and "fallback" in r.content
        assert r.counters["highlights_success_count"] == 1
        assert r.counters["highlights_failure_count"] == 1

    def test_blocklisted_results_are_dropped_everywhere(self):
        r, _ = _search(blocklist=LEAKS)
        assert "TakoData" not in r.content
        assert r.counters["contamination_drops"] == 1
        assert all("TakoData" not in w["url"] for w in r.raw["results"]["web"])

    def test_counters_and_cost(self):
        r, _ = _search()
        assert r.counters["knowledge_card_count"] == 1
        assert r.counters["server_latency_ms"] == 910
        assert r.n_results == 4
        assert r.cost_usd == pytest.approx(0.005)

    def test_web_arm_reports_no_knowledge_counter(self):
        r, _ = _search(knowledge=False)
        assert "knowledge_card_count" not in r.counters

    def test_a_throttled_response_is_retryable(self):
        with pytest.raises(Exception) as info:
            _search(payload={"error": "slow down"}, status=429)
        assert retryable(info.value)

    def test_an_auth_failure_is_not_retryable(self):
        with pytest.raises(Exception) as info:
            _search(payload={"error": "bad key"}, status=401)
        assert not retryable(info.value)


class TestContamination:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/TakoData/VerticalRTK",
            "https://raw.githubusercontent.com/TakoData/VerticalRTK/main/data/verticalrtk_fast.jsonl",
            "https://huggingface.co/datasets/takodata/verticalrtk",
        ],
    )
    def test_leak_sources_dropped(self, url):
        assert filter_blocked([{"url": url}], LEAKS) == ([], 1)

    def test_ordinary_source_kept(self):
        kept, dropped = filter_blocked([{"url": "https://www.sec.gov/x"}], LEAKS)
        assert len(kept) == 1 and dropped == 0

    def test_no_blocklist_drops_nothing(self):
        rows = [{"url": "https://github.com/TakoData/VerticalRTK"}]
        assert filter_blocked(rows, ()) == (rows, 0)


class TestRegistry:
    def test_unknown_provider_lists_the_known_ones(self):
        with pytest.raises(ValueError, match="you_knowledge"):
            run_search("nope", "q", count=10)

    def test_default_is_you_with_and_without_knowledge(self):
        assert DEFAULT_PROVIDERS == ("you_knowledge", "you_web")

    def test_every_provider_declares_its_key_and_exclusion(self):
        for name, p in PROVIDERS.items():
            assert p.api_key_env, name
            assert p.exclusion, name
        assert PROVIDERS["you_knowledge"].exclusion == EXCLUSION_API

    def test_answer_farm_exclusions_are_bare_hostnames(self):
        # exclude_domains silently ignores a scheme or path.
        for d in config.DOMAIN_EXCLUSIONS["answer_farms"]:
            assert "/" not in d and ":" not in d, d
        assert config.DOMAIN_EXCLUSIONS["none"] == ()


class TestRetryPolicy:
    """Only the failures worth retrying are retried."""

    def _status(self, code):
        req = httpx.Request("POST", "https://example.invalid/search")
        return httpx.HTTPStatusError(
            "boom", request=req, response=httpx.Response(code, request=req)
        )

    def test_throttling_and_server_errors_are_retryable(self):
        for code in (429, 500, 502, 503, 504, 408):
            assert retryable(self._status(code)), code

    def test_auth_and_bad_request_are_not(self):
        for code in (400, 401, 403, 404, 422):
            assert not retryable(self._status(code)), code

    def test_timeouts_and_transport_errors_are_retryable(self):
        req = httpx.Request("POST", "https://example.invalid/search")
        assert retryable(httpx.ReadTimeout("slow", request=req))
        assert retryable(httpx.ConnectError("refused", request=req))

    def test_a_retryable_failure_is_retried_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise self._status(429)
            return "ok"

        assert with_retry(flaky, attempts=4, base_delay=0) == "ok"
        assert calls["n"] == 3

    def test_a_non_retryable_failure_is_raised_on_the_first_attempt(self):
        calls = {"n": 0}

        def broken():
            calls["n"] += 1
            raise self._status(401)

        with pytest.raises(httpx.HTTPStatusError):
            with_retry(broken, attempts=4, base_delay=0)
        assert calls["n"] == 1

    def test_attempts_are_bounded(self):
        calls = {"n": 0}

        def always_429():
            calls["n"] += 1
            raise self._status(429)

        with pytest.raises(httpx.HTTPStatusError):
            with_retry(always_429, attempts=3, base_delay=0)
        assert calls["n"] == 3
