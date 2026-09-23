"""The run folder: summary.csv, details.jsonl, manifest.json."""

from __future__ import annotations

import csv
import json
from datetime import datetime

from benchmarks import config, outputs

GRADED = {
    "id": "a",
    "input": "Q1",
    "expected": "A1",
    "answer": "A1",
    "grade": 1.0,
    "verdict": '{"answer_score": 1}',
    "finished": True,
    "search_calls": 2,
    "search_cost_usd": 0.01,
    "synthesis_cost_usd": 0.002,
    "tco_usd": 0.012,
    "search_time_s": 1.234,
    "model_time_s": 5.0,
    "total_time_s": 6.5,
    "search_errors": 0,
    "search_refused": 1,
    "search_counters": {"knowledge_card_count": 3},
    "server_latency_ms": [400, 600],
    "searches": [{"query": "q", "ok": True, "web": [], "knowledge": []}],
}
UNGRADED = {**GRADED, "id": "b", "expected": None, "grade": None, "server_latency_ms": [800]}
ERRORED = {"id": "c", "input": "Q3", "expected": "A3", "grade": None, "error": "RuntimeError: boom"}


def _manifest():
    return outputs.build_manifest(
        provider="you_knowledge",
        exclusion_mechanism="api_parameter",
        queries={"name": "q"},
        search_budget=3,
        exclude_domains_name="answer_farms",
        exclude_domains=config.DOMAIN_EXCLUSIONS["answer_farms"],
        blocklist=(),
        concurrency=5,
    )


class TestRunWriter:
    def test_writes_three_files(self, tmp_path):
        w = outputs.RunWriter(tmp_path / "run", _manifest())
        for rec in (GRADED, UNGRADED, ERRORED):
            w.append(rec)
        w.close(outputs.totals([GRADED, UNGRADED, ERRORED]))

        with (tmp_path / "run" / "summary.csv").open() as fh:
            rows = list(csv.DictReader(fh))
        assert [r["id"] for r in rows] == ["a", "b", "c"]
        assert tuple(rows[0]) == outputs.SUMMARY_FIELDS
        assert (rows[0]["grade"], rows[1]["grade"], rows[2]["grade"]) == ("1", "", "")
        assert rows[0]["knowledge_cards"] == "3" and rows[0]["search_time_s"] == "1.23"
        assert (rows[0]["total_time_s"], rows[0]["tco_usd"]) == ("6.5", "0.012")
        assert rows[2]["error"] == "RuntimeError: boom"

        details = [json.loads(line) for line in (tmp_path / "run" / "details.jsonl").open()]
        assert details[0]["searches"] == GRADED["searches"]
        assert details[0]["verdict"] == GRADED["verdict"]

        manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
        assert manifest["provider"] == "you_knowledge"
        assert manifest["totals"]["questions"] == 3

    def test_rows_are_on_disk_before_close(self, tmp_path):
        w = outputs.RunWriter(tmp_path / "run", _manifest())
        w.append(GRADED)
        assert (tmp_path / "run" / "details.jsonl").read_text().count("\n") == 1
        assert (tmp_path / "run" / "summary.csv").read_text().count("\n") == 2


class TestTotals:
    def test_accuracy_is_over_graded_rows_only(self):
        t = outputs.totals([GRADED, UNGRADED, ERRORED])
        assert (t["questions"], t["graded"], t["correct"], t["accuracy"]) == (3, 1, 1, 1.0)
        assert t["errored"] == 1

    def test_server_latency_pools_every_search(self):
        t = outputs.totals([GRADED, UNGRADED])
        assert (t["server_latency_ms_p50"], t["server_latency_ms_mean"]) == (600, 600)

    def test_time_and_cost_are_per_question_means(self):
        t = outputs.totals([GRADED, {**UNGRADED, "total_time_s": 7.5, "tco_usd": 0.014}])
        assert t["total_time_s_per_question"] == 7.0
        assert t["tco_usd_per_question"] == 0.013
        assert t["search_cost_usd_per_question"] == 0.01
        assert t["tco_usd_total"] == 0.026

    def test_nothing_graded(self):
        t = outputs.totals([UNGRADED])
        assert t["accuracy"] is None
        assert "no rows have an `expected`" in outputs.report(t)

    def test_report_names_graded_and_total(self):
        text = outputs.report(outputs.totals([GRADED, UNGRADED, ERRORED]))
        assert "1 correct of 1 graded / 3 total" in text
        assert "p50 600 ms" in text
        assert "total time       6.5s" in text and "TCO              $0.01200" in text
        assert "1 rows errored" in text


class TestRunDir:
    def test_name(self, tmp_path):
        d = outputs.run_dir(tmp_path, "verticalrtk_fast", datetime(2026, 9, 22, 13, 5, 9))
        assert d.name == "20260922-130509-verticalrtk_fast"


class TestShow:
    SEARCH = {
        "query": "aws ebit q2",
        "knowledge": [
            {
                "title": "AWS EBIT",
                "attribution": ["S&P Global"],
                "as_of": "2026-Q2",
                "description": "d",
            }
        ],
        "web": [{"title": "Filing", "url": "https://sec.gov/x", "highlights": ["h1"]}],
    }

    def _run(self, tmp_path):
        run = tmp_path / "20260923-000000-verticalrtk_fast"
        arms = {
            "you_knowledge": [
                {
                    "id": "a",
                    "input": "Q1",
                    "expected": "A1",
                    "grade": 1.0,
                    "answer": "k1",
                    "searches": [self.SEARCH],
                },
                {"id": "b", "input": "Q2", "expected": "A2", "grade": 1.0, "answer": "k2"},
            ],
            "you_web": [
                {
                    "id": "a",
                    "input": "Q1",
                    "expected": "A1",
                    "grade": 0.0,
                    "answer": "w1",
                    "searches": [{**self.SEARCH, "knowledge": []}],
                },
                {"id": "b", "input": "Q2", "expected": "A2", "grade": 1.0, "answer": "w2"},
            ],
        }
        for name, recs in arms.items():
            (run / name).mkdir(parents=True)
            (run / name / "details.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        return run

    def test_defaults_to_the_questions_that_differ(self, tmp_path):
        text = outputs.show(self._run(tmp_path))
        assert "a  Q1" in text and "b  Q2" not in text
        assert "--- you_knowledge   grade 1" in text and "--- you_web   grade 0" in text
        assert "[knowledge] AWS EBIT  (S&P Global · as of 2026-Q2)" in text
        assert "[web] Filing  https://sec.gov/x" in text and "h1" in text

    def test_one_question_by_id(self, tmp_path):
        text = outputs.show(self._run(tmp_path), "b")
        assert "b  Q2" in text and "answer: w2" in text

    def test_unknown_id_and_latest_run(self, tmp_path):
        run = self._run(tmp_path)
        assert "zz is not in" in outputs.show(run, "zz")
        assert outputs.latest_run(tmp_path) == run


class TestCompare:
    ROWS = [
        {"id": "a", "input": "Q1", "expected": "A1", "metadata": {"vertical": "companies"}},
        {"id": "b", "input": "Q2", "expected": "A2", "metadata": {"vertical": "sports"}},
        {"id": "c", "input": "Q3", "expected": None, "metadata": {}},
    ]

    def _runs(self):
        def rec(qid, grade, answer):
            return {**GRADED, "id": qid, "grade": grade, "answer": answer}

        return {
            "you_knowledge": [rec("b", 1.0, "k2"), rec("a", 1.0, "k1"), rec("c", None, "k3")],
            "you_web": [rec("a", 0.0, "w1"), rec("b", 1.0, "w2"), rec("c", None, "w3")],
        }

    def test_report_by_vertical_and_the_questions_that_differ(self):
        text, _ = outputs.compare(self.ROWS, self._runs())
        assert "2 questions graded by every provider" in text
        assert "all (2)" in text and "companies (1)" in text and "sports (1)" in text
        assert "100.0%" in text and "50.0%" in text
        assert "right with you_knowledge, wrong with you_web: 1\n    a  Q1" in text
        assert "right with you_web, wrong with you_knowledge: 0" in text

    def test_table_has_every_question_in_input_order(self, tmp_path):
        _, table = outputs.compare(self.ROWS, self._runs())
        assert [r["id"] for r in table] == ["a", "b", "c"]
        assert table[0]["you_knowledge_grade"] == 1 and table[0]["you_web_grade"] == 0
        assert table[2]["you_web_grade"] == "" and table[2]["you_web_answer"] == "w3"

        outputs.write_comparison(tmp_path / "comparison.csv", table)
        with (tmp_path / "comparison.csv").open() as fh:
            header = next(csv.reader(fh))
        assert header == [
            "id",
            "input",
            "expected",
            "vertical",
            "you_knowledge_grade",
            "you_knowledge_answer",
            "you_web_grade",
            "you_web_answer",
        ]


class TestManifest:
    def test_records_every_setting_that_moves_the_numbers(self):
        m = _manifest()
        for key in (
            "provider",
            "exclusion_mechanism",
            "queries",
            "search_budget",
            "exclude_domains",
            "blocklist",
            "concurrency",
            "candidate_model",
            "judge_model",
            "agent_prompt_sha",
            "judge_prompt_sha",
            "agent_knows_date",
            "price_per_1m_tokens",
            "harness",
        ):
            assert key in m, key
        assert m["exclude_domains_count"] == len(config.DOMAIN_EXCLUSIONS["answer_farms"])

    def test_prompt_shas_match_the_published_results(self):
        # A change here means new results aren't comparable to the published ones.
        m = _manifest()
        assert m["agent_prompt_sha"] == AGENT_PROMPT_SHA
        assert m["judge_prompt_sha"] == JUDGE_PROMPT_SHA


AGENT_PROMPT_SHA = "b14396e600e9"
JUDGE_PROMPT_SHA = "4efad79be591"
