# Daily forecast — which system is actually running

`daily_forecast_service.py` has gone through three distinct scoring
approaches. Only the third one is live on this branch. Read this before
touching the file, so you don't assume behavior from an older version.

## READ FIRST — two different forecasts, do not confuse them

The product has **two** things called "daily forecast". They share almost no
logic. Nearly every wrong turn taken on this file started by reading the
wrong one.

| | Personal daily forecast | **Event chart** |
|---|---|---|
| For | one person's day | one match |
| Built on | the user's **natal chart** + transits to it | **only** the moment and place of kick-off |
| Needs birth data | yes | **no** |
| Output | personal daily reading | favourite / underdog / draw, in roles only |

**Event chart never involves a natal chart and never involves transits.** It
is a single chart cast for one instant at one location.

The naming actively misleads. `judge_event_chart` takes arguments called
`transit_houses` / `transit_planets`, and `calculate_transits` is called with
`birth_date=target_date`. Both are legacy names on a shared utility: passing
the match moment as both `birth_date` and `target_date` is simply how you get
a chart for one instant. No natal chart is built and none is scored. See the
comments at `app/api/endpoints.py:2086-2087` and `:2110-2111`.

Event-chart entry point and the exact production call chain:
`app/api/endpoints.py:2055-2108` → `judge_event_chart()`.

Input is only: kick-off time (local, naive), its timezone, and the place
(string for the geocoder, or explicit lat/lon). `exact_time=True` is
mandatory — without it a `00:00` kick-off is silently shifted to noon.

## What does NOT participate in the event chart

**LLM — not called.** Verdict text is fully deterministic, built from the
computed testimony list. `generation_mode: 'deterministic'` in the response
records this; see the comment at `daily_forecast_service.py:1870`. The
`llm_provider` / `llm_model` response fields are echo for the frontend and
invoke nothing.

**The book — does not affect scoring.** RAG over the reference book still
runs (`search_chunks_priority_book`, `daily_forecast_service.py:1780-1790`),
but only *after* `judge_event_chart()` has finished scoring, and only to
attach supporting quotes to `rag_sources`. It cannot change a weight or a
verdict. `source='mixed'` testimonies are excluded from it outright.

For evals and tests, call `judge_event_chart()` directly: it is synchronous
and pure — no book, no LLM, no network, no cache. See
`plans/event-chart-tests-and-evals.md`.

## 1. Old natal-transit method (replaced, not in this branch)

The original `/daily-forecast` scored a day by running transits against the
user's **natal chart** (`birth_date`/`natal_chart` were required inputs).
This is what shipped before `feat/improve-daily-prompt`. It no longer exists
in this file — mentioned here only so old API docs/clients referencing
`birth_date`/`natal_chart` as required make sense historically.

## 2. Pure event-chart method (John Frawley, *Sports Astrology*, ch. 2)

Replaced #1. Builds a chart for the **time and place the match starts**
(Placidus), not the athlete's birth chart. Lord 1/10 = favourite, Lord 7/4 =
underdog. Scoring comes only from what ch. 2 allows: significator placement
within 2-3° of cusps 1/10/7/4, the Moon's final applying aspect, the
antiscion of the Part of Fortune, its dispositor, the Nodes, combustion,
outer planets. The book is explicit that essential dignity, accidental
dignity (angularity), and retrogradation do **not** apply to event charts —
this method follows that rule strictly.

Spec: `specs/daily_forecast_event_chart_plan.md`.

In the code, these testimonies are tagged `source='book'` and are the ones
the RAG lookup (`search_chunks_priority_book`, book id=30) is allowed to
fetch supporting quotes for.

## 3. Hybrid method (current, live on this branch)

Method #2 plus a second layer the book explicitly tells you not to add:
classical (horary, ch.1-style) evaluation of **Lord 1 and Lord 7 only**
(never Lord 10/4) — essential dignity (domicile/exaltation/detriment/fall)
and the strength of their own house. This is a deliberate, evidence-based
departure from the book's "don't mix the methods" rule: real-match testing
showed the hybrid version predicts better than the pure ch. 2 method alone.

### House-strength model: two schools, we use School B

There are two plausible classical house-strength systems for the hybrid
layer, and they disagree on several houses. Worth knowing both, because an
earlier revision on this branch used School A and got it wrong.

**School A — Lilly's full accidental-dignity table** (*Christian Astrology*).
Every house gets its own graduated point value: 1st/10th strongest, 7th/4th/
11th good, 2nd/5th fair, 9th mildly positive, 3rd very mildly positive, and
only 6th/8th/12th negative. In this school the 9th and 11th are "houses of
good fortune/good spirit" and get a small bonus.

**School B — the simple 3-tier scheme** (angular/succedent/cadent + an
explicit 8th-house exception). Angular houses (1/4/7/10) = bonus, succedent
houses (2/5/8/11) = neutral ("no bonus"), cadent houses (3/6/9/12) =
weakness/penalty. But with one explicit override: the 8th house, although
formally succedent, is always treated separately and harshly as "the house
of death" — worse than an ordinary succedent house. So School B gives the
9th and 11th **no** bonus at all: 11th is neutral, 9th (cadent) is already a
penalty.

**We use School B.** All three real reference examples the product owner
tested behave exactly like School B: 11th = "no bonus" (neutral, not
positive), 9th = "weak penalty" (negative, not positive), 8th = its own
severe penalty, angular = bonus (and an angular house that's also the
significator's own numbered house — e.g. Lord 7 sitting in the 7th — stacks
an extra "own house" bonus on top, shown as ⭐⭐ in the Umag example).
School A (the full Lilly table) was tried first on this branch, scored
9th/11th as positive, and was replaced once it stopped matching reference
output. `HOUSE_STRENGTH`, `ANGULAR_HOUSES`/`CADENT_HOUSES`/`EIGHTH_HOUSE` in
the code implement School B.

### The enemy-house override — angular is not always a bonus

School B as described above was **incomplete**, and the gap flipped verdicts.
"Angular = bonus" was applied without checking *whose* angular house the
significator sits in.

The 7th is the underdog's house and the 1st is the favourite's. A significator
standing in the opposing side's angular house is not strengthened by it — it
is in the opponent's territory and is **penalised**:

- Lord 1 in houses 1 / 4 / 10 → bonus. Lord 1 in the **7th** → penalty.
- Lord 7 in houses 7 / 4 / 10 → bonus. Lord 7 in the **1st** → penalty.

Implemented as `ENEMY_HOUSE = {1: 7, 7: 1}` and `HOUSE_STRENGTH_ENEMY` in
`daily_forecast_service.py`; all house weighting now goes through
`_house_weight(house_num, lord_house)`. The `house_mark` for such a placement
is ⚠️, not ⭐.

Found on a real chart where Mars (Lord 1) sat in the 7th: the missing rule
scored it `+1.75` for the favourite instead of a penalty, and the verdict came
out "favourite wins" when the correct reading was "underdog". `_house_phrase`
already computed whether the house was the significator's own, but used the
result only to append a text suffix — the weight ignored it entirely.

These testimonies are tagged `source='mixed'` and are **not** looked up via
RAG — the book actively argues against them, so a RAG search would surface
contradicting quotes.

Full rationale, weight choices, and the correction history: see
`../../plans/daily-forecast-hybrid-method.md` at the project root.

## Where each system's rules live in code

- `judge_event_chart()` — orchestrates both layers, returns testimonies +
  `significator_card`.
- `_outer_planet_testimonies`, `_fortuna_aspect_testimonies`,
  `_moon_aspect_events`, section A/B/C/D/E/F in `judge_event_chart` — ch. 2
  (system #2).
- `_mixed_method_testimonies`, `_lord_profile`, `_house_phrase_ru`,
  `_dignity_phrase_ru` — hybrid layer (system #3).
- The response has **no numeric score/category** by product decision — only
  qualitative `match_type` and the rendered significator card/testimony
  text. Don't reintroduce a 1-10 score field without checking with product
  first.
