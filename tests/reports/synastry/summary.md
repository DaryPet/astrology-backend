# Synastry: old vs new — comparison

The shared astrological input (natal + aspects) is identical for both variants — the comparison is isolated to the RAG/prompt/LLM layer. Pair: `tests/data/synastry_eval_pair.json`. Runs: 3 old / 3 new.

**old** = fcca162 (before this branch's changes): top 5 aspects in RAG search, book chunks truncated to 200/150 chars, `deepseek-v4-flash`, `temperature=1`.

**new** = working tree: all ~51 aspects in RAG search, full book chunks, `deepseek-v4-pro`, `temperature=0.3`, cross-check and auto-fix of hallucinated planet positions.


## Table

| Metric | old | new |
|---|---|---|
| Runs (errors) | 3 (0) | 3 (0) |
| Generation time, sec (avg) | 170.69 | 274.53 |
| Response length, chars (avg) | 40302.33 | 44086.33 |
| Input, tokens (estimate, avg) | 6922 | 160922.33 |
| Output, tokens (estimate, avg) | 10075 | 11021 |
| Coverage: % aspects with in-depth analysis | 58.17% | 68.63% |
| Coverage: % aspects mentioned+analyzed | 78.47% | 68.63% |
| Coverage: missing aspects (avg) | 11 | 16 |
| LLM judge: book fidelity, 1-5 | 2.33 | 2.33 |
| LLM judge: analysis depth, 1-5 | 2 | 2 |
| LLM judge: contradictions with book (sum over runs) | 1 | 5 |


## Limitations

- The judge (`gpt-4o`) scores a sample every 3rd aspect (~17 of them), not the full list — to save tokens, same principle as in the event-chart evals (a full-sample run can be added separately if needed).
- 3 runs per variant — with `temperature>0` there is run-to-run variance, statistical significance at this sample size is limited (see plans/event-chart-tests-and-evals.md, "Limitations").
- The judge itself can be wrong just like the model being scored — numeric verdicts don't replace a spot-check human audit, they only narrow down what to look at by hand.


## By run


### old

- run 1: 188.3s, 47386 chars, coverage=41.2% (missing=4), fidelity=2, depth=2
  - judge: Most aspects are discussed in a template way without concrete support from the book fragments. Some aspects are not discussed at all or contradict the stated aspect.
- run 2: 140.6s, 31530 chars, coverage=64.7% (missing=17), fidelity=3, depth=2
  - judge: The analysis is often unsupported by the book fragments, but doesn't contradict them. Analysis depth varies, often lacking aspect-specific detail.
- run 3: 183.2s, 41991 chars, coverage=68.6% (missing=12), fidelity=2, depth=2
  - judge: Many aspects are not discussed in the text, and those that are discussed are often not confirmed by the book fragments. Analysis depth is mostly template-like, with rare exceptions.

### new

- run 1: 334.1s, 49774 chars, coverage=66.7% (missing=17), fidelity=2, depth=2
  - judge: Most aspects are not discussed in the text or are discussed without chart-specific detail. Groundedness is often absent, since the book fragments don't confirm the analysis.
- run 2: 230.1s, 39558 chars, coverage=64.7% (missing=18), fidelity=3, depth=2
  - judge: The analysis often doesn't match the aspects (e.g. aspect confusion), and many aspects are not discussed. Where there is discussion, it is often template-like and lacks chart-specific detail.
- run 3: 259.4s, 42927 chars, coverage=74.5% (missing=13), fidelity=2, depth=2
  - judge: Many aspects are not discussed or are described incorrectly. Lack of specificity or contradictions in aspect descriptions occur frequently.
