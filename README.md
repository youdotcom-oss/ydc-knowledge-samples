# ydc-knowledge-samples

Minimal Python examples for the [You.com](https://you.com) Knowledge launch blog. Each script POSTs one query to `https://ydc-index.io/v1/search` with `knowledge=core`, which returns structured Knowledge cards plus licensed attributions (The Economist, Xignite / S&P Global, AccuWeather, CoinMarketCap, and others).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
cp .env.example .env
# set YOU_API_KEY in .env (YDC_API_KEY is also accepted)
make install
```

## Run

```bash
make help        # targets + exact query strings
make big-mac     # What's the Big Mac Index for Japan versus the US?
make nvidia      # What's Nvidia's stock price?
make weather     # What's the weather in Boise, Idaho?
make bitcoin     # What's Bitcoin's price right now?
make all         # run all four
```

Each script pretty-prints the `results.knowledge` array as JSON, then the first `results.web` hit if present. Fields are printed as returned — nothing is invented.

Without a key, the client exits with a short error. Get an API key from You.com, then rerun.
