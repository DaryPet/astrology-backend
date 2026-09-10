"""
Regression test for simplifying /api/geocode/coordinates
(plans/concurrency-100-plus-users.md, problem 1).

The frontend (Home.tsx, Synastry.tsx, EventAnalysisPanel.tsx via
geocodeAPI.detectTimezone, api.ts:263) only uses the `timezone` field from
this endpoint's response. The endpoint currently gets it indirectly, via
reverse_geocode() -> Nominatim -> get_timezone() inside. The plan is to call
get_timezone() directly, without going through Nominatim.

This test locks in that get_timezone() (the same function that today
produces the timezone field in the response) gives the expected IANA names
for real cities — before and after moving the call from reverse_geocode()
straight into the route, the result should not differ, because it's the
same function.
"""
import pytest

from app.api.endpoints import get_timezone

CASES = [
    ("Kyiv", 50.4501, 30.5234, "Europe/Kyiv"),
    ("Moscow", 55.7558, 37.6173, "Europe/Moscow"),
    ("New York", 40.7128, -74.0060, "America/New_York"),
    ("London", 51.5074, -0.1278, "Europe/London"),
    ("Tokyo", 35.6762, 139.6503, "Asia/Tokyo"),
]


@pytest.mark.parametrize("city,lat,lon,expected_tz", CASES)
def test_get_timezone_matches_expected(city, lat, lon, expected_tz):
    result = get_timezone(lat, lon)
    assert result == expected_tz, f"{city}: expected {expected_tz}, got {result}"


def test_get_timezone_returns_str_not_none_for_ocean_point():
    # Open ocean is a valid scenario (coordinates outside land) — the function
    # should return something sensible (fallback to nearby/UTC) rather than crash.
    result = get_timezone(0.0, -140.0)
    assert isinstance(result, str) and result
