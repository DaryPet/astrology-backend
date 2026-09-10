"""
Tests for mapping the LocationIQ response -> the format expected by the frontend
(plans/geocoding-locationiq-migration.md, Part 2, plan item 8).

No live calls to LocationIQ — only recorded/fake responses; we test the
get_coordinates()/autocomplete_place() logic itself (parsing, float(lat/lon),
the fallback chain, caching, place_type detection).
"""
import asyncio

import pytest

from app.api import endpoints


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else []
        self.text = text

    def json(self):
        return self._json_data


class FakeAsyncClient:
    """Replaces httpx.AsyncClient: returns responses from `responses` in order."""

    def __init__(self, calls, responses, *args, **kwargs):
        self._calls = calls
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        self._calls.append({"url": url, "params": params})
        idx = len(self._calls) - 1
        resp = self._responses[idx] if idx < len(self._responses) else self._responses[-1]
        if isinstance(resp, Exception):
            raise resp
        return resp


def install_fake_httpx(monkeypatch, responses):
    calls = []

    def factory(*args, **kwargs):
        return FakeAsyncClient(calls, responses, *args, **kwargs)

    monkeypatch.setattr(endpoints.httpx, "AsyncClient", factory)
    return calls


@pytest.fixture(autouse=True)
def clear_geocode_cache():
    endpoints._geocode_cache.clear()
    yield
    endpoints._geocode_cache.clear()


# --- get_coordinates ---

def test_get_coordinates_success_first_attempt(monkeypatch):
    calls = install_fake_httpx(monkeypatch, [
        FakeResponse(200, [{"lat": "50.4501", "lon": "30.5234", "display_name": "Kyiv, Ukraine"}]),
    ])
    lat, lon = asyncio.run(endpoints.get_coordinates("Kyiv"))
    assert (lat, lon) == pytest.approx((50.4501, 30.5234))
    assert isinstance(lat, float) and isinstance(lon, float)
    assert len(calls) == 1
    assert calls[0]["params"]["accept-language"] == "ru"


def test_get_coordinates_falls_back_to_english_attempt(monkeypatch):
    calls = install_fake_httpx(monkeypatch, [
        FakeResponse(200, []), 
        FakeResponse(200, [{"lat": "51.5074", "lon": "-0.1278", "display_name": "London, UK"}]),
    ])
    lat, lon = asyncio.run(endpoints.get_coordinates("London"))
    assert (lat, lon) == pytest.approx((51.5074, -0.1278))
    assert len(calls) == 2
    assert calls[0]["params"]["accept-language"] == "ru"
    assert calls[1]["params"]["accept-language"] == "en"


def test_get_coordinates_raises_when_no_results(monkeypatch):
    install_fake_httpx(monkeypatch, [FakeResponse(200, [])])
    with pytest.raises(ValueError):
        asyncio.run(endpoints.get_coordinates("Nonexistentplacezzz"))


def test_get_coordinates_raises_on_invalid_coordinates(monkeypatch):
    install_fake_httpx(monkeypatch, [
        FakeResponse(200, [{"lat": "999", "lon": "999", "display_name": "Bad"}]),
    ])
    with pytest.raises(ValueError):
        asyncio.run(endpoints.get_coordinates("Badplace"))


def test_get_coordinates_uses_cache_on_second_call(monkeypatch):
    calls = install_fake_httpx(monkeypatch, [
        FakeResponse(200, [{"lat": "40.7128", "lon": "-74.0060", "display_name": "New York"}]),
    ])
    first = asyncio.run(endpoints.get_coordinates("New York"))
    second = asyncio.run(endpoints.get_coordinates("New York"))
    assert first == second
    assert len(calls) == 1 


# --- autocomplete_place ---

def test_autocomplete_place_maps_fields(monkeypatch):
    install_fake_httpx(monkeypatch, [
        FakeResponse(200, [{
            "lat": "40.7484284",
            "lon": "-73.9856546198733",
            "display_name": "Empire State Building, 350, 5th Avenue, New York City, New York, USA",
        }]),
    ])
    results = asyncio.run(endpoints.autocomplete_place("Empire", lang="en"))
    assert len(results) == 1
    item = results[0]
    assert isinstance(item["lat"], float) and isinstance(item["lon"], float)
    assert item["latitude"] == item["lat"]
    assert item["longitude"] == item["lon"]
    assert item["display_name"] == "Empire State Building, 350"
    assert item["country"] == "USA"
    assert item["type"] == "city"
    assert item["timezone"] 


def test_autocomplete_place_short_query_returns_empty_without_network(monkeypatch):
    calls = install_fake_httpx(monkeypatch, [])
    result = asyncio.run(endpoints.autocomplete_place("a"))
    assert result == []
    assert calls == []


def test_autocomplete_place_non_200_returns_empty(monkeypatch):
    install_fake_httpx(monkeypatch, [FakeResponse(500, [], text="server error")])
    result = asyncio.run(endpoints.autocomplete_place("Kyiv"))
    assert result == []


def test_autocomplete_place_detects_village_type(monkeypatch):
    install_fake_httpx(monkeypatch, [
        FakeResponse(200, [{"lat": "50.0", "lon": "30.0", "display_name": "Some Village, Kyiv Oblast, Ukraine"}]),
    ])
    results = asyncio.run(endpoints.autocomplete_place("Some Village", lang="en"))
    assert results[0]["type"] == "village"


def test_autocomplete_place_sorts_prefix_match_first(monkeypatch):
    install_fake_httpx(monkeypatch, [
        FakeResponse(200, [
            {"lat": "1.0", "lon": "1.0", "display_name": "Not matching prefix, Somewhere"},
            {"lat": "2.0", "lon": "2.0", "display_name": "Kyiv, Ukraine"},
        ]),
    ])
    results = asyncio.run(endpoints.autocomplete_place("Kyiv", lang="en"))
    assert results[0]["name"] == "Kyiv, Ukraine"
