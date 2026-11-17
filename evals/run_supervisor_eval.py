import sys
import json
from pathlib import Path
from datetime import date, timedelta

from dotenv import load_dotenv
from langsmith import Client, evaluate

load_dotenv()

# backend.py is in the project root, one folder up from this file
sys.path.append(str(Path(__file__).resolve().parents[1]))
import backend

DATASET_NAME = "waypoint-supervisor"
CASES_FILE = Path(__file__).parent / "supervisor_cases.json"

# which model to test, chosen when running the script
MODELS = {
    "lite": backend.gemini_llm,
    "haiku": getattr(backend, "claude_llm", None),
    "chain": backend.llm,
}


# ---------- 1. upload the cases to langsmith once ----------

def create_dataset_if_missing(client):
    if client.has_dataset(dataset_name=DATASET_NAME):
        print(f"Using the existing LangSmith dataset '{DATASET_NAME}'")
        return

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    examples = []

    for case in cases:
        labels = dict(case)
        labels.pop("request")
        examples.append({"inputs": {"request": case["request"]}, "outputs": labels})

    client.create_dataset(dataset_name=DATASET_NAME)
    client.create_examples(dataset_name=DATASET_NAME, examples=examples)
    print(f"Created the LangSmith dataset '{DATASET_NAME}' with {len(examples)} cases")


# ---------- 2. what gets tested: only the supervisor ----------

def run_supervisor(inputs):
    result = backend.supervisor_agent({"user_query": inputs["request"]})

    # supervisor_agent never crashes: when the model fails, it uses these fallback messages
    failed = (
        result.get("guardrail_reason") == "Guardrail validation fallback allowed the request"
        or result.get("supervisor_reasoning", "").startswith("Supervisor parsing failed")
    )

    return {
        "allowed": result.get("guardrail_allowed"),
        "selected_agents": result.get("selected_agents", []),
        "trip_constraints": result.get("trip_constraints", {}),
        "failed": failed,
    }


# ---------- 3. small helpers for comparing answers ----------

def clean_airport(value):
    return str(value or "").strip().upper()


def clean_days(value):
    if value in (None, "", 0):
        return ""
    try:
        return int(value)
    except (ValueError, TypeError):
        return str(value)


def expected_date(rule):
    today = date.today()

    if rule["rule"] == "empty":
        return ""
    if rule["rule"] == "exact":
        return rule["value"]
    if rule["rule"] == "days_from_today":
        return (today + timedelta(days=rule["value"])).isoformat()

    # "month_day": the next time that date comes around
    month, day = rule["value"].split("-")
    next_date = date(today.year, int(month), int(day))
    if next_date < today:
        next_date = date(today.year + 1, int(month), int(day))
    return next_date.isoformat()


# ---------- 4. the scoring ----------

def check_supervisor(outputs, reference_outputs):
    labels = reference_outputs
    results = []

    # a failed model call is an error, not a wrong answer, so nothing else is scored
    if outputs["failed"]:
        return {"results": [{"key": "failed", "score": 1}]}

    results.append({"key": "failed", "score": 0})

    guardrail_correct = outputs["allowed"] == labels["expect_allowed"]
    results.append({"key": "guardrail_correct", "score": int(guardrail_correct)})

    # routing and extraction only matter for requests that should be allowed and were
    if not (labels["expect_allowed"] and outputs["allowed"]):
        return {"results": results}

    selected = outputs["selected_agents"]
    has_required = all(agent in selected for agent in labels["required_agents"])
    no_forbidden = not any(agent in selected for agent in labels["forbidden_agents"])

    results.append({"key": "has_required_agents", "score": int(has_required)})
    results.append({"key": "no_forbidden_agents", "score": int(no_forbidden)})
    results.append({"key": "routing_correct", "score": int(has_required and no_forbidden)})

    constraints = outputs["trip_constraints"]

    # null in the dataset means "not checked"
    if labels["origin_airport"] is not None:
        answer = clean_airport(constraints.get("origin_airport"))
        results.append({"key": "origin_airport_correct", "score": int(answer in labels["origin_airport"])})

    if labels["destination_airport"] is not None:
        answer = clean_airport(constraints.get("destination_airport"))
        results.append({"key": "destination_airport_correct", "score": int(answer in labels["destination_airport"])})

    if labels["travel_date"] is not None:
        answer = str(constraints.get("travel_date") or "").strip()
        results.append({"key": "travel_date_correct", "score": int(answer == expected_date(labels["travel_date"]))})

    if labels["trip_days"] is not None:
        answer = clean_days(constraints.get("trip_days"))
        results.append({"key": "trip_days_correct", "score": int(answer in labels["trip_days"])})

    return {"results": results}


# ---------- 5. run it ----------

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in MODELS:
        print("Usage: uv run python evals/run_supervisor_eval.py lite|haiku|chain")
        sys.exit(1)

    model_name = sys.argv[1]

    if MODELS[model_name] is None:
        print("Claude isn't set up: add ANTHROPIC_API_KEY to .env first")
        sys.exit(1)

    # every llm call in backend.py goes through backend.llm, so swap in the model to test
    backend.llm = MODELS[model_name]

    client = Client()
    create_dataset_if_missing(client)

    results = evaluate(
        run_supervisor,
        data=DATASET_NAME,
        evaluators=[check_supervisor],
        experiment_prefix=f"supervisor-{model_name}",
        max_concurrency=2,
    )

    # add up each score and the time per case, so the summary prints here as well as in LangSmith
    scores = {}
    seconds = []

    for row in results:
        run = row["run"]
        seconds.append((run.end_time - run.start_time).total_seconds())

        for result in row["evaluation_results"]["results"]:
            scores.setdefault(result.key, []).append(result.score)

    print(f"\n===== {model_name}: {len(seconds)} cases, average {sum(seconds) / len(seconds):.1f}s per case =====")
    for key, values in scores.items():
        print(f"{key:<30} {sum(values)}/{len(values)}")