# 🧭 Waypoint — A Multi Agent Travel Itinerary Generator with LangGraph

An open-source AI travel planner that turns a natural-language trip request into a practical, human-approved travel plan — routed through a supervisor agent that decides which specialists (flights, hotels, weather, budget) a request actually needs.

![Python](https://img.shields.io/badge/python-3.14%2B-blue)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)
![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-1c3c3c)

## Why this project?

Planning a trip usually means jumping between multiple websites, tools, and spreadsheets. Waypoint brings that into one flow: a supervisor agent reads the request, runs a guardrail check, and decides which specialists are actually relevant —

- a flight-research agent,
- a hotel-research agent,
- a weather agent, and/or
- a budget-feasibility agent,

before an itinerary agent drafts a plan, a human reviews and approves it (or requests changes), and a final agent produces the polished result. All of it is coordinated through a single LangGraph workflow with PostgreSQL-backed checkpointing.

## Features

- 🛡️ Guardrails that block non-travel-related or harmful requests before any agent runs
- 🧠 A supervisor agent that dynamically decides which specialist agents a request actually needs
- ✈️ Flight research via an Aviationstack MCP server
- 🏨 Hotel suggestions via a Tavily MCP server
- ⛅ Weather-aware planning — current conditions plus a 5-day forecast — via a custom MCP weather server
- 💰 Budget feasibility analysis grounded in the flight and hotel data already gathered
- 📝 A draft itinerary combining every agent's output
- 🙋 Human-in-the-loop approval — review the draft, approve it, or send feedback for a revision — before the final plan is produced
- 🌐 FastAPI backend with a simple web interface
- 💾 Graph-state persistence in PostgreSQL, so a paused (awaiting-approval) plan survives a server restart
- ⚡ Gemini-powered reasoning throughout

## Architecture

![Waypoint architecture](waypoint_architecture.png)

A request passes through a guardrail and supervisor first, which decide whether to proceed and which specialist agents to run. Selected specialists each pull live data through their own MCP server. An itinerary agent always runs next and drafts a plan, the graph pauses for human approval, and a final agent applies any feedback and returns the polished result. State is checkpointed to PostgreSQL at the approval pause, so an in-progress plan survives a restart.

## Tech Stack

- Python 3.14+
- FastAPI
- Jinja2 + HTML/CSS/JavaScript frontend
- LangGraph
- LangChain
- Model Context Protocol (MCP) — via `langchain-mcp-adapters`, plus a custom FastMCP server
- Gemini LLMs
- PostgreSQL (LangGraph checkpointing)
- Tavily API
- AviationStack API
- OpenWeather API
- Docker + Render (deployment)

## Project Structure

```text
.
├── app.py                    # FastAPI app entry point
├── backend.py                 # LangGraph workflow: supervisor, guardrails, specialist agents, HITL
├── mcp_client.py                # MCP client setup (Tavily, Aviationstack, weather) + shared Gemini helper
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── static/                    # Static frontend assets
├── templates/                  # HTML templates
└── tools/
    └── custom_weather_mcp.py    # Custom FastMCP server (OpenWeather current + forecast)
```

## Prerequisites

Before running the project locally, make sure you have:

- Python 3.14 or newer installed
- PostgreSQL running and accessible
- API keys for:
  - Gemini
  - Tavily
  - AviationStack
  - OpenWeather
  - LangSmith (optional — only needed if you want tracing)

## Environment Variables

Create a `.env` file in the project root with the following variables (see `.env.example`):

```env
DATABASE_URL=postgresql://user:password@localhost:5432/travel_db
GOOGLE_API_KEY=your_gemini_api_key
TAVILY_API_KEY=your_tavily_api_key
AVIATIONSTACK_API_KEY=your_aviationstack_api_key
OPENWEATHER_API_KEY=your_openweather_api_key
DEFAULT_ORIGIN_DATA="BOM"

# Optional — LangSmith tracing. Set LANGSMITH_TRACING=false to disable
# tracing entirely and omit the rest of these safely.
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_PROJECT=Waypoint
```

## Installation

```bash
uv venv
source .venv/bin/activate       # macOS/Linux
.venv\Scripts\Activate.ps1      # Windows PowerShell
uv pip install -r requirements.txt
```

## Running the App

Start the FastAPI server:

```bash
uv run app.py
```

Then open your browser at:

```text
http://127.0.0.1:8000/
```

## Running with Docker

```bash
docker build -t waypoint .
docker run -p 8000:8000 --env-file .env waypoint
```

> The Aviationstack MCP server is launched at runtime via `uvx aviationstack-mcp`, so the Dockerfile copies the `uv`/`uvx` binaries from Astral's official image before installing dependencies.

## Deployment

Waypoint is deployed on [Render](https://render.com) as a Docker-based web service.

1. Push this repo to GitHub.
2. On Render, create a new **Web Service** and connect the repo — Render will detect and build the included `Dockerfile` automatically.
3. Add the environment variables listed above under the service's **Environment** tab.
4. Render assigns the app's port at runtime via the `PORT` environment variable — `app.py` already binds to `host="0.0.0.0"` and reads `port=int(os.environ.get("PORT", 8000))` in production rather than a hardcoded host/port.
5. Every push to the connected branch triggers an automatic redeploy.

> ⚠️ Render's router can't reach a server bound to `127.0.0.1` — it must bind to `0.0.0.0`, and the port must come from the `PORT` environment variable Render sets at runtime, not a hardcoded value.

## API Endpoints

- `GET /health` — Health check
- `POST /api/travel` — Submit a new travel request. Runs the guardrail, the supervisor, whichever specialist agents were selected, and the itinerary agent, then pauses for human approval. Returns a blocked response, or a draft itinerary with `"requires_approval": true`.
- `POST /api/travel/approve` — Resume a paused plan with `thread_id`, `approved` (bool), and optional `feedback`. Returns the final, polished plan.

Example requests:

```bash
curl -X POST http://127.0.0.1:8000/api/travel \
  -H "Content-Type: application/json" \
  -d '{"message":"Plan a 3-day trip to Tokyo with a budget of $1200"}'
```

```bash
curl -X POST http://127.0.0.1:8000/api/travel/approve \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"user_xxxxxxxx", "approved": true, "feedback": ""}'
```

## How the Workflow Works

1. The user submits a travel request.
2. A guardrail check confirms the request is travel-related and not harmful; if not, the workflow stops and returns a reason.
3. A supervisor agent decides which specialist agents the request actually needs — flight, hotel, weather, and/or budget — and extracts trip details (destination, dates, budget, and so on) from the request.
4. Only the selected specialist agents run, each pulling live data through its own MCP server (the budget agent reasons over the others' results instead of calling an external tool).
5. An itinerary agent always runs next, combining every result into a draft plan.
6. The workflow pauses for human approval. The user can approve the draft or send feedback for a revision.
7. A final agent applies any feedback and produces the polished travel plan.

## Limitations

- Live ticket pricing depends on AviationStack's data availability and may not always be returned — the final response explicitly notes this when prices are missing rather than inventing figures.
- Hotel suggestions come from a Tavily web search rather than a dedicated hotel-booking API, so availability and live pricing aren't guaranteed.
- Feedback on the draft itinerary is applied once by the final agent — there's no second approval round after a revision.
- Graph state is scoped per `thread_id` (via PostgreSQL checkpointing); there's currently no user-facing way to browse or delete past runs from the UI.


## License

This project is licensed under the Apache-2.0 license — see [LICENSE](LICENSE) for details.

## Acknowledgments

This project is built with the help of modern LLM tooling — LangGraph, the Model Context Protocol, and Gemini — combined with real-world travel APIs, and it is intended as a practical example of multi-agent orchestration with a human-in-the-loop step.