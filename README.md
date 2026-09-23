# You.com Knowledge

Companion code for the You.com Knowledge launch post.

Web search tells an agent what pages say. Knowledge gives it the data itself: structured, real-time results from licensed providers such as The Economist, S&P Global, AccuWeather, CoinMarketCap, and the Bank for International Settlements. They are returned alongside web and news results from the same You.com Search call. Add `knowledge="core"` to a search, and relevant results come back under `results.knowledge`, each with a description, an `as_of` date, and an attribution naming the provider.

Search costs $5 per 1,000 calls.

- [Get an API key](https://you.com/platform/api-keys)
- [Read the docs](https://docs.you.com/api-reference/search)

## What's here

- **[Demos](demos/README.md):** the runnable queries from the post (Big Mac Index, Nvidia stock, Boise weather, BTC to USD, and the yen carry trade), plus an interactive loop. Each one uses the official `youdotcom` Python SDK, and the demos README shows the same call in curl.
- **[Benchmarks](benchmarks/README.md):** how Knowledge compares with web-only search APIs on Vertical RTK, and how to reproduce the results.

Shared helpers for rendering, synthesis, and cost live in [`utils/`](utils).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
cp .env.example .env   # then set YDC_API_KEY
make install           # uv sync
make weather           # run one demo to check your key
```

`.env` holds:

| Variable | Needed for |
| --- | --- |
| `YDC_API_KEY` | Every demo. The `youdotcom` SDK reads it from the environment. |
| `OPENROUTER_API_KEY` | Optional. Only for GPT-5.6 Luna synthesis (`SYNTH=1` / `--synthesize`). |

Run everything from the repo root. `make help` lists every target.
