from mcp.server.fastmcp import FastMCP
from datetime import date, timedelta
import os
import requests
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("Flights tool MCP server")

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")


#searches google flights through serpapi for a round trip
@mcp.tool()
def search_flights(origin_airport: str, destination_airport: str, outbound_date: str = "", trip_days: int = 5):

    # no travel date given, so search about a month from today
    if outbound_date == "":
        outbound = date.today() + timedelta(days=30)
    else:
        outbound = date.fromisoformat(outbound_date)

    return_day = outbound + timedelta(days=trip_days)

    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_flights",
                "departure_id": origin_airport,
                "arrival_id": destination_airport,
                "outbound_date": outbound.isoformat(),
                "return_date": return_day.isoformat(),
                "currency": "INR",
                "hl": "en",
                "gl": "in",
                "api_key": SERPAPI_API_KEY
            },
            timeout=30
        )
        data = response.json()
    except requests.RequestException:
        # not returning the real error: it contains the URL with the api key
        return {"error": "Could not reach SerpApi"}

    if "error" in data:
        return {"error": data["error"]}

    flights = data.get("best_flights") or data.get("other_flights") or []

    options = []

    for option in flights[:5]:
        first_leg = option["flights"][0]
        hours = option["total_duration"] // 60
        minutes = option["total_duration"] % 60

        options.append(
            {
                "airline": first_leg["airline"],
                "price_inr": option.get("price"),
                "duration": f"{hours}h {minutes}m",
                "stops": len(option["flights"]) - 1
            }
        )

    insights = data.get("price_insights", {})

    return {
        "route": f"{origin_airport} to {destination_airport}",
        "outbound_date": outbound.isoformat(),
        "return_date": return_day.isoformat(),
        "options": options,
        "typical_price_range_inr": insights.get("typical_price_range")
    }


if __name__ == "__main__":
    mcp.run()