# Tests for the specialist agents in backend.py: flight, hotel, weather and budget
#
# Every model and MCP tool the agents use is replaced with a fake from
# tests/fakes.py, so these tests make no network calls and cost nothing.

import json
from datetime import date, timedelta

import backend
from tests.fakes import FakeLLM, fake_tool, mcp_text


FLIGHT_DATA = {
    "route": "DEL to DXB",
    "options": [{"airline": "IndiGo", "round_trip_price_inr": 51080, "duration": "4h 15m", "stops": 0}]
}

DUBAI_TRIP = {
    "origin": "Delhi",
    "destination": "Dubai",
    "origin_airport": "DEL",
    "destination_airport": "DXB",
    "travel_date": "2026-12-20",
    "trip_days": 5
}


# ---------- flight agent ----------

def test_flight_agent_uses_live_prices_when_airports_are_known(monkeypatch):
    calls = []
    monkeypatch.setattr(backend, "flights_mcp_search", fake_tool(mcp_text(FLIGHT_DATA), calls))
    fake = FakeLLM(["flight briefing"])
    monkeypatch.setattr(backend, "llm", fake)

    result = backend.flight_agent({"user_query": "Dubai trip", "trip_constraints": DUBAI_TRIP, "llm_calls": 2})

    assert calls == [("DEL", "DXB", "2026-12-20", 5)]
    assert "Google Flights (live prices)" in fake.prompts[0]
    assert result["flight_results"] == "flight briefing"
    assert result["llm_calls"] == 3


def test_flight_agent_falls_back_to_web_search_on_a_serpapi_error(monkeypatch):
    search_calls = []
    monkeypatch.setattr(backend, "flights_mcp_search", fake_tool(mcp_text({"error": "Invalid API key."})))
    monkeypatch.setattr(backend, "tavily_mcp_search", fake_tool(mcp_text("some web results"), search_calls))
    fake = FakeLLM(["estimated briefing"])
    monkeypatch.setattr(backend, "llm", fake)

    result = backend.flight_agent({"user_query": "Dubai trip", "trip_constraints": DUBAI_TRIP})

    assert search_calls == [("flights from Delhi to Dubai airlines and ticket price",)]
    assert "web search (rough estimates, not live prices)" in fake.prompts[0]
    assert result["flight_results"] == "estimated briefing"


def test_flight_agent_skips_the_model_when_both_searches_fail(monkeypatch):
    monkeypatch.setattr(backend, "flights_mcp_search", fake_tool(RuntimeError("server down")))
    monkeypatch.setattr(backend, "tavily_mcp_search", fake_tool(RuntimeError("server down")))
    fake = FakeLLM([])          # no answers: the test fails if the model is called at all
    monkeypatch.setattr(backend, "llm", fake)

    result = backend.flight_agent({"user_query": "Dubai trip", "trip_constraints": DUBAI_TRIP, "llm_calls": 2})

    assert result["flight_results"] == "Flight information is unavailable right now."
    assert result["llm_calls"] == 2
    assert fake.prompts == []


def test_flight_agent_turns_trip_days_into_a_number(monkeypatch):
    calls = []
    monkeypatch.setattr(backend, "flights_mcp_search", fake_tool(mcp_text(FLIGHT_DATA), calls))
    monkeypatch.setattr(backend, "llm", FakeLLM(["briefing", "briefing", "briefing"]))

    for trip_days in ["7", "", "a week"]:
        trip = dict(DUBAI_TRIP, trip_days=trip_days)
        backend.flight_agent({"user_query": "Dubai trip", "trip_constraints": trip})

    # "7" becomes 7, and anything that isn't a number falls back to 5
    assert [call[3] for call in calls] == [7, 5, 5]


# ---------- hotel agent ----------

def test_hotel_agent_searches_by_destination_and_trims_the_results(monkeypatch):
    long_text = "Great pool.\nNear the beach. " * 40          # far longer than 400 characters
    tavily_data = {"results": [{"title": f"Hotel {n}", "content": long_text, "url": f"https://x.com/{n}"} for n in range(8)]}
    calls = []
    monkeypatch.setattr(backend, "tavily_mcp_search", fake_tool(mcp_text(tavily_data), calls))

    trip = {"destination": "Goa", "travel_style": "budget"}
    result = backend.hotel_agent({"user_query": "anything", "trip_constraints": trip})
    lines = result["hotel_results"].split("\n")

    assert calls == [("best budget hotels in Goa",)]
    assert len(lines) == 5                                   # only the top 5 results
    assert lines[0].startswith("- Hotel 0: ")
    assert lines[0].endswith("(source: https://x.com/0)")
    assert "llm_calls" not in result                         # this agent never calls the model


def test_hotel_agent_reports_when_the_search_fails(monkeypatch):
    monkeypatch.setattr(backend, "tavily_mcp_search", fake_tool(RuntimeError("down")))

    result = backend.hotel_agent({"user_query": "anything", "trip_constraints": {"destination": "Goa"}})

    assert result["hotel_results"] == "Hotel information is unavailable right now."


# ---------- weather agent ----------

def use_fake_weather(monkeypatch):
    monkeypatch.setattr(backend, "weather_mcp_search", fake_tool(mcp_text({"city": "Goa", "temperature_c": 31})))
    monkeypatch.setattr(backend, "forecast_mcp_search", fake_tool(mcp_text({"forecast": []})))


def test_weather_uses_the_forecast_when_the_trip_starts_soon(monkeypatch):
    use_fake_weather(monkeypatch)
    in_two_days = (date.today() + timedelta(days=2)).isoformat()

    result = backend.weather_agent({"user_query": "Goa", "trip_constraints": {"destination": "Goa", "travel_date": in_two_days}})

    assert "can be used for the trip days" in result["weather_results"]
    assert '"temperature_c": 31' in result["weather_results"]   # the JSON text, not the MCP wrapper


def test_weather_warns_when_the_trip_is_beyond_the_forecast(monkeypatch):
    use_fake_weather(monkeypatch)
    in_a_month = (date.today() + timedelta(days=30)).isoformat()

    for travel_date in [in_a_month, "", "not a date"]:
        trip = {"destination": "Goa", "travel_date": travel_date}
        result = backend.weather_agent({"user_query": "Goa", "trip_constraints": trip})

        assert "NOT the trip dates" in result["weather_results"]


def test_weather_only_asks_for_the_city_when_it_is_missing(monkeypatch):
    use_fake_weather(monkeypatch)
    asked = []

    def fake_extract_destination(query):
        asked.append(query)
        return "Manali"

    monkeypatch.setattr(backend, "extract_destination", fake_extract_destination)

    backend.weather_agent({"user_query": "Goa", "trip_constraints": {"destination": "Goa"}})
    assert asked == []                                     # the supervisor already knew the city

    result = backend.weather_agent({"user_query": "somewhere cold", "trip_constraints": {}})
    assert asked == ["somewhere cold"]
    assert "Current weather for Manali" in result["weather_results"]


def test_weather_reports_when_the_weather_server_fails(monkeypatch):
    monkeypatch.setattr(backend, "weather_mcp_search", fake_tool(RuntimeError("down")))

    result = backend.weather_agent({"user_query": "Goa", "trip_constraints": {"destination": "Goa"}})

    assert result["weather_results"] == "Weather information is unavailable right now."


# ---------- budget agent ----------

def test_budget_agent_reports_when_every_model_fails(monkeypatch):
    monkeypatch.setattr(backend, "llm", FakeLLM([RuntimeError("all models are down")]))

    result = backend.budget_agent({"user_query": "Dubai on ₹1,00,000", "llm_calls": 3})

    assert result["budget_results"] == "Budget analysis is unavailable right now."
    assert result["llm_calls"] == 3