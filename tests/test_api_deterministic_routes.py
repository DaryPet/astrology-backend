"""
Integration tests (Фаза 1, plans/testing-plan-minimum.md) for the 8
deterministic (non-LLM) routes: happy-path, validation, and — where the
route is protected — the auth boundary.

All requests pass latitude/longitude directly so the endpoints never need to
geocode a place name (see app/api/endpoints.py:684-703): no real network call
is possible, and the `_no_real_network` autouse fixture (tests/conftest.py)
would fail the test loudly if one were attempted anyway.
"""
import pytest

KYIV = {"latitude": 50.4501, "longitude": 30.5234, "timezone": "Europe/Kyiv"}

NATAL_PAYLOAD = {
    "birth_date": "1990-06-15T00:00:00",
    "birth_time": "14:30",
    "birth_place": "Kyiv, Ukraine",
    "house_system": "Placidus",
    **KYIV,
}


def _natal_payload(**overrides):
    payload = dict(NATAL_PAYLOAD)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# POST /api/chart/calculate — no auth, no rate limit
# ---------------------------------------------------------------------------
class TestChartCalculate:
    def test_happy_path(self, client):
        resp = client.post("/api/chart/calculate", json=_natal_payload())

        assert resp.status_code == 200
        body = resp.json()
        for key in ("sun_sign", "moon_sign", "ascendant", "mc", "planets", "houses", "aspects"):
            assert key in body
        assert isinstance(body["planets"], dict)
        assert isinstance(body["aspects"], list)

    def test_missing_required_field_is_422(self, client):
        payload = _natal_payload()
        del payload["birth_date"]

        resp = client.post("/api/chart/calculate", json=payload)

        assert resp.status_code == 422

    def test_no_place_and_no_coordinates_is_400(self, client):
        payload = _natal_payload(birth_place="", latitude=None, longitude=None)

        resp = client.post("/api/chart/calculate", json=payload)

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/synastry/direct — no auth, no rate limit
# ---------------------------------------------------------------------------
class TestSynastryDirect:
    def test_happy_path(self, client):
        payload = {"chart1": _natal_payload(), "chart2": _natal_payload(birth_date="1992-03-10T00:00:00")}

        resp = client.post("/api/synastry/direct", json=payload)

        assert resp.status_code == 200

    def test_missing_chart2_is_422(self, client):
        resp = client.post("/api/synastry/direct", json={"chart1": _natal_payload()})

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/progressions — auth required, 15/min
# ---------------------------------------------------------------------------
class TestProgressions:
    def test_happy_path(self, client):
        resp = client.post("/api/progressions", json=_natal_payload())

        assert resp.status_code == 200

    def test_missing_birth_date_is_422(self, client):
        payload = _natal_payload()
        del payload["birth_date"]

        resp = client.post("/api/progressions", json=payload)

        assert resp.status_code == 422

    def test_without_auth_is_403(self, unauthenticated_client):
        resp = unauthenticated_client.post("/api/progressions", json=_natal_payload())

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/transits — auth required, 20/min
# ---------------------------------------------------------------------------
class TestTransits:
    def test_happy_path(self, client):
        resp = client.post("/api/transits", json=_natal_payload())

        assert resp.status_code == 200

    def test_missing_birth_date_is_422(self, client):
        payload = _natal_payload()
        del payload["birth_date"]

        resp = client.post("/api/transits", json=payload)

        assert resp.status_code == 422

    def test_without_auth_is_403(self, unauthenticated_client):
        resp = unauthenticated_client.post("/api/transits", json=_natal_payload())

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/progressed-synastry — auth required, 15/min
# ---------------------------------------------------------------------------
class TestProgressedSynastry:
    def test_happy_path(self, client):
        payload = {"chart1": _natal_payload(), "chart2": _natal_payload(birth_date="1992-03-10T00:00:00")}

        resp = client.post("/api/progressed-synastry", json=payload)

        assert resp.status_code == 200

    def test_missing_chart2_is_422(self, client):
        resp = client.post("/api/progressed-synastry", json={"chart1": _natal_payload()})

        assert resp.status_code == 422

    def test_without_auth_is_403(self, unauthenticated_client):
        payload = {"chart1": _natal_payload(), "chart2": _natal_payload(birth_date="1992-03-10T00:00:00")}

        resp = unauthenticated_client.post("/api/progressed-synastry", json=payload)

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/geocode/coordinates — no auth, no rate limit, no network
# ---------------------------------------------------------------------------
class TestGeocodeCoordinates:
    def test_happy_path(self, client):
        resp = client.get("/api/geocode/coordinates", params={"lat": 50.4501, "lon": 30.5234})

        assert resp.status_code == 200
        assert resp.json() == {"timezone": "Europe/Kyiv"}

    def test_missing_query_param_is_422(self, client):
        resp = client.get("/api/geocode/coordinates", params={"lat": 50.4501})

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/geocode/autocomplete — no auth, no rate limit
# ---------------------------------------------------------------------------
class TestGeocodeAutocomplete:
    def test_short_query_returns_empty_without_network(self, client):
        """len(query) < 2 short-circuits before any LocationIQ call
        (app/api/endpoints.py:121-122) — safe to hit for real."""
        resp = client.get("/api/geocode/autocomplete", params={"q": "a"})

        assert resp.status_code == 200
        assert resp.json() == []

    def test_delegates_to_autocomplete_place(self, client, monkeypatch):
        import app.api.endpoints as endpoints_module

        fake_result = [{"name": "Kyiv, Ukraine", "lat": 50.45, "lon": 30.52}]

        async def fake_autocomplete_place(query, lang=None):
            assert query == "Kyi"
            return fake_result

        monkeypatch.setattr(endpoints_module, "autocomplete_place", fake_autocomplete_place)

        resp = client.get("/api/geocode/autocomplete", params={"q": "Kyi"})

        assert resp.status_code == 200
        assert resp.json() == fake_result

    def test_missing_query_param_is_422(self, client):
        resp = client.get("/api/geocode/autocomplete")

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/books/process — no auth, no rate limit
# ---------------------------------------------------------------------------
class TestBooksProcess:
    def test_delegates_to_process_book_async(self, client, monkeypatch):
        import app.services.book_processor as book_processor_module

        async def fake_process_book_async(filename):
            assert filename == "example.pdf"
            return {"status": "ok", "chunks": 3}

        monkeypatch.setattr(book_processor_module, "process_book_async", fake_process_book_async)

        resp = client.post("/api/books/process", params={"filename": "example.pdf"})

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "chunks": 3}

    def test_missing_filename_is_422(self, client):
        resp = client.post("/api/books/process")

        assert resp.status_code == 422
