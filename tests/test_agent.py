"""The search tool, wired to a stand-in provider via ``search=``, plus the agent's
fixed settings. No network."""

from __future__ import annotations

import anyio
import pytest

from benchmarks import agent, config
from benchmarks.agent import WebSearchParams, build_web_search_tool, cited_urls, sources
from benchmarks.providers import SearchResponse

RAW = {
    "results": {
        "web": [
            {"url": "https://www.sec.gov/x", "title": "Filing", "contents": {"highlights": ["h"]}}
        ],
        "knowledge": [
            {
                "title": "Card",
                "attribution": [{"name": "BIS"}],
                "as_of": "2026-09-22",
                "description": "d",
            }
        ],
    }
}


class TestSearchTool:
    def _run(self, tool, q="q"):
        return anyio.run(tool.executor, WebSearchParams(query=q))

    def _tool(self, response=None, exc=None, fail_first=0, **kwargs):
        """``fail_first`` raises on the first N calls, then succeeds."""
        calls = {"n": 0}

        def provider(name, query, *, count, blocklist=(), exclude_domains=()):
            calls["n"] += 1
            if exc or calls["n"] <= fail_first:
                raise exc or RuntimeError("429 Too Many Requests")
            return response

        self.calls = calls
        return build_web_search_tool("you_knowledge", search=provider, **kwargs)

    def test_provider_content_and_cost_pass_through(self):
        tool = self._tool(SearchResponse(content="a number", cost_usd=0.005, n_results=10))
        r = self._run(tool)
        assert r.success and "a number" in r.content
        assert r.metadata.cost_usd == pytest.approx(0.005)

    def test_provider_error_is_reported_not_raised(self):
        r = self._run(self._tool(exc=RuntimeError("503 upstream")))
        assert r.success is False and r.metadata.errors == 1

    def test_empty_results_say_so_rather_than_sending_an_empty_turn(self):
        r = self._run(self._tool(SearchResponse(content="")))
        assert "no results" in r.content.lower()

    def test_budget_refuses_once_spent(self):
        tool = self._tool(SearchResponse(content="hit"), max_searches=2)
        assert self._run(tool).success and self._run(tool).success
        third = self._run(tool)
        assert third.success is False and "budget exhausted" in third.content.lower()

    def test_refusal_counts_apart_from_use_and_error(self):
        tool = self._tool(SearchResponse(content="hit"), max_searches=1)
        used, refused = self._run(tool).metadata, self._run(tool).metadata
        assert (used.num_uses, used.refused, used.errors) == (1, 0, 0)
        assert (refused.num_uses, refused.refused, refused.errors) == (0, 1, 0)

    def test_result_payload_is_capped_before_entering_context(self):
        tool = self._tool(SearchResponse(content="x" * 5000), max_result_chars=200)
        assert len(self._run(tool).content) < 5000

    def test_a_failed_search_does_not_consume_budget(self):
        tool = self._tool(SearchResponse(content="hit"), fail_first=1, max_searches=1)
        first = self._run(tool)
        assert first.success is False and first.metadata.errors == 1
        second = self._run(tool)
        assert second.success is True, "budget was charged for a failed search"
        assert "hit" in second.content

    def test_repeated_failures_stop_rather_than_refunding_forever(self):
        tool = self._tool(exc=RuntimeError("503"), max_searches=1)
        for _ in range(3):
            assert self._run(tool).metadata.errors == 1
        stopped = self._run(tool)
        assert stopped.success is False
        assert stopped.metadata.refused == 1 and stopped.metadata.errors == 0
        assert self.calls["n"] == 3, "kept calling a provider that always fails"

    def test_a_success_resets_the_failure_streak(self):
        tool = self._tool(SearchResponse(content="hit"), fail_first=2, max_searches=5)
        assert self._run(tool).metadata.errors == 1
        assert self._run(tool).metadata.errors == 1
        assert self._run(tool).success is True
        assert self._run(tool).success is True

    def test_metadata_sums_via_addable(self):
        M = agent.SearchMetadata
        total = M(n_results=10, cost_usd=0.005, counters={"a": 7}) + M(
            n_results=8, errors=1, counters={"a": 4, "b": 1}
        )
        assert (total.num_uses, total.n_results, total.errors) == (2, 18, 1)
        assert total.counters == {"a": 11, "b": 1}


class TestSearchLog:
    def _tool(self, log, response=None, exc=None):
        def provider(name, query, *, count, blocklist=(), exclude_domains=()):
            if exc:
                raise exc
            return response

        return build_web_search_tool("you_knowledge", search=provider, log=log, max_searches=1)

    def test_success_records_query_cards_and_web_results(self):
        log: list = []
        resp = SearchResponse(
            content="c", latency_ms=120, counters={"server_latency_ms": 90}, raw=RAW
        )
        anyio.run(self._tool(log, resp).executor, WebSearchParams(query="fed rate"))
        (entry,) = log
        assert entry["query"] == "fed rate" and entry["ok"] is True
        assert (entry["latency_ms"], entry["server_latency_ms"]) == (120, 90)
        assert entry["knowledge"][0] == {
            "title": "Card",
            "attribution": ["BIS"],
            "as_of": "2026-09-22",
            "description": "d",
        }
        assert entry["web"][0] == {
            "title": "Filing",
            "url": "https://www.sec.gov/x",
            "highlights": ["h"],
        }

    def test_failure_records_the_error(self):
        log: list = []
        anyio.run(self._tool(log, exc=RuntimeError("503")).executor, WebSearchParams(query="q"))
        assert log == [{"query": "q", "ok": False, "error": "503"}]

    def test_refusal_is_not_logged_as_a_search(self):
        log: list = []
        tool = self._tool(log, SearchResponse(content="c", raw=RAW))
        anyio.run(tool.executor, WebSearchParams(query="a"))
        anyio.run(tool.executor, WebSearchParams(query="b"))
        assert [e["query"] for e in log] == ["a"]


class TestCitedUrls:
    SEARCHES = [{"web": [{"url": "https://www.sec.gov/x"}]}]

    def test_flags_urls_the_search_returned(self):
        got = cited_urls("Per https://www.sec.gov/x, and https://other.com/y.", self.SEARCHES)
        assert got == [
            {"url": "https://www.sec.gov/x", "returned_by_search": True},
            {"url": "https://other.com/y", "returned_by_search": False},
        ]

    def test_markdown_links_and_duplicates(self):
        got = cited_urls("[SEC](https://www.sec.gov/x) (https://www.sec.gov/x/)", self.SEARCHES)
        assert got == [{"url": "https://www.sec.gov/x", "returned_by_search": True}]

    def test_no_text(self):
        assert cited_urls(None, self.SEARCHES) == []


class TestSources:
    def test_cards_and_web_results_deduplicated_in_order(self):
        searches = [
            {"knowledge": [{"title": "Card", "attribution": ["BIS"], "as_of": "2026"}], "web": []},
            {
                "knowledge": [{"title": "Card", "attribution": ["BIS"], "as_of": "2026"}],
                "web": [{"title": "A", "url": "https://a.example"}],
            },
            {"ok": False, "error": "503"},
        ]
        assert sources(searches) == [
            {"type": "knowledge", "title": "Card", "attribution": ["BIS"], "as_of": "2026"},
            {"type": "web", "title": "A", "url": "https://a.example"},
        ]


class TestCosts:
    def test_tco_is_search_plus_synthesis(self):
        c = agent.costs(input_tokens=10_000, output_tokens=1_000, search_cost_usd=0.005)
        assert c["synthesis_cost_usd"] == pytest.approx(0.0032)
        assert c["tco_usd"] == pytest.approx(0.0082)


class TestAgent:
    def test_gets_exactly_one_tool(self):
        a = agent.build_agent("you_knowledge", api_key="sk-test")
        assert [t.name for t in a._tools] == ["web_search"]

    def test_quiet_by_default(self):
        assert isinstance(
            agent.build_agent("you_knowledge", api_key="sk-test").logger, agent.QuietLogger
        )
        verbose = agent.build_agent("you_knowledge", api_key="sk-test", verbose=True)
        assert not isinstance(verbose.logger, agent.QuietLogger)

    def test_model_is_called_on_openai_directly(self):
        client = agent.build_agent("you_knowledge", api_key="sk-test")._client
        assert client.model_slug == "gpt-5.6-luna"
        assert str(client._client.base_url).startswith("https://api.openai.com/v1")

    def test_quiet_logger_has_what_agent_reads(self):
        q = agent.QuietLogger()
        assert (q.depth, q.name, q.model, q.max_turns) == (0, "agent", None, None)
        assert (q.finish_params, q.run_metadata, q.output_dir) == (None, None, None)

    def test_finish_tool_returns_an_answer(self):
        assert agent.FINISH_TOOL.name == "submit_answer"
        assert set(agent.FinalAnswer.model_fields) == {"answer", "reason"}

    def test_constants_are_pinned(self):
        a = agent.build_agent("you_knowledge", api_key="sk-test")
        assert a._max_turns == config.MAX_TURNS == 25
        assert config.MAX_SEARCH_RESULTS == 10
        assert config.TEMPERATURE is None
