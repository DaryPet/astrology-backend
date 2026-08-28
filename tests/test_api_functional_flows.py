"""
Functional/e2e tests (Фаза 2, plans/testing-plan-minimum.md): multi-step
scenarios chaining several endpoints through one TestClient, the way the
frontend actually calls the API. Deterministic steps use real astrology
math; LLM steps use `fake_llm_adapter` (never a real LLM call — see
tests/test_api_llm_routes.py for why).

Not covered here (out of scope): the event-chart daily forecast endpoint.
"""
import pytest

pytestmark = pytest.mark.functional

LAT, LON, TZ = 50.4501, 30.5234, "Europe/Kyiv"

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


def test_geocode_then_chart_then_full_analysis(client, patch_llm_adapter):
    """geocode/coordinates -> chart/calculate -> analysis/full, the natal
    chart screen's real call sequence."""
    tz_resp = client.get("/api/geocode/coordinates", params={"lat": LAT, "lon": LON})
    assert tz_resp.status_code == 200
    timezone = tz_resp.json()["timezone"]

    chart_resp = client.post(
        "/api/chart/calculate",
        json={**NATAL_FIELDS, "timezone": timezone},
    )
    assert chart_resp.status_code == 200
    chart = chart_resp.json()
    assert "planets" in chart

    analysis_resp = client.post(
        "/api/analysis/full",
        json={**NATAL_FIELDS, "timezone": timezone, "language": "ru"},
    )
    assert analysis_resp.status_code == 200
    assert analysis_resp.json()["analysis"] == patch_llm_adapter.reply


def test_chart_then_synastry_direct_then_aspect(client, patch_llm_adapter):
    """chart/calculate (x2, sanity) -> synastry/direct -> synastry/aspect."""
    c1 = client.post("/api/chart/calculate", json=NATAL_FIELDS)
    c2 = client.post("/api/chart/calculate", json=PARTNER_FIELDS)
    assert c1.status_code == 200 and c2.status_code == 200

    synastry_resp = client.post(
        "/api/synastry/direct",
        json={"chart1": NATAL_FIELDS, "chart2": PARTNER_FIELDS},
    )
    assert synastry_resp.status_code == 200

    aspect_resp = client.post(
        "/api/synastry/aspect",
        json={"planet1": "Sun", "planet2": "Moon", "aspect_name": "Trine", "language": "en"},
    )
    assert aspect_resp.status_code == 200
    assert aspect_resp.json()["analysis"] == patch_llm_adapter.reply


def test_progressions_then_progressions_analysis(client, patch_llm_adapter):
    """progressions -> analysis/progressions, passing the first call's result
    straight into the second (progression_data), as the frontend does."""
    prog_resp = client.post("/api/progressions", json=NATAL_FIELDS)
    assert prog_resp.status_code == 200
    progression_data = prog_resp.json()

    chart_resp = client.post("/api/chart/calculate", json=NATAL_FIELDS)
    assert chart_resp.status_code == 200
    natal_chart = chart_resp.json()

    analysis_resp = client.post(
        "/api/analysis/progressions",
        json={
            **NATAL_FIELDS,
            "progression_data": progression_data,
            "natal_chart": natal_chart,
            "language": "ru",
        },
    )
    assert analysis_resp.status_code == 200
    assert analysis_resp.json()["analysis"] == patch_llm_adapter.reply


def test_progressed_synastry_then_analysis_then_aspect(client, patch_llm_adapter):
    """progressed-synastry -> analysis/progressed-synastry -> .../aspect."""
    calc_resp = client.post(
        "/api/progressed-synastry",
        json={"chart1": NATAL_FIELDS, "chart2": PARTNER_FIELDS},
    )
    assert calc_resp.status_code == 200

    analysis_resp = client.post(
        "/api/analysis/progressed-synastry",
        json={"chart1": NATAL_FIELDS, "chart2": PARTNER_FIELDS, "language": "ru"},
    )
    assert analysis_resp.status_code == 200
    assert analysis_resp.json()["analysis"] == patch_llm_adapter.reply

    aspect_resp = client.post(
        "/api/analysis/progressed-synastry/aspect",
        json={
            "planet1": "Sun", "planet2": "Moon", "aspect_name": "Trine",
            "layer": "progressed", "language": "ru",
        },
    )
    assert aspect_resp.status_code == 200
    assert aspect_resp.json()["analysis"] == patch_llm_adapter.reply


def test_synastry_aspect_stream_returns_sse_frames(client, patch_llm_adapter):
    """stream: true must return an SSE response with the stage/.../final
    event contract (app/services/synastry_service.py:626-633), not plain
    JSON — the format the frontend's EventSource-style client expects."""
    resp = client.post(
        "/api/synastry/aspect",
        json={
            "planet1": "Sun", "planet2": "Moon", "aspect_name": "Trine",
            "language": "en", "stream": True,
        },
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "event: stage" in resp.text
    assert "event: final" in resp.text
