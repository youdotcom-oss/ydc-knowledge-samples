# Benchmarks

<!-- TODO: fill in before launch. Everything below is a template. -->

How You.com Knowledge compares with web-only search APIs on questions that need structured, real-time data.

Set up the repo first. See [Setup](../README.md#setup) in the root README.

## Overview

<!-- TODO: what Vertical RTK is, where the questions come from, and where web-only search tops out. -->

**Benchmark:** Vertical RTK

**Headline:** TODO

## Methodology

<!-- TODO -->

- **What's measured:** accuracy vs. server-side query time.
- **Comparison set:** You.com Search with `knowledge="core"`, Parallel Advanced, Perplexity, and TODO.
- **Questions:** TODO (count, domains, how they were selected).
- **Grading:** TODO (grader model or rubric, and how answers are matched against ground truth).
- **Settings:** TODO (per-provider parameters, run dates, SDK and model versions).

## Results

<!-- TODO: chart (accuracy vs. server-side query time) -->

| Provider | Accuracy | Server-side query time |
| --- | --- | --- |
| You.com Search + Knowledge | TODO | TODO |
| Parallel Advanced | TODO | TODO |
| Perplexity | TODO | TODO |

Download the structured results: TODO (link to results file).

## Reproduce

<!-- TODO: harness location and commands -->

```bash
# TODO: e.g. make bench
```

## Caveats

<!-- TODO: dataset bias toward the licensed-data domains Knowledge covers, the fact that live data drifts between runs, and anything excluded from the comparison. -->
