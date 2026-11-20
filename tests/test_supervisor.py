# Tests for the guardrail and supervisor in backend.supervisor_agent
#
# The real model is replaced with FakeLLM, which replies with text we choose.
# The supervisor makes two calls: first the guardrail, then the routing.

import json

import backend
from tests.fakes import FakeLLM


def guardrail_answer(allowed, reason=""):
    return json.dumps({"allowed": allowed, "reason": reason})


def routing_answer(agents, constraints=None, reasoning="test reasoning"):
    return json.dumps({
        "selected_agents": agents,
        "trip_constraints": constraints or {},
        "reasoning": reasoning
    })


def test_blocked_request_stops_before_routing(monkeypatch):
    fake = FakeLLM([guardrail_answer(False, "Waypoint only helps with travel.")])
    monkeypatch.setattr(backend, "llm", fake)

    result = backend.supervisor_agent({"user_query": "Write me a Python script"})

    assert result["guardrail_allowed"] is False
    assert result["selected_agents"] == []
    assert result["guardrail_reason"] == "Waypoint only helps with travel."
    assert len(fake.prompts) == 1          # only the guardrail ran, no routing call


def test_routing_keeps_agent_order_and_always_adds_itinerary(monkeypatch):
    # the model lists agents in a random order and includes one that doesn't exist
    fake = FakeLLM([
        guardrail_answer(True),
        routing_answer(["budget_agent", "spaceship_agent", "flight_agent"])
    ])
    monkeypatch.setattr(backend, "llm", fake)

    result = backend.supervisor_agent({"user_query": "Dubai from Delhi on a budget"})

    assert result["guardrail_allowed"] is True
    assert result["selected_agents"] == ["flight_agent", "budget_agent", "itinerary_agent"]


def test_routing_fills_in_trip_constraints(monkeypatch):
    fake = FakeLLM([
        guardrail_answer(True),
        routing_answer(
            ["flight_agent"],
            {"origin_airport": "DEL", "destination_airport": "DXB", "trip_days": 5}
        )
    ])
    monkeypatch.setattr(backend, "llm", fake)

    result = backend.supervisor_agent({"user_query": "Delhi to Dubai for 5 days"})
    constraints = result["trip_constraints"]

    assert constraints["origin_airport"] == "DEL"
    assert constraints["destination_airport"] == "DXB"
    assert constraints["trip_days"] == 5
    assert constraints["travel_date"] == ""    # not given, so it keeps the empty default


def test_guardrail_failure_lets_the_request_through(monkeypatch):
    # if the guardrail model crashes, the app allows the request rather than blocking everyone
    fake = FakeLLM([
        RuntimeError("model is down"),
        routing_answer(["hotel_agent"])
    ])
    monkeypatch.setattr(backend, "llm", fake)

    result = backend.supervisor_agent({"user_query": "Hotels in Goa"})

    assert result["guardrail_allowed"] is True
    # the evaluation script looks for this exact text to count failures
    assert result["guardrail_reason"] == "Guardrail validation fallback allowed the request"


def test_unreadable_routing_answer_runs_every_agent(monkeypatch):
    fake = FakeLLM([guardrail_answer(True), "Sorry, I can't do JSON today."])
    monkeypatch.setattr(backend, "llm", fake)

    result = backend.supervisor_agent({"user_query": "Plan a trip to Goa"})

    assert result["selected_agents"] == backend.AGENT_ORDER
    assert result["supervisor_reasoning"].startswith("Supervisor parsing failed")


def test_json_inside_extra_text_is_still_read():
    text = 'Here you go: {"allowed": true, "reason": ""} Hope that helps!'

    assert backend.json_from_llm(text) == {"allowed": True, "reason": ""}

