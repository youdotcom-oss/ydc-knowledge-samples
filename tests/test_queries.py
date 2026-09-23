"""The query loader, the VerticalRTK mapping, and export. No network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks import queries
from benchmarks.queries import QueryFileError, from_verticalrtk, load, parse_records

EXAMPLE = Path(__file__).resolve().parents[1] / "benchmarks" / "example_queries.jsonl"


def _jsonl(*records) -> str:
    return "\n".join(r if isinstance(r, str) else json.dumps(r) for r in records)


class TestParseRecords:
    def test_all_fields(self):
        (row,) = parse_records(
            _jsonl({"id": 7, "input": " Q? ", "expected": "A", "metadata": {"k": "v"}}), where="f"
        )
        assert row == {"id": "7", "input": "Q?", "expected": "A", "metadata": {"k": "v"}}

    def test_only_input_is_required(self):
        (row,) = parse_records(_jsonl({"input": "Q?"}), where="f")
        assert row == {"id": "row-0001", "input": "Q?", "expected": None, "metadata": {}}

    def test_default_id_is_the_line_number(self):
        rows = parse_records(_jsonl({"input": "a"}, "", {"input": "b"}), where="f")
        assert [r["id"] for r in rows] == ["row-0001", "row-0003"]

    def test_blank_expected_is_ungraded(self):
        (row,) = parse_records(_jsonl({"input": "Q", "expected": "  "}), where="f")
        assert row["expected"] is None

    @pytest.mark.parametrize(
        "line,match",
        [
            ("not json", r"f:1: not valid JSON"),
            ("[1, 2]", r"f:1: each line must be a JSON object"),
            (json.dumps({"expected": "A"}), r"f:1: `input` must be a non-empty string"),
            (json.dumps({"input": {"question": "Q"}}), r"`input` must be a non-empty string"),
            (json.dumps({"input": "Q", "expected": 3}), r"`expected` must be a string"),
            (json.dumps({"input": "Q", "metadata": [1]}), r"`metadata` must be an object"),
        ],
    )
    def test_bad_lines_name_the_line(self, line, match):
        with pytest.raises(QueryFileError, match=match):
            parse_records(line, where="f")

    def test_duplicate_ids_are_rejected(self):
        with pytest.raises(QueryFileError, match="duplicate id 'x'"):
            parse_records(_jsonl({"id": "x", "input": "a"}, {"id": "x", "input": "b"}), where="f")

    def test_empty_file_is_rejected(self):
        with pytest.raises(QueryFileError, match="no records"):
            parse_records("\n\n", where="f")


class TestLoadFile:
    def test_example_file_loads(self):
        qs = load(str(EXAMPLE))
        assert len(qs.rows) == 3 and qs.n_graded == 1
        assert qs.blocklist == ()
        assert qs.source["path"].endswith("example_queries.jsonl")
        assert len(qs.source["sha256"]) == 64
        assert (qs.source["n_rows"], qs.source["n_graded"]) == (3, 1)

    def test_limit_takes_the_first_n(self):
        qs = load(str(EXAMPLE), limit=2)
        assert [r["id"] for r in qs.rows] == ["bis-founded", "fed-funds"]

    def test_only_jsonl(self, tmp_path):
        p = tmp_path / "q.csv"
        p.write_text("input\nQ\n")
        with pytest.raises(QueryFileError, match=r"expected a \.jsonl file"):
            load(str(p))


class TestVerticalRTK:
    UPSTREAM = _jsonl(
        {
            "id": "0001",
            "query": "Q1?",
            "vertical": "finance",
            "answer": "A1",
            "as_of": "2026-09-01",
        },
        {
            "id": "0002",
            "query": "Q2?",
            "vertical": "weather",
            "answer": "A2",
            "as_of": "2026-09-02",
        },
    )

    def test_mapping_keeps_text_unchanged(self):
        rows = parse_records(from_verticalrtk(self.UPSTREAM), where="u")
        assert rows[0] == {
            "id": "0001",
            "input": "Q1?",
            "expected": "A1",
            "metadata": {"vertical": "finance", "as_of": "2026-09-01"},
        }
        assert len(rows) == 2

    def test_export_round_trips(self, tmp_path):
        rows = parse_records(from_verticalrtk(self.UPSTREAM), where="u")
        qs = queries.QuerySet(name="verticalrtk_fast", rows=rows, source={})
        path = queries.export(qs, tmp_path / "out.jsonl")
        assert load(str(path)).rows == rows

    def test_an_exported_verticalrtk_copy_keeps_the_leak_filter(self, tmp_path):
        rows = [{"id": "vrtk_fast_0001", "input": "Q?", "expected": "A", "metadata": {}}]
        qs = queries.QuerySet(name="verticalrtk_fast", rows=rows, source={})
        again = load(str(queries.export(qs, tmp_path / "verticalrtk_fast.jsonl")))
        assert again.blocklist == queries.config.VERTICALRTK_BLOCKLIST

    def test_export_keeps_ungraded_rows_ungraded(self, tmp_path):
        qs = load(str(EXAMPLE))
        again = load(str(queries.export(qs, tmp_path / "mine.jsonl")))
        assert again.rows == qs.rows and again.n_graded == 1

    def test_url_is_pinned_to_a_commit(self):
        assert len(queries.VERTICALRTK_REF) == 40
        assert queries.verticalrtk_url(queries.VERTICALRTK_REF) == (
            "https://raw.githubusercontent.com/TakoData/VerticalRTK/"
            f"{queries.VERTICALRTK_REF}/data/verticalrtk_fast.jsonl"
        )
