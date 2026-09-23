# Demos

Runnable examples from the You.com Knowledge launch post. Each one sends a single query to the You.com Search API with `knowledge="core"`, then prints the knowledge cards, web results, and news results that come back.

Set up the repo first. See [Setup](../README.md#setup) in the root README.

## Make a call

With the official Python SDK ([`youdotcom`](https://pypi.org/project/youdotcom/) 3.5.0 or later), a bare `You()` reads `YDC_API_KEY` from the environment:

```python
from youdotcom import You

with You() as you:
    response = you.search(
        query="US policy rate vs Japan policy rate and USD/JPY exchange rate",
        knowledge="core",
    )

for card in response.results.knowledge or []:
    sources = ", ".join(a.name for a in card.attribution)
    print(f"{card.title} ({sources}, as of {card.as_of})")
    print(card.description)
```

The same request with curl:

```bash
curl -s https://ydc-index.io/v1/search \
  -H "X-API-Key: $YDC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "US policy rate vs Japan policy rate and USD/JPY exchange rate", "knowledge": "core"}' \
  | jq '.results.knowledge'
```

Knowledge cards arrive under `results.knowledge`, alongside the usual `results.web` and `results.news`. Each card has a `title`, a `description`, an optional `as_of` date, and an `attribution` list naming the licensed data provider.

## Run the examples

Run these from the repo root:

```bash
make help        # targets + exact query strings
make big-mac     # What's the Big Mac Index for Japan versus the US?
make nvidia      # What's Nvidia's stock price?
make weather     # What's the weather in Boise, Idaho?
make bitcoin     # What's the BTC to USD price right now?
make yen-carry   # US policy rate vs Japan policy rate and USD/JPY exchange rate
make interactive # paste queries in a loop
make all         # run all five
```

Each `make` target runs a module, for example `uv run python -m demos.nvidia`. The demos import shared helpers from [`utils/`](../utils), so run them from the repo root with `-m` rather than as `python demos/nvidia.py`.

Each demo prints `results.knowledge` first (title, attribution, `as_of`, description), then `results.web`, then `results.news`, then latency. Search-only is the default, so you only need `YDC_API_KEY`.

### Optional synthesis

With `OPENROUTER_API_KEY` set in `.env`, any demo can pass the results to [GPT-5.6 Luna](https://openrouter.ai/openai/gpt-5.6-luna) for a short answer:

```bash
make nvidia SYNTH=1
uv run python -m demos.nvidia --synthesize
make interactive SYNTH=1   # or type /synth inside the loop
```

That adds a Luna summary plus a cost breakdown: You.com Search ($5 / 1k calls), Luna token cost, and the total.

## Knowledge results

The cards each query returns, with the source that licenses the data. Descriptions are abbreviated here; the demos print them in full. Values are live, so numbers and `as_of` dates differ every run.

### `make big-mac`: What's the Big Mac Index for Japan versus the US?

| Card | Attribution |
| --- | --- |
| Japan, United States - Big Mac Index (Adjusted - USD) | The Economist |
| Japan Big Mac Index (Adjusted - USD) | The Economist |
| Japan Big Mac Index (Raw - USD) | The Economist |

> Japan Big Mac Index (Adjusted - USD)'s latest value was -0.41979 Index Points in Jan 2025, up 41.93% since Jan 2022 […]; United States Big Mac Index (Adjusted - USD)'s latest value was 0 Index Points in Jan 2025 […]. Data from Jan 2022 to Jan 2025.

### `make nvidia`: What's Nvidia's stock price?

| Card | Attribution |
| --- | --- |
| Nvidia Stock Overview | Xignite / S&P Global |

> Nvidia (NVDA) stock price is $227.17 as of Sep 21, 2026 2:12 PM EDT. Current market cap is $5,439,524,663,700. The Sep 21, 2026 session opened at $222.07, with a high of $227.34 and a low of $222.07. The 52-week range is $165.17 to $235.74. The P/E ratio is 28.48. The P/S ratio is 16.57.

### `make weather`: What's the weather in Boise, Idaho?

| Card | Attribution |
| --- | --- |
| Boise, ID Current Weather Forecast | AccuWeather |

> Weather forecast for Boise, Idaho, United States on Sep 21, 2026 1:00 PM. Currently, it is 77°F and feels like 81°F. The high is 85°F and the low is 57°F. The weather is expected to be clear. Sunrise is at 7:30 AM and sunset is at 7:43 PM […]. The weekly forecast is: Tuesday, clear, high of 86°F and low of 57°F; […]

### `make bitcoin`: What's the BTC to USD price right now?

| Card | Attribution |
| --- | --- |
| Bitcoin to USD conversion rate | CoinMarketCap |

> Exchange rate from Bitcoin (BTC) to United States Dollar (USD). The current rate is $86,041.6 per BTC. The rate rose 5.941% (4,825.22 USD) from Sep 20, 2026 6:20 PM UTC to Sep 21, 2026 6:20 PM UTC. It ranged from 80,753.8 to 86,284.4 USD over that period.

The query says `BTC to USD` rather than `Bitcoin`. Asking for `BTC` alone also matches unrelated entities (a `BTC Funding` card, and a London BTC Company stock card), and asking for `Bitcoin` pulls in a Mercado Bitcoin funding card.

### `make yen-carry`: US policy rate vs Japan policy rate and USD/JPY exchange rate

One call covering both legs of the carry trade plus the exchange rate.

| Card | Attribution |
| --- | --- |
| United States, Japan - Central Bank Policy Rate | Bank for International Settlements |
| Currency Exchange: Japanese Yen (JPY) to US Dollar (USD) | Xignite |
| Currency Exchange: US Dollar (USD) to Japanese Yen (JPY) | Xignite |

> United States Central Bank Policy Rate's latest value was 3.6% in Aug 2026, up 0% since Feb 2026 […]; Japan Central Bank Policy Rate's latest value was 1.0% in Aug 2026, up 33.33% since Feb 2026, with a maximum of 1.0% in Jun 2026 and a minimum of 0.75% in Feb 2026. Monthly data from Feb 2026 to Aug 2026.

Both policy rates arrive in a single comparison card. The two currency cards are the same pair quoted in both directions, and which of them come back varies run to run: sometimes both, sometimes only one.
