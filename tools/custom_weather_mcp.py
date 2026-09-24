from mcp.server.fastmcp import FastMCP
import os
import requests
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("Weather tool MCP server")

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

#turns this function into a tool for this custom MCP server

@mcp.tool()
def get_current_weather(city: str):

    response = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={
            "q": city,
            "appid": OPENWEATHER_API_KEY,
            "units": "metric"
        }
    )
    
    data = response.json()

    if response.status_code != 200:
        return data

    return {
        "city": data["name"],
        "temperature_c": data["main"]["temp"],
        "feels_like_c": data["main"]["feels_like"],
        "humidity": data["main"]["humidity"],
        "condition": data["weather"][0]["description"],
        "wind_speed": data["wind"]["speed"]
    }

@mcp.tool()
def get_forecast(city: str):

    response = requests.get(
        "https://api.openweathermap.org/data/2.5/forecast",
        params={
            "q": city,
            "appid": OPENWEATHER_API_KEY,
            "units": "metric"
        }
    )

    data = response.json()

    if response.status_code != 200:
        return data

    forecast = []

    for item in data["list"]:
        if item["dt_txt"].endswith("12:00:00"):
            forecast.append(
                {
                    "date": item["dt_txt"].split(" ")[0],
                    "temperature": item["main"]["temp"],
                    "weather": item["weather"][0]["description"]
                }
            )

    return {
        "city": city,
        "forecast": forecast[:5]
    }


if __name__ == "__main__":
    mcp.run()

    





