from email import message
from pathlib import Path
import traceback
import uvicorn

from backend import run_travel_agent

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Waypoint",
    description="Langgraph Multi Agent travel itenarary generator with FastAPI Frontend",
    version="1.0.0"
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class TravelRequest(BaseModel):
    message:str
    thread_id: str | None = None

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    Return the index.html page with proper template rendering.
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )

    

      
       












