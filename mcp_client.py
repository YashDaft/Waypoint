import os
import certifi
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_google_genai import ChatGoogleGenerativeAI
from tools.custom_weather_mcp import OPENWEATHER_API_KEY



load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
AVIATIONSTACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

WEATHER_SERVER_PATH = Path(__file__).parent / "tools/custom_weather_mcp.py"
WEATHER_ENV = {"OPENWEATHER_API_KEY": OPENWEATHER_API_KEY}

GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables, please add gemini api key to .env file")


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
        #local mcp server, implementing from aviationstack-mcp github repository
        "Aviationstack": {
            "transport": "stdio",
            "command": "uvx",
            "args": [
                "aviationstack-mcp"
            ],
            "env": {
            "AVIATION_STACK_API_KEY": AVIATIONSTACK_API_KEY
            }
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

aviation_tools = {}

async def initialize_mcp():

    global search_tool, aviation_tools

    if search_tool is not None and aviation_tools:
        return
    
    tools = await client.get_tools()

    for tool in tools:
        print(tool.name)

    search_tool = next(
        tool for tool in tools
        if tool.name == "tavily_search"
    )

    aviation_tools = {
        tool.name: tool
        for tool in tools
        if tool.name != "tavily_search"
    }

#calling tavily mcp server tool
async def tavily_mcp_search(query:str):
    await initialize_mcp()
    result = await search_tool.ainvoke({"query": query})
    return result

#calling aviation mcp server tool
async def aviation_mcp_call(tool_name: str, tool_args: dict=None):

    tools = await client.get_tools()

    tool = next(
        t for t in tools if t.name == tool_name
    )

    result = await tool.ainvoke(tool_args or {})

    return result


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
    """Gemini responses can return content as a plain string or a list of content blocks."""
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























    
    




    
        

