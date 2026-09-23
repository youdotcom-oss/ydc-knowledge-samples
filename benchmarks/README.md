# Benchmarks

[VerticalRTK](https://github.com/TakoData/VerticalRTK) is a public benchmark built by Tako, one of our data partners. Its 155 questions target live, structured data: the categories where crawling the public web struggles. An agent answers each question with one search from the API under test, and an LLM judge grades the answer against the reference.

We use it because it shows what Knowledge adds beyond web search, across a wide range of domains: companies, government and defense, macro and markets, society and health, energy and climate, sports, and digital usage.

## The benchmark run (September 22, 2026)

| Arm | Accuracy | Query time (server) | Total time | Query cost | TCO |
| --- | --- | --- | --- | --- | --- |
| **You.com + Knowledge** | **84.2%** | **0.74s** | **7.1s** | **$0.00500** | **$0.00797** |
| Parallel advanced | 65.2% | ~4.14s (est) | 10.1s | $0.00500 | $0.00750 |
| You.com web search | 64.5% | 0.60s | 7.3s | $0.00500 | $0.00815 |
| Perplexity high | 64.5% | ~1.21s (est) | 7.0s | $0.00500 | $0.00711 |
| Exa auto + highlights | 63.9% | 1.69s | 8.1s | $0.00700 | $0.00990 |
| Parallel basic | 57.4% | ~1.85s (est) | 9.3s | $0.00500 | $0.00762 |
| Model only, GPT-5.6 Luna | 14.8% | 0.00s | 5.2s | $0.00000 | $0.00145 |

- Every row is the average of 3 separate runs over all 155 questions.
- Query time is p50 server-side query time, which excludes network and model inference. Parallel and Perplexity don't return server times, so their values are marked "est" and are estimated to the best of our ability.
- Total time is the full harness time per question: the search plus model synthesis. TCO is query cost plus synthesis cost per question, at OpenAI list price with no cache discount.
- Both You.com configurations run with Highlights enabled. The only difference between them is the `knowledge` parameter. All other providers run at the setting named in their row.

## Methodology

The setup is based on the [Artificial Analysis Search API methodology](https://artificialanalysis.ai/methodology/search-api): one fixed agent, harness and judge, so that the search provider is the only thing that varies.

| Setting | Value |
| --- | --- |
| Questions | VerticalRTK fast, 155 questions, pinned to the commit at the end of September 22 ([`ae470841`](https://github.com/TakoData/VerticalRTK/tree/ae470841aef53080bfeb87add5704278198114ef)) |
| Agent | GPT-5.6 Luna, medium reasoning, via the OpenAI Responses API, told today's date |
| Harness | [Stirrup](https://github.com/ArtificialAnalysis/Stirrup) 0.2.0, 25 turns |
| Searches per question | 1, with 10 results per search |
| You.com search call | `extraction={"extraction_mode": "highlights"}`, plus `knowledge="core"` for the Knowledge arm |
| Excluded domains | 19 homework-answer and scraped-content sites, the same for every provider ([`config.py`](config.py)) |
| Judge | GPT-5.6 Luna, medium reasoning, FinSearchComp's rubric plus one rule for numeric form; binary right or wrong |

Results that link to VerticalRTK itself are dropped before the agent sees them, since its answer key is public.

### Refreshing goldens

Some reference answers go stale: prices, rates, the latest quarter, forecasts. A stale reference can grade a correct live answer as wrong, which penalizes whichever arm has the freshest data. For the best results, refresh the ground truth at the end of the trading day, then run the benchmark the same evening:

1. `make bench-export` writes the pinned question set to `benchmarks/verticalrtk_fast.jsonl` as an editable file. Each row keeps its `as_of` in `metadata`, so the rows that move day to day are easy to find.
2. After the close, update `expected` on the rows that moved, from a primary source.
3. Run `make bench QUERIES=benchmarks/verticalrtk_fast.jsonl`.

Tako also refreshes the set upstream; `--queries-ref main` runs their latest version. A score is only comparable to another score graded against the same answers.

## How it's built

| File | What it does |
| --- | --- |
| [`run.py`](run.py) | The command behind `make bench`: loads the questions, runs each provider, grades the answers, and compares the providers |
| [`config.py`](config.py) | Everything held fixed across providers: model, prompts, search budget, excluded domains, prices |
| [`queries.py`](queries.py) | Fetches VerticalRTK at the pinned commit, loads your own JSONL, and exports either one |
| [`providers.py`](providers.py) | The You.com call, with and without Knowledge; add your own provider here |
| [`agent.py`](agent.py) | The Stirrup agent and its `web_search` tool |
| [`judge.py`](judge.py) | Grades each answer with the FinSearchComp rubric |
| [`outputs.py`](outputs.py) | Writes the results folder and `manifest.json`, and prints the comparison and `make bench-show` |
| [`prompts/`](prompts) | The FinSearchComp judge rubric, unmodified |
| [`example_queries.jsonl`](example_queries.jsonl) | A three-question file to start your own set from |

## Running it

Set up the repo first; see [Setup](../README.md#setup). The benchmark needs `YDC_API_KEY` and `OPENAI_API_KEY` in `.env`.

```bash
make bench-preflight   # checks both keys and runs one live search per arm
make bench LIMIT=5     # a smoke test on the first 5 questions
make bench             # the full run: both You.com rows, graded and compared
```

`make bench` runs You.com + Knowledge and You.com web search on the same questions, grades every answer, and logs each question as it finishes. To match the published table, repeat the run separately and average. Repeating a run straight away hits the server cache, which makes latency look faster than it is.

The other rows in the table need their own provider; see [Adding a provider](#adding-a-provider).

The Makefile targets wrap `uv run --group bench python -m benchmarks.run`. Call it directly for the other flags:

| Flag | Default | |
| --- | --- | --- |
| `--queries PATH` | VerticalRTK fast | Your JSONL file |
| `--limit N` | all | First N questions |
| `--provider NAME ...` | `you_knowledge you_web` | One or more; the first is compared to the rest |
| `--search-budget N` | 1 | Searches allowed per question; `0` is unlimited |
| `--queries-ref REF` | pinned commit | VerticalRTK commit or branch, e.g. `main` |
| `--export-queries PATH` | | Write the question set as JSONL, then exit |
| `--show [ID]` | | Print knowledge cards and web highlights, then exit |
| `--dry-run` | | Print what would run, spend nothing |
| `--verbose` | | Show Stirrup's per-turn agent log |

Each run writes a folder under `benchmarks/results/`, named `<timestamp>-<query set>/`. It has one subfolder per provider, with `summary.csv` (one line per question), `details.jsonl` (everything, including every search and what it returned) and `manifest.json` (the settings and totals). Rows are written as they finish, so a run you stop halfway keeps every row it already paid for.

## Web highlights vs Knowledge

When `make bench` finishes, it prints the two arms side by side: accuracy overall and by vertical, query time, total time and TCO, then every question one arm got right and the other got wrong. `comparison.csv` in the run folder has each question with both arms' answers and grades.

To see what each arm was actually given, run:

```bash
make bench-show                    # every question the two arms graded differently
make bench-show ID=vrtk_fast_0002  # one question
```

For each arm, it prints the answer and grade, then the search the agent made: the knowledge cards, with their source and `as_of` date, and the web results with their highlights. It reads the latest run; add `RUN=benchmarks/results/<folder>` for an earlier one.

## Your own query set

One JSON object per line, in the same shape as a [Braintrust](https://www.braintrust.dev/docs/guides/datasets) dataset record:

```json
{"id": "bis-founded", "input": "In what year was the Bank for International Settlements founded?", "expected": "1930"}
{"id": "fed-funds", "input": "What is the current target range for the US federal funds rate?", "metadata": {"topic": "macro"}}
{"input": "What is the current USD to JPY exchange rate?"}
```

Only `input` is required. Rows without an `expected` answer are run and recorded, but not graded. `id` defaults to the line number, and `metadata` is copied into the outputs; a `vertical` in `metadata` gets its own line in the comparison.

```bash
make bench QUERIES=benchmarks/example_queries.jsonl
make bench-show
```

## Adding a provider

A provider is one function that takes a query and returns a `SearchResponse`. Add it to [`providers.py`](providers.py), next to `you_search`, with `import os` at the top of the file:

```python
def acme_search(query, *, count, blocklist=(), exclude_domains=()):
    started = time.monotonic()
    r = httpx.post(
        "https://api.acme.example/search",
        headers={"Authorization": f"Bearer {os.environ['ACME_API_KEY']}"},
        json={"q": query, "limit": count, "exclude_domains": list(exclude_domains)},
        timeout=60,
    )
    r.raise_for_status()
    hits, dropped = filter_blocked(r.json()["results"], blocklist)
    web = [
        {"title": h["title"], "url": h["url"], "contents": {"highlights": [h["snippet"]]}}
        for h in hits
    ]
    return SearchResponse(
        content="\n\n".join(
            f"[{w['title']}]({w['url']})\n{w['contents']['highlights'][0]}" for w in web
        ),
        cost_usd=0.005,
        n_results=len(web),
        latency_ms=round((time.monotonic() - started) * 1000),
        counters={"contamination_drops": dropped},
        raw={"results": {"web": web}},
    )
```

Then add it to `PROVIDERS` in the same file:

```python
"acme": Provider(search=acme_search, api_key_env="ACME_API_KEY", exclusion=EXCLUSION_API),
```

and run `make bench PROVIDER="you_knowledge acme"` to compare it against You.com + Knowledge.

- `content` is what the agent reads, and `raw["results"]["web"]` in the shape above is what shows up in `details.jsonl` and `make bench-show`.
- `exclusion` records how the provider honors `exclude_domains`: `EXCLUSION_API` for an API parameter, `EXCLUSION_QUERY` for `-site:` operators, or `EXCLUSION_NONE`.
- Raise on HTTP errors, as `raise_for_status()` does, so that throttling is retried.

## Tests

`make test` runs the offline suite; it needs no API keys.

## Attribution

- **VerticalRTK** by [Tako](https://github.com/TakoData/VerticalRTK), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Fetched from GitHub at run time and not redistributed here. `queries.py` downloads `data/verticalrtk_fast.jsonl` at the pinned commit and maps `query` to `input`, `answer` to `expected`, and `vertical` and `as_of` into `metadata`; no question or answer text is changed. Each run's `manifest.json` records the URL, commit and sha256 of the file it used. The repository also has an earlier 131-question set, which its authors ask to be scored separately, so only the fast set is used.
- **Judge rubric** from [FinSearchComp](https://huggingface.co/datasets/ByteSeedXpert/FinSearchComp) ([paper](https://arxiv.org/abs/2509.13160)), CC BY 4.0. The files in [`prompts/`](prompts) are byte-identical to the dataset, which has two template variants that differ only by a fullwidth colon; the majority variant is included. The numeric-form rule is appended in code (`config.JUDGE_NORMALIZATION_RULE`), so the files stay unmodified and the change shows up in the manifest's `judge_prompt_sha`.
- **[Stirrup](https://github.com/ArtificialAnalysis/Stirrup)** by Artificial Analysis, MIT. Installed as a pinned dependency (the `bench` group in `pyproject.toml`), not vendored.
