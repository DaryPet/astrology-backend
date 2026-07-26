# Synastry: eval 2 — model-effect (pro vs flash), same fixture

Continuation of eval 1 (`tests/reports/synastry/summary.md`). Same pair
(`tests/reports/synastry/chart_input.json` — Test User 1990 Moscow + nf 1982
Dobropillya), same code (all ~51 aspects, full chunks), **only the model
was switched back to `deepseek-v4-flash`** — isolates the model-effect from
the volume-effect. `old` was not re-run — the runs from eval 1 were reused
(same code, same fixture).

Judge: **Claude (Sonnet 5, this same session)** instead of gpt-4o — read the
sample (every 3rd aspect, 17 of 51) by hand using the same structure
(`tests/judge_synastry.py::build_sample`), no API call.

## Table (averages over 3 runs)

| Variant | Time, s | Input tok. | Covered % | Missing | Fidelity 1-5 | Depth 1-5 |
|---|---|---|---|---|---|---|
| old — flash, 5 asp., truncated (judge gpt-4o) | 166.1 | 6,922 | 60.8% | 8.3 | 2.3 | 2 |
| new-pro — all asp., full chunks (judge gpt-4o) | 268.9 | 160,922 | 75.8% | 11.7 | 2.3 | 2 |
| new-flash — all asp., full chunks (judge Claude) | 156.0 | 163,172 | 71.9% | 7.7 | 2 | 2.7 |

**Fidelity/Depth cannot be compared directly between old/new-pro and
new-flash — different judges (gpt-4o vs Claude), different strictness
calibration.** Time, tokens, coverage — fairly comparable, judge-independent.

## What the comparable metrics show

- **new-flash is the fastest of all three** (156s), faster even than the old
  code (166s), while discussing all 51 aspects instead of 5. Flash is simply
  faster than pro on its own, given the same prompt volume.
- **new-flash coverage (71.9%) is close to new-pro (75.8%)**, both notably
  higher than old (60.8%). This confirms the eval 1 conclusion: the coverage
  gain comes from removing the `[:5]` slice and chunk truncation
  (volume/prompt), not the model itself — flash barely lags behind pro at
  the same volume.
- **Missing** is quite noisy across new-flash runs (3, 3, 17 — average 7.7)
  — one run (run 3) came out noticeably weaker than the other two. At n=3
  this is expected, not a reason to conclude "flash is less stable" — more
  runs are needed to state that with confidence.
- **Aspect-type hallucinations**: new-flash caught 1 of 3 runs (33%,
  `find_fabricated_aspect_types`), the same proportion as old (1/3) and
  new-pro (1/3, just a different pair). Switching models doesn't remove this
  error — looks like a structural problem with the prompt itself (asking to
  discuss 51 aspects in one text), not a weakness of a specific model.
- **Grounded (actually confirmed by the book) = 0 across all three
  variants**, regardless of model/volume/judge. Looks like a ceiling of the
  corpus itself — the book simply doesn't cover most specific planet pairs
  granularly enough, and this isn't fixed by volume or model choice.

## Known limitation of the measurement itself

The paragraph extractor for a pair (`find_paragraph_for_pair`) for dense
"nodal" blocks (several Chiron/Node aspects discussed together in one
chunk) sometimes still grabs the **wrong** directed pair via the fallback —
occurred in 3 of 51 sampled items in this run (see `*.judge.json`, noted in
the note field). Not model confusion — measurement confusion; such cases
are scored as "missing", not as substantive discussion.

## Files

- `raw/new_flash_{1,2,3}.json` — full text
- `raw/new_flash_{1,2,3}.coverage.json` — coverage across all 51 aspects
- `raw/new_flash_{1,2,3}.judge.json` — verdict on the sample (17/51), judge Claude
- `raw/new_flash_{1,2,3}.sample_for_claude_judge.json` — what exactly the judge read
