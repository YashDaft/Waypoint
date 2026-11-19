# Tests for the FastAPI routes in app.py
#
# TestClient sends requests to the app directly, without starting a server.
# The agent itself is replaced with a fake, so these tests only check the
# routes: input checks, status codes and what gets passed through.

from fastapi.testclient import TestClient

import app


client = TestClient(app.app)


def fake_agent_result(**overrides):
    """A small made-up result shaped like the real one from backend.py."""
    result = {"thread_id": "user_123", "answer": "draft plan", "requires_approval": True}
    result.update(overrides)
    return result


def test_home_page_loads():
    response = client.get("/")

    assert response.status_code == 200
    assert "Where to next?" in response.text


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_empty_message_is_rejected():
    for message in ["", "   "]:
        response = client.post("/api/travel", json={"message": message})

        assert response.status_code == 400
        assert response.json() == {"success": False, "error": "Message cannot be empty."}


def test_travel_request_runs_the_agent_and_returns_its_result(monkeypatch):
    calls = []

    def fake_run_travel_agent(user_input, thread_id):
        calls.append((user_input, thread_id))
        return fake_agent_result()

    monkeypatch.setattr(app, "run_travel_agent", fake_run_travel_agent)

    response = client.post("/api/travel", json={"message": "  Plan a trip to Goa  "})

    assert response.status_code == 200
    assert response.json() == {"success": True, **fake_agent_result()}
    assert calls == [("Plan a trip to Goa", None)]       # spaces trimmed, no thread yet


def test_agent_crash_returns_a_500_error(monkeypatch):
    def broken_agent(user_input, thread_id):
        raise RuntimeError("database is down")

    monkeypatch.setattr(app, "run_travel_agent", broken_agent)

    response = client.post("/api/travel", json={"message": "Plan a trip to Goa"})

    assert response.status_code == 500
    assert response.json()["success"] is False


def test_revising_without_feedback_is_rejected():
    response = client.post(
        "/api/travel/approve",
        json={"thread_id": "user_123", "approved": False, "feedback": "  "}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Feedback is required when not approved."


def test_approval_needs_a_thread_id():
    # FastAPI checks the request shape itself and answers 422 when it's wrong
    response = client.post("/api/travel/approve", json={"thread_id": "", "approved": True})

    assert response.status_code == 422


def test_approval_resumes_the_right_plan(monkeypatch):
    calls = []

    def fake_resume(thread_id, approved, feedback):
        calls.append((thread_id, approved, feedback))
        return fake_agent_result(requires_approval=False, answer="final plan")

    monkeypatch.setattr(app, "resume_travel_agent", fake_resume)

    response = client.post(
        "/api/travel/approve",
        json={"thread_id": "user_123", "approved": True, "feedback": ""}
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "final plan"
    assert calls == [("user_123", True, "")]