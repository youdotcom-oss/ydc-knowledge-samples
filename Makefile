.PHONY: help install big-mac nvidia weather bitcoin all

help:
	@echo "install   uv sync — install project + httpx"
	@echo "big-mac   What's the Big Mac Index for Japan versus the US?"
	@echo "nvidia    What's Nvidia's stock price?"
	@echo "weather   What's the weather in Boise, Idaho?"
	@echo "bitcoin   What's Bitcoin's price right now?"
	@echo "all       run all four examples"

install:
	uv sync

big-mac:
	uv run python scripts/big_mac.py

nvidia:
	uv run python scripts/nvidia.py

weather:
	uv run python scripts/boise_weather.py

bitcoin:
	uv run python scripts/bitcoin.py

all: big-mac nvidia weather bitcoin
