# 🧭 Waypoint — A Multi-Agent Travel Itinerary Generator with LangGraph

An open source AI travel planner that turns a natural-language trip request into a practical travel plan with flight suggestions, hotel ideas, and a day-by-day itinerary. The project uses a multi-agent workflow built with LangGraph, LangChain, and FastAPI.

![Python](https://img.shields.io/badge/python-3.14%2B-blue)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)
![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-1c3c3c)
![License](https://img.shields.io/badge/license-MIT-green)

## Why this project?

Planning a trip usually means jumping between multiple websites, tools, and spreadsheets. This project brings that flow into one experience by combining:

- a flight-search agent,
- a hotel-research agent,
- an itinerary-planning agent, and
- a final response agent,

all coordinated through a LangGraph workflow.

## Features

- ✈️ Flight research using AviationStack
- 🏨 Hotel suggestions using Tavily search
- 🧠 Multi-agent orchestration with LangGraph
- 📝 Structured travel itinerary generation
- 🌐 FastAPI backend with a simple web interface
- 💾 Conversation state persistence using PostgreSQL
- ⚡ LLM-powered responses with Gemini

## Tech Stack

- Python 3.14+
- FastAPI
- Jinja2 + HTML/CSS/JavaScript frontend
- LangGraph
- LangChain
- Gemini LLMs
- PostgreSQL
- Tavily API
- AviationStack API
- Docker + Render (deployment)

## Project Structure

```text
.
├── app.py                # FastAPI app entry point
├── backend.py             # LangGraph travel workflow
├── requirements.txt       # Python dependencies
├── Dockerfile
├── .dockerignore
├── static/                # Static frontend assets
├── templates/              # HTML templates
└── tools/                 # Flight and web search integrations
```

## Prerequisites

Before running the project locally, make sure you have:

- Python 3.14 or newer installed
- PostgreSQL running and accessible
- API keys for:
  - Gemini
  - Tavily
  - AviationStack
  - LangSmith (optional — only needed if you want tracing)

## Environment Variables

Create a `.env` file in the project root with the following variables (see `.env.example`):

```env
DATABASE_URL=postgresql://user:password@localhost:5432/travel_db
GOOGLE_API_KEY=your_gemini_api_key
AVIATIONSTACK_API_KEY=your_aviationstack_api_key
TAVILY_API_KEY=your_tavily_api_key
DEFAULT_ORIGIN_IATA=DEL

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

## Deployment

Waypoint is deployed on [Render](https://render.com) as a Docker-based web service.

1. Push this repo to GitHub.
2. On Render, create a new **Web Service** and connect the repo — Render will detect and build the included `Dockerfile` automatically.
3. Add the environment variables listed above (`DATABASE_URL`, `GOOGLE_API_KEY`, `AVIATIONSTACK_API_KEY`, `TAVILY_API_KEY`, `DEFAULT_ORIGIN_IATA`, and the LangSmith variables if you want tracing) under the service's **Environment** tab.
4. Render assigns the app's port at runtime via the `PORT` environment variable — make sure `app.py` binds to `host="0.0.0.0"` and reads `port=int(os.environ.get("PORT", 8000))` rather than a hardcoded host/port (see note below).
5. Every push to the connected branch triggers an automatic redeploy.

> ⚠️ Render's router can't reach a server bound to `127.0.0.1` — it must bind to `0.0.0.0`, and the port must come from the `PORT` environment variable Render sets at runtime, not a hardcoded value.

## API Endpoints

- `GET /health` — Health check
- `POST /api/travel` — Submit a travel request

Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/travel \
  -H "Content-Type: application/json" \
  -d '{"message":"Plan a 3-day trip to Tokyo with a budget of $1200"}'
```

## How the Workflow Works

1. The user submits a travel request.
2. The flight agent gathers flight-related information.
3. The hotel agent searches for accommodation suggestions.
4. The itinerary agent creates a practical travel plan.
5. The final agent formats the result into a polished response.

## Limitations

- Live ticket pricing depends on AviationStack's data availability and may not always be returned — the final response explicitly notes this when prices are missing rather than inventing figures.
- Conversation memory is scoped per `thread_id`; there's currently no user-facing way to browse or delete past conversations from the UI.
- Hotel suggestions come from web search results rather than a dedicated hotel-booking API, so availability and live pricing aren't guaranteed.

## Contributing

Contributions are welcome. If you want to improve the app, add new travel features, or fix issues:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Open a pull request

## License

This project is licensed under the Apache-2.0 license — see [LICENSE](LICENSE) for details.

## Acknowledgments

This project is built with the help of modern LLM tooling and travel APIs, and it is intended as a practical example of combining LangGraph agents with real-world applications.