import os
import certifi
import asyncio
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
AVIATIONSTACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY")


#mcp client for this app
client = MultiServerMCPClient(
    {
        "tavily":{
            "transport": "streamable_http",
            "url":f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"
        },
        #local mcp server
        "Aviationstack": {
            "transport": "stdio",
        "command": "uvx",
        "args": [
            "aviationstack-mcp"
        ],
        "env": {
            "AVIATION_STACK_API_KEY": AVIATIONSTACK_API_KEY
        }
    }
}
)

async def get_all_tools():
    tools = await client.get_tools()
    
    print("\nAvailable MCP tools:\n")

    for tool in tools:
        print(tool.name)
