.PHONY: help install big-mac nvidia weather bitcoin nasa interactive all bench bench-preflight bench-export bench-show test

SYNTH ?=
FLAG := $(if $(filter 1 true yes,$(SYNTH)),--synthesize)
DEMO := uv run python -m demos.run

QUERIES ?=
LIMIT ?=
BUDGET ?=
PROVIDER ?=
BENCH_ARGS := $(if $(QUERIES),--queries $(QUERIES)) $(if $(LIMIT),--limit $(LIMIT)) \
	$(if $(BUDGET),--search-budget $(BUDGET)) $(if $(PROVIDER),--provider $(PROVIDER))
BENCH := uv run --group bench python -m benchmarks.run

help:
	@echo "install      uv sync — install httpx + the youdotcom SDK"
	@echo "big-mac      What's the Big Mac Index for Japan versus the US?"
	@echo "nvidia       What's Nvidia's stock price?"
	@echo "weather      What's the weather in Boise, Idaho?"
	@echo "bitcoin      What's the BTC to USD price right now?"
	@echo "nasa         How much did NASA pay out in federal contract outlays in FY2025?"
	@echo "interactive  paste queries in a loop"
	@echo "all          run all five examples"
	@echo ""
	@echo "add SYNTH=1 to any target for GPT-5.6 Luna synthesis (needs OPENROUTER_API_KEY)"
	@echo ""
	@echo "bench-preflight  check keys and one live search before a benchmark"
	@echo "bench            run You.com with and without Knowledge on VerticalRTK fast, grade, compare"
	@echo "                 QUERIES=my.jsonl  LIMIT=5  BUDGET=1  PROVIDER=you_knowledge"
	@echo "                 (needs OPENAI_API_KEY)"
	@echo "bench-export     write the pinned questions to benchmarks/verticalrtk_fast.jsonl to edit"
	@echo "bench-show       knowledge cards vs web highlights where the arms disagree (or ID=...)"
	@echo "test             run the offline test suite"

install:
	uv sync

big-mac nvidia weather bitcoin nasa:
	$(DEMO) $@ $(FLAG)

interactive:
	$(DEMO) --interactive $(FLAG)

all:
	$(DEMO) $(FLAG)

bench-preflight:
	$(BENCH) --preflight $(BENCH_ARGS)

bench:
	$(BENCH) $(BENCH_ARGS)

bench-export:
	$(BENCH) --export-queries benchmarks/verticalrtk_fast.jsonl

bench-show:
	$(BENCH) --show $(ID) $(if $(RUN),--run $(RUN))

test:
	uv run --group bench --group dev pytest
