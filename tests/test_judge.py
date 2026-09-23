"""The rubric grader, on the paths that make no request."""

from __future__ import annotations

import hashlib

import anyio
import pytest

from benchmarks import config, judge

# sha256 of the files as published with FinSearchComp.
RUBRIC_SHA256 = {
    "judge_system_prompt.txt": "a2b4c4f4dd42a0ac6080ef3fcf9ec46fdf23ab5921353de7bf890ed74ff1a123",
    "judge_prompt_template.txt": "3b2980e6ae7e64f6d99c6911e7c08915a2b8d07191c803639c3c725bb44457a3",
}


class TestRubric:
    def test_rubric_files_load_and_ask_for_answer_score(self):
        system, template = judge.rubric()
        assert "answer_score" in system
        assert all(p in template for p in ("{prompt}", "{response_reference}", "{response}"))

    def test_normalization_rule_is_appended_not_edited_in(self):
        system, _ = judge.rubric()
        assert system.endswith(config.JUDGE_NORMALIZATION_RULE)
        raw = (judge.PROMPTS_DIR / "judge_system_prompt.txt").read_text()
        assert config.JUDGE_NORMALIZATION_RULE not in raw

    @pytest.mark.parametrize("name", sorted(RUBRIC_SHA256))
    def test_vendored_files_are_unmodified(self, name):
        data = (judge.PROMPTS_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == RUBRIC_SHA256[name]

    def test_prompt_fills_all_three_slots(self):
        p = judge.build_prompt("Q?", "REF", "ANS")
        assert "Q?" in p and "REF" in p and "ANS" in p

    @pytest.mark.parametrize(
        "text,want",
        [
            ('- JSON:\n{"answer_score": 1}', 1.0),
            ('blah {"answer_score": 0}', 0.0),
        ],
    )
    def test_score_parsing(self, text, want):
        assert float(judge.SCORE_RE.search(text).group(1)) == want

    def test_unparseable_verdict_is_not_scored_zero(self):
        assert judge.SCORE_RE.search("I think it is correct.") is None


class TestGrade:
    def test_empty_answer_scores_zero_without_a_judge_call(self):
        assert anyio.run(judge.grade, None, "Q", "REF", None) == (0.0, "empty answer")

    def test_no_expected_answer_is_not_graded(self):
        assert anyio.run(judge.grade, None, "Q", None, "an answer") == (None, None)
        assert anyio.run(judge.grade, None, "Q", "", "an answer") == (None, None)


class TestJudgeClient:
    def test_judge_calls_openai_directly(self):
        client = judge.make_client(api_key="sk-test")
        assert str(client.base_url).startswith("https://api.openai.com/v1")


class TestPinnedConstants:
    def test_methodology_constants_are_pinned(self):
        assert config.MAX_SEARCH_RESULTS == 10
        assert config.MAX_TURNS == 25
        assert config.TEMPERATURE is None
        assert config.DEFAULT_SEARCH_BUDGET == 1

    def test_judge_and_candidate_are_the_same_family(self):
        assert config.JUDGE_MODEL == config.CANDIDATE_MODEL

    def test_synthesis_cost_uses_list_price(self):
        # 1M input at $0.20 plus 1M output at $1.20.
        assert config.synthesis_cost_usd(1_000_000, 1_000_000) == pytest.approx(1.40)
        assert config.synthesis_cost_usd(2_000, 900) == pytest.approx(0.00148)
