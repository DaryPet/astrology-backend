"""
Регрессионный тест для упрощения /api/geocode/coordinates
(plans/concurrency-100-plus-users.md, проблема 1).

Фронтенд (Home.tsx, Synastry.tsx, EventAnalysisPanel.tsx через
geocodeAPI.detectTimezone, api.ts:263) использует из ответа этого эндпоинта
только поле `timezone`. Эндпоинт сейчас получает его косвенно, через
reverse_geocode() -> Nominatim -> get_timezone() внутри. План — вызывать
get_timezone() напрямую, без похода в Nominatim.

Этот тест фиксирует, что get_timezone() (та же функция, что и сегодня
формирует поле timezone в ответе) даёт ожидаемые IANA-имена для реальных
городов — до и после переноса вызова из reverse_geocode() прямо в роут
результат не должен отличаться, потому что функция та же самая.
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
    # Открытый океан — валидный сценарий (координаты вне суши), функция
    # должна отдать что-то вменяемое (fallback на nearby/UTC), а не упасть.
    result = get_timezone(0.0, -140.0)
    assert isinstance(result, str) and result
