"""
Performance/concurrency tests (Фаза 3, plans/testing-plan-minimum.md).

Opt-in only: pytest.ini's `addopts = -m "not perf"` excludes this file from
the default run. Invoke explicitly: `pytest -m perf tests/test_perf.py`.

Thresholds are set with a generous (~3x) margin over what was measured on a
2026 dev laptop specifically so they catch a several-times regression, not
normal machine-to-machine variance — see plans/testing-plan-minimum.md,
"Flaky перф-пороги" risk.
"""
import asyncio
import statistics
import time
from datetime import datetime

import httpx
import pytest

from app.main import app
from app.utils.astrology_v2 import calculate_planet_positions, calculate_progressed_synastry

pytestmark = pytest.mark.perf

LAT, LON, TZ = 50.4501, 30.5234, "Europe/Kyiv"
BIRTH_DATE = datetime(1990, 6, 15, 14, 30)

NATAL_FIELDS = {
    "birth_date": "1990-06-15T00:00:00",
    "birth_time": "14:30",
    "birth_place": "Kyiv, Ukraine",
    "latitude": LAT,
    "longitude": LON,
    "timezone": TZ,
    "house_system": "Placidus",
}
PARTNER_FIELDS = {**NATAL_FIELDS, "birth_date": "1992-03-10T00:00:00"}

N_RUNS = 20
# Measured median on a 2026 dev laptop was well under 100ms; 3x margin.
PLANET_POSITIONS_MEDIAN_BUDGET_S = 0.3


def test_calculate_planet_positions_median_budget():
    durations = []
    for _ in range(N_RUNS):
        start = time.perf_counter()
        calculate_planet_positions(
            birth_date=BIRTH_DATE, birth_place="Kyiv, Ukraine", lat=LAT, lon=LON,
            timezone_str=TZ, house_system="Placidus",
        )
        durations.append(time.perf_counter() - start)

    median = statistics.median(durations)
    print(f"\n  calculate_planet_positions over {N_RUNS} runs:")
    print(f"  min={min(durations)*1000:.2f}ms  median={median*1000:.2f}ms  max={max(durations)*1000:.2f}ms"
          f"  | budget={PLANET_POSITIONS_MEDIAN_BUDGET_S*1000:.0f}ms")
    assert median < PLANET_POSITIONS_MEDIAN_BUDGET_S, (
        f"calculate_planet_positions median {median:.3f}s exceeds budget "
        f"{PLANET_POSITIONS_MEDIAN_BUDGET_S}s over {N_RUNS} runs — possible perf regression"
    )


PROGRESSED_SYNASTRY_MEDIAN_BUDGET_S = 1.5


def test_calculate_progressed_synastry_median_budget():
    person1 = {
        "birth_date": BIRTH_DATE, "birth_place": "Kyiv, Ukraine",
        "lat": LAT, "lon": LON, "timezone": TZ,
    }
    person2 = {
        "birth_date": datetime(1992, 3, 10, 14, 30), "birth_place": "Kyiv, Ukraine",
        "lat": LAT, "lon": LON, "timezone": TZ,
    }

    durations = []
    for _ in range(N_RUNS):
        start = time.perf_counter()
        calculate_progressed_synastry(person1=person1, person2=person2, house_system="Placidus")
        durations.append(time.perf_counter() - start)

    median = statistics.median(durations)
    print(f"\n  calculate_progressed_synastry over {N_RUNS} runs:")
    print(f"  min={min(durations)*1000:.2f}ms  median={median*1000:.2f}ms  max={max(durations)*1000:.2f}ms"
          f"  | budget={PROGRESSED_SYNASTRY_MEDIAN_BUDGET_S*1000:.0f}ms")
    assert median < PROGRESSED_SYNASTRY_MEDIAN_BUDGET_S, (
        f"calculate_progressed_synastry median {median:.3f}s exceeds budget "
        f"{PROGRESSED_SYNASTRY_MEDIAN_BUDGET_S}s over {N_RUNS} runs — possible perf regression"
    )


CONCURRENCY = 50
P95_BUDGET_S = 5.0


@pytest.mark.anyio
async def test_chart_calculate_handles_50_concurrent_requests():
    """POST /api/chart/calculate has no auth and no rate limit (see
    plans/testing-plan-minimum.md's route table) — the cleanest route to
    load without fighting slowapi. Closes plans/concurrency-100-plus-users.md's
    concern with a repeatable check: no errors, no deadlock, bounded p95."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:

        async def one_request():
            start = time.perf_counter()
            resp = await client.post("/api/chart/calculate", json=NATAL_FIELDS)
            return resp.status_code, time.perf_counter() - start

        results = await asyncio.gather(*[one_request() for _ in range(CONCURRENCY)])

    statuses = [status for status, _ in results]
    durations = [duration for _, duration in results]

    assert all(status == 200 for status in statuses), f"non-200 statuses: {statuses}"

    durations.sort()
    p95_index = int(len(durations) * 0.95)
    p95 = durations[min(p95_index, len(durations) - 1)]
    assert p95 < P95_BUDGET_S, f"p95 latency {p95:.2f}s exceeds budget {P95_BUDGET_S}s under {CONCURRENCY} concurrent requests"
