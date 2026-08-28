"""
Integration tests (Фаза 1, plans/testing-plan-minimum.md) for the LLM-backed
routes: contract only (status code + response shape + LLM adapter called),
never a real LLM call. `fake_llm_adapter` (tests/conftest.py) returns a fixed
string; RAG search silently returns [] because the network-lockdown fixture
blocks the real Supabase RPC call (both are caught by broad `except Exception`
in app/services/search_service.py, so this degrades quietly, not with an
error) — exactly the point: neither the LLM nor the RAG backend is real here.

get_llm_adapter is bound in 4 different module namespaces (imported at
module level in analysis_service.py, synastry_service.py, and
synastry_relationship_service.py; imported locally in some functions of
analysis_service.py, which resolves from the origin module at call time) —
`patch_llm_adapter` below patches all of them so it doesn't matter which
pattern a given endpoint's service function happens to use.

Natal/progressed/transit chart data is built with the real, deterministic
astrology functions (app/utils/astrology_v2.py) rather than hand-written
fixture dicts — same data shape production code would build, no guessing.

Every route that takes an explicit `language` field is parametrized over all
3 supported languages (ru/en/uk) via the `language` fixture below — not just
`ru`. This exercises app/services/text_verification.py's anti-fabrication
checks (find_fabricated_positions_layered, find_undercovered_aspects_generic,
etc.) in all 3 of their language branches against real calculated aspect
data; the fake LLM reply naturally won't "cover" any of them, so a
"[...] Undercovered aspects detected" line printed under `-s` for every one
of these tests is expected noise from that real, unmodified production code
path — not a test failure and not something to silence, since the checks
themselves are exactly what should run for real.

Intentionally NOT covered here: the event-chart daily forecast endpoint
(see app/services/README.md for why it's a separate system from the routes
below) — out of scope for this file.
"""
import pytest
from datetime import datetime

from app.utils.astrology_v2 import (
    calculate_planet_positions,
    calculate_aspects,
    calculate_secondary_progressions,
    calculate_transits,
    calculate_progressed_synastry,
)

BIRTH_DATE = datetime(1990, 6, 15, 14, 30)
LAT, LON = 50.4501, 30.5234
TZ = "Europe/Kyiv"

LANGUAGES = ["ru", "en", "uk"]


@pytest.fixture(params=LANGUAGES)
def language(request):
    return request.param


def _build_natal_chart_dict():
    chart = calculate_planet_positions(
        birth_date=BIRTH_DATE, birth_place="Kyiv, Ukraine", lat=LAT, lon=LON,
        timezone_str=TZ, house_system="Placidus",
    )
    aspects = calculate_aspects(chart["planets"])
    return {
        "sun_sign": chart["sun_sign"], "sun_sign_ru": chart["sun_sign_ru"],
        "moon_sign": chart["moon_sign"], "moon_sign_ru": chart["moon_sign_ru"],
        "ascendant": chart["ascendant"], "ascendant_ru": chart["ascendant_ru"],
        "mc": chart["mc"], "mc_ru": chart["mc_ru"],
        "planets": chart["planets"],
        "houses": {str(k): v for k, v in chart["houses"].items()},
        "houses_meta": chart.get("houses_meta", {}),
        "meta": chart.get("meta", {}),
        "aspects": aspects,
    }


@pytest.fixture(autouse=True)
def patch_llm_adapter(monkeypatch, fake_llm_adapter):
    for module_path in (
        "app.services.llm_adapter",
        "app.services.analysis_service",
        "app.services.synastry_service",
        "app.services.synastry_relationship_service",
    ):
        module = __import__(module_path, fromlist=["get_llm_adapter"])
        monkeypatch.setattr(module, "get_llm_adapter", lambda *a, **kw: fake_llm_adapter)
    return fake_llm_adapter


NATAL_BIRTH_FIELDS = {
    "birth_date": "1990-06-15T00:00:00",
    "birth_time": "14:30",
    "birth_place": "Kyiv, Ukraine",
    "latitude": LAT,
    "longitude": LON,
    "timezone": TZ,
}


def test_synastry_aspect(client, patch_llm_adapter, language):
    payload = {
        "planet1": "Sun", "planet2": "Moon", "aspect_name": "Trine",
        "orb": 2.0, "language": language,
    }

    resp = client.post("/api/synastry/aspect", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply
    assert len(patch_llm_adapter.calls) == 1


# /analysis/query and /analysis/query-with-chart have no `language` request
# field — language is auto-detected from the query text itself
# (app/services/search_service.py:detect_query_language), and that detector
# only ever returns 'ru' or 'en': any Cyrillic character (which includes
# Ukrainian text — Ukrainian and Russian share the Ѐ-ӿ range) maps
# to 'ru', so there is no query text that makes it return 'uk'. These two
# tests cover both of the detector's actual outcomes instead of looping over
# LANGUAGES.
@pytest.mark.parametrize("query, expected_language", [
    ("Saturn in 7th house", "en"),
    ("Сатурн в 7 доме", "ru"),
])
def test_analysis_query(client, patch_llm_adapter, query, expected_language):
    resp = client.post("/api/analysis/query", json={"query": query})

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply
    assert body["query"] == query
    assert body["query_language"] == expected_language


def test_analysis_query_with_chart(client, patch_llm_adapter):
    payload = {"query": "Sun conjunct Moon", "chart_data": NATAL_BIRTH_FIELDS}

    resp = client.post("/api/analysis/query-with-chart", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply
    assert body["chart_data"] is not None


def test_analysis_planet(client, patch_llm_adapter, language):
    payload = {"planet": "Venus", "sign": "Taurus", "degree": 12.5, "house": 2, "language": language}

    resp = client.post("/api/analysis/planet", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply


def test_analysis_full(client, patch_llm_adapter, language):
    payload = {**NATAL_BIRTH_FIELDS, "language": language}

    resp = client.post("/api/analysis/full", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply
    assert body["language"] == language


def test_generate_summary(client, patch_llm_adapter, language):
    resp = client.post("/api/generate-summary", json={"text": "Some long analysis text.", "language": language})

    assert resp.status_code == 200
    assert resp.json() == {"summary": patch_llm_adapter.reply}


def test_analysis_chat(client, patch_llm_adapter, language):
    payload = {
        "question": "What does my Venus placement mean?",
        "chart_data": {},
        "summary": "Short summary of the chart.",
        "language": language,
    }

    resp = client.post("/api/analysis/chat", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == patch_llm_adapter.reply


def test_analysis_synastry_full(client, patch_llm_adapter, language):
    payload = {
        "chart1": NATAL_BIRTH_FIELDS,
        "chart2": {**NATAL_BIRTH_FIELDS, "birth_date": "1992-03-10T00:00:00"},
        "language": language,
    }

    resp = client.post("/api/analysis/synastry/full", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply


def test_synastry_relationship_types(client, patch_llm_adapter, language):
    resp = client.post(
        "/api/synastry/relationship-types",
        json={"full_analysis": "Some finished synastry analysis text.", "language": language},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply


def test_analysis_progressions(client, patch_llm_adapter, language):
    natal_chart = _build_natal_chart_dict()
    payload = {**NATAL_BIRTH_FIELDS, "natal_chart": natal_chart, "language": language}

    resp = client.post("/api/analysis/progressions", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply


def test_analysis_transits(client, patch_llm_adapter, language):
    natal_chart = _build_natal_chart_dict()
    payload = {**NATAL_BIRTH_FIELDS, "natal_chart": natal_chart, "language": language}

    resp = client.post("/api/analysis/transits", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply


def test_analysis_progressed_synastry(client, patch_llm_adapter, language):
    payload = {
        "chart1": NATAL_BIRTH_FIELDS,
        "chart2": {**NATAL_BIRTH_FIELDS, "birth_date": "1992-03-10T00:00:00"},
        "language": language,
    }

    resp = client.post("/api/analysis/progressed-synastry", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply


def test_analysis_progressed_synastry_aspect(client, patch_llm_adapter, language):
    payload = {
        "planet1": "Sun", "planet2": "Moon", "aspect_name": "Trine",
        "layer": "progressed", "language": language,
    }

    resp = client.post("/api/analysis/progressed-synastry/aspect", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == patch_llm_adapter.reply
