.PHONY: help install big-mac nvidia weather bitcoin yen-carry interactive all

SYNTH ?=
FLAG := $(if $(filter 1 true yes,$(SYNTH)),--synthesize)

help:
	@echo "install      uv sync — install httpx + the youdotcom SDK"
	@echo "big-mac      What's the Big Mac Index for Japan versus the US?"
	@echo "nvidia       What's Nvidia's stock price?"
	@echo "weather      What's the weather in Boise, Idaho?"
	@echo "bitcoin      What's the BTC to USD price right now?"
	@echo "yen-carry    US policy rate vs Japan policy rate and USD/JPY exchange rate"
	@echo "interactive  paste queries in a loop"
	@echo "all          run all five examples"
	@echo ""
	@echo "add SYNTH=1 to any target for GPT-5.6 Luna synthesis (needs OPENROUTER_API_KEY)"

install:
	uv sync

big-mac:
	uv run python -m demos.big_mac $(FLAG)

nvidia:
	uv run python -m demos.nvidia $(FLAG)

weather:
	uv run python -m demos.boise_weather $(FLAG)

bitcoin:
	uv run python -m demos.bitcoin $(FLAG)

yen-carry:
	uv run python -m demos.yen_carry_trade $(FLAG)

interactive:
	uv run python -m demos.interactive $(FLAG)

all: big-mac nvidia weather bitcoin yen-carry
