# Tests for tools/flights_mcp.py
#
# These tests never call the real SerpApi. Instead, each test swaps
# requests.get for a fake function that returns data we wrote ourselves.
# That way the tests are free, fast, and give the same result every time,
# and we can check exactly what our code does with each kind of answer.

from datetime import date, timedelta

import requests

from tools.flights_mcp import search_flights


# ---------- fakes ----------

class FakeResponse:
    """Stands in for the response object that requests.get returns."""

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


# a small made-up SerpApi answer: one direct flight and one with a stop
FAKE_SERPAPI_DATA = {
    "best_flights": [
        {
            "flights": [{"airline": "IndiGo"}],
            "total_duration": 255,
            "price": 51080
        },
        {
            "flights": [{"airline": "Oman Air"}, {"airline": "Oman Air"}],
            "total_duration": 355,
            "price": 45455
        }
    ],
    "price_insights": {"typical_price_range": [33000, 44500]}
}


def fake_serpapi(data):
    """Returns a fake requests.get that always answers with `data`,
    and remembers the params it was called with in `calls`."""
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params)
        return FakeResponse(data)

    return fake_get, calls


# ---------- tests ----------

def test_turns_serpapi_data_into_flight_options(monkeypatch):
    fake_get, calls = fake_serpapi(FAKE_SERPAPI_DATA)
    monkeypatch.setattr(requests, "get", fake_get)

    result = search_flights("DEL", "DXB", "2026-12-20", 5)

    assert result["route"] == "DEL to DXB"
    assert len(result["options"]) == 2

    direct = result["options"][0]
    assert direct["airline"] == "IndiGo"
    assert direct["round_trip_price_inr"] == 51080
    assert direct["duration"] == "4h 15m"     # 255 minutes
    assert direct["stops"] == 0

    one_stop = result["options"][1]
    assert one_stop["stops"] == 1             # two legs means one stop

    assert result["typical_price_range_inr"] == [33000, 44500]


def test_return_flight_is_on_the_last_day_of_the_trip(monkeypatch):
    fake_get, calls = fake_serpapi(FAKE_SERPAPI_DATA)
    monkeypatch.setattr(requests, "get", fake_get)

    result = search_flights("DEL", "DXB", "2026-12-20", 5)

    # a 5 day trip from the 20th is the 20th to the 24th
    assert result["outbound_date"] == "2026-12-20"
    assert result["return_date"] == "2026-12-24"

    # and those are the dates actually sent to SerpApi
    assert calls[0]["outbound_date"] == "2026-12-20"
    assert calls[0]["return_date"] == "2026-12-24"


def test_one_day_trip_returns_the_next_day(monkeypatch):
    fake_get, calls = fake_serpapi(FAKE_SERPAPI_DATA)
    monkeypatch.setattr(requests, "get", fake_get)

    result = search_flights("DEL", "JAI", "2026-12-20", 1)

    assert result["return_date"] == "2026-12-21"


def test_no_date_searches_a_month_from_today(monkeypatch):
    fake_get, calls = fake_serpapi(FAKE_SERPAPI_DATA)
    monkeypatch.setattr(requests, "get", fake_get)

    result = search_flights("BOM", "GOI")

    expected = date.today() + timedelta(days=30)
    assert result["outbound_date"] == expected.isoformat()


def test_uses_other_flights_when_there_are_no_best_flights(monkeypatch):
    data = {
        "other_flights": [
            {"flights": [{"airline": "Air India"}], "total_duration": 260, "price": 49289}
        ]
    }
    fake_get, calls = fake_serpapi(data)
    monkeypatch.setattr(requests, "get", fake_get)

    result = search_flights("DEL", "DXB", "2026-12-20", 5)

    assert result["options"][0]["airline"] == "Air India"
    assert result["typical_price_range_inr"] is None   # no price insights in the data


def test_serpapi_error_is_passed_back(monkeypatch):
    fake_get, calls = fake_serpapi({"error": "Invalid API key."})
    monkeypatch.setattr(requests, "get", fake_get)

    result = search_flights("DEL", "DXB", "2026-12-20", 5)

    assert result == {"error": "Invalid API key."}


def test_network_failure_does_not_leak_the_api_key(monkeypatch):
    # a real connection error message contains the full URL, including the key
    def broken_get(url, params, timeout):
        raise requests.ConnectionError("Failed: https://serpapi.com/search.json?api_key=SECRET123")

    monkeypatch.setattr(requests, "get", broken_get)

    result = search_flights("DEL", "DXB", "2026-12-20", 5)

    assert result == {"error": "Could not reach SerpApi"}
    assert "SECRET123" not in str(result)
