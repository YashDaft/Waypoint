import os
import certifi
import asyncio
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_google_genai import ChatGoogleGenerativeAI
from tools.custom_weather_mcp import OPENWEATHER_API_KEY



load_dotenv()

# httpx logs every request URL, and the Tavily MCP URL contains the API key,
# so only let httpx log warnings and errors
logging.getLogger("httpx").setLevel(logging.WARNING)

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

WEATHER_SERVER_PATH = Path(__file__).parent / "tools/custom_weather_mcp.py"
WEATHER_ENV = {"OPENWEATHER_API_KEY": OPENWEATHER_API_KEY}

FLIGHTS_SERVER_PATH = Path(__file__).parent / "tools/flights_mcp.py"
FLIGHTS_ENV = {"SERPAPI_API_KEY": SERPAPI_API_KEY}

GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in environment variables, please add your Gemini API key to the .env file")


llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",
    api_key=GEMINI_API_KEY,
)

#mcp client for this app
client = MultiServerMCPClient(
    {   #remote tavily mcp
        "tavily":{
            "transport": "streamable_http",
            "url":f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"
        },
        #local custom made flights mcp server (serpapi google flights)
        "flights": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(FLIGHTS_SERVER_PATH)],
            "env": FLIGHTS_ENV
        },
        #local custom made mcp server
        "weather": {
            "transport": "stdio",
            # Use the same Python environment that runs app.py.
            "command": sys.executable,
            "args": [str(WEATHER_SERVER_PATH)],
            "env": WEATHER_ENV
        }
    }
)


search_tool = None

other_tools = {}

async def initialize_mcp():

    global search_tool, other_tools

    if search_tool is not None and other_tools:
        return
    
    tools = await client.get_tools()

    for tool in tools:
        print(tool.name)

    search_tool = next(
        tool for tool in tools
        if tool.name == "tavily_search"
    )

    other_tools = {
        tool.name: tool
        for tool in tools
        if tool.name != "tavily_search"
    }

#calling tavily mcp server tool
async def tavily_mcp_search(query:str):
    await initialize_mcp()
    result = await search_tool.ainvoke({"query": query})
    return result

#calling flights mcp server tool
flights_tool = None

async def flights_mcp_search(origin_airport: str, destination_airport: str, outbound_date: str = "", trip_days: int = 5):

    global flights_tool

    if flights_tool is None:
        tools = await client.get_tools()
        flights_tool = next(
            tool for tool in tools
            if tool.name == "search_flights"
        )

    return await flights_tool.ainvoke({
        "origin_airport": origin_airport,
        "destination_airport": destination_airport,
        "outbound_date": outbound_date,
        "trip_days": trip_days
    })


#Weather tools

weather_tool = None

forecast_tool = {}

async def initialize_weather_tools():

    global weather_tool, forecast_tool

    if weather_tool is not None:
        return
    
    tools = await client.get_tools()

    weather_tool = next(
        tool for tool in tools
        if tool.name == "get_current_weather"
    )

    forecast_tool = next(
        tool for tool in tools
        if tool.name == "get_forecast"
    )

async def weather_mcp_search(city: str):

    await initialize_weather_tools()

    return await weather_tool.ainvoke({"city": city})

async def forecast_mcp_search(city: str):

    await initialize_weather_tools()

    return await forecast_tool.ainvoke({"city": city})


#helper function to extract text from response
def _extract_text(content):
    """LLM and MCP results can be a plain string or a list of content blocks; this returns just the text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip()
    return str(content).strip()


def extract_destination(query: str):
    prompt = f"""
    Extract only the destination city from the user's query.

    User Query:
    {query}

    Return only the name of the destination city.
    """

    response = llm.invoke(prompt)

    return _extract_text(response.content)