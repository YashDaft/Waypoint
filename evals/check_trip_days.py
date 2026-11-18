import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import backend

# pick the model to check: lite or haiku
backend.llm = {"lite": backend.gemini_llm, "haiku": backend.claude_llm}[sys.argv[1]]

cases = json.loads((Path(__file__).parent / "supervisor_cases_hard.json").read_text(encoding="utf-8"))

for case in cases:
    # only the allowed cases that check trip length
    if case["trip_days"] is None or not case["expect_allowed"]:
        continue

    result = backend.supervisor_agent({"user_query": case["request"]})
    got = result.get("trip_constraints", {}).get("trip_days")

    print(f"{case['id']}  expected {case['trip_days']}  got {got!r}  | {case['request'][:60]}")