# Tests for the scoring code in evals/run_supervisor_eval.py
#
# The evaluation grades the supervisor. If the grading itself had a bug,
# every score it reports would be wrong, so the grader gets its own tests.

from datetime import date, timedelta

from evals.run_supervisor_eval import check_supervisor, clean_airport, clean_days, expected_date


# ---------- helpers ----------

def test_clean_airport_ignores_case_and_spaces():
    assert clean_airport(" del ") == "DEL"
    assert clean_airport(None) == ""


def test_clean_days_treats_numbers_and_text_numbers_the_same():
    assert clean_days(5) == 5
    assert clean_days("5") == 5
    assert clean_days("") == ""
    assert clean_days(None) == ""
    assert clean_days(0) == ""
    assert clean_days("a week") == "a week"


# ---------- date rules ----------

def test_simple_date_rules():
    today = date.today()

    assert expected_date({"rule": "empty"}) == ""
    assert expected_date({"rule": "exact", "value": "2027-01-15"}) == "2027-01-15"
    assert expected_date({"rule": "days_from_today", "value": 1}) == (today + timedelta(days=1)).isoformat()


def test_month_day_rule_moves_past_dates_to_next_year():
    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    # a date that has already passed this year means next year
    rule = {"rule": "month_day", "value": yesterday.strftime("%m-%d")}
    assert expected_date(rule) == yesterday.replace(year=yesterday.year + 1).isoformat()

    # a date still ahead is this year
    rule = {"rule": "month_day", "value": tomorrow.strftime("%m-%d")}
    assert expected_date(rule) == tomorrow.isoformat()


def test_next_weekday_rule_is_always_one_to_seven_days_ahead():
    today = date.today()

    for weekday in range(7):           # 0 = Monday ... 6 = Sunday
        answer = date.fromisoformat(expected_date({"rule": "next_weekday", "value": weekday}))

        assert answer.weekday() == weekday
        assert 1 <= (answer - today).days <= 7


# ---------- the scoring ----------

DUBAI_LABELS = {
    "expect_allowed": True,
    "required_agents": ["flight_agent", "hotel_agent"],
    "forbidden_agents": ["weather_agent"],
    "origin_airport": ["DEL"],
    "destination_airport": ["DXB", "DWC"],
    "travel_date": {"rule": "exact", "value": "2026-12-20"},
    "trip_days": [5],
}


def model_answer(**overrides):
    """A supervisor answer that gets everything in DUBAI_LABELS right."""
    answer = {
        "allowed": True,
        "failed": False,
        "selected_agents": ["flight_agent", "hotel_agent", "itinerary_agent"],
        "trip_constraints": {
            "origin_airport": "DEL",
            "destination_airport": "DXB",
            "travel_date": "2026-12-20",
            "trip_days": "5",
        },
    }
    answer.update(overrides)
    return answer


def scores(outputs, labels):
    """Turns check_supervisor's result into a simple {name: score} dictionary."""
    return {item["key"]: item["score"] for item in check_supervisor(outputs, labels)["results"]}


def test_a_correct_answer_scores_full_marks():
    result = scores(model_answer(), DUBAI_LABELS)

    assert result["failed"] == 0
    assert all(score == 1 for key, score in result.items() if key != "failed")


def test_forbidden_agent_fails_routing_but_not_required_agents():
    answer = model_answer(selected_agents=["flight_agent", "hotel_agent", "weather_agent"])
    result = scores(answer, DUBAI_LABELS)

    assert result["has_required_agents"] == 1
    assert result["no_forbidden_agents"] == 0
    assert result["routing_correct"] == 0


def test_wrong_airport_is_caught():
    answer = model_answer(trip_constraints={"origin_airport": "BOM", "destination_airport": "DXB",
                                            "travel_date": "2026-12-20", "trip_days": 5})
    result = scores(answer, DUBAI_LABELS)

    assert result["origin_airport_correct"] == 0
    assert result["destination_airport_correct"] == 1


def test_null_labels_are_not_scored():
    labels = dict(DUBAI_LABELS, origin_airport=None, travel_date=None)
    result = scores(model_answer(), labels)

    assert "origin_airport_correct" not in result
    assert "travel_date_correct" not in result


def test_failed_model_call_is_an_error_not_a_wrong_answer():
    result = scores(model_answer(failed=True), DUBAI_LABELS)

    assert result == {"failed": 1}


def test_blocked_request_only_scores_the_guardrail():
    labels = dict(DUBAI_LABELS, expect_allowed=False)
    result = scores(model_answer(allowed=False), labels)

    assert result == {"failed": 0, "guardrail_correct": 1}