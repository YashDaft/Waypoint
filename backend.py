import uuid
import psycopg
import os
import certifi
from dotenv import load_dotenv
import operator
import asyncio

from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import TypedDict, Annotated
from psycopg.rows import dict_row
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    AnyMessage
)

#from tools.flight_tool import search_flights
#from tools.tavily_tool import tavily_search
from mcp_client import (
    tavily_mcp_search, 
    aviation_mcp_call,
    extract_destination,
    forecast_mcp_search,
    weather_mcp_search
)
load_dotenv()



def get_database_url():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL not found in environment variables, please add postgresq external database url to .env file")
    
    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"


    return database_url


url = get_database_url()


GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in environment variables, please add gemini api key to .env file")


llm = ChatGoogleGenerativeAI(
    model="gemini-3.7-flash",
    api_key=GEMINI_API_KEY,
)

class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str
    flight_results: str
    hotel_results: str
    itinerary: str
    llm_calls: int
    weather_results: str

#Flight tool prompt
FLIGHT_AGENT_PROMPT = """
You are a flight research specialist helping plan a trip.

User Request:
{query}

Available Airport Data:
{airport_data}

Available Airline Data:
{airline_data}

Using ONLY the information provided above, produce a concise flight briefing with these sections:

1. **Departure Airport** — most likely departure airport (name + IATA code) based on the user's request.
2. **Arrival Airport** — most likely arrival airport (name + IATA code) for the destination.
3. **Airlines Serving This Route** — airlines found in the data above that operate this route.
4. **Typical Flight Duration** — an approximate duration, clearly marked as an estimate.
5. **Estimated Airfare Range** — only if pricing is present in the data above. If not, say so explicitly rather than guessing.
6. **Peak Season Considerations** — note if the travel dates overlap with a known peak season for this route.
7. **Booking Advice** — 1-2 practical, actionable tips.

Rules:
- Do NOT invent airport codes, airlines, prices, or durations not supported by the data above.
- If a section's data is missing or insufficient, say so clearly instead of guessing.
- Format the response in Markdown using the headers above, so it can be cleanly incorporated into a larger itinerary.
"""

def flight_agent(state: TravelState):
    
    query = state['user_query']

    try:

        airports = asyncio.run(
            aviation_mcp_call("list_airports")
        )

        airlines = asyncio.run(
            aviation_mcp_call("list_airlines")
        )

        print("AIRPORTS:", airports)
        print("\nAIRLINES:", airlines)

        prompt = FLIGHT_AGENT_PROMPT.format(
            query=query,
            airport_data=str(airports),
            airline_data=str(airlines)
        )

        response = llm.invoke([
            SystemMessage(
                content="You are an expert travel flight planner. Use the provided data to give accurate, useful guidance. Do not guess or invent information."
            ),
            HumanMessage(content=prompt)
        ])

        flight_data = response.content
        llm_calls_made = 1

    except Exception as e:
        flight_data = f"Flight information unavailable: {str(e)}"
        llm_calls_made = 0
    
    return {
        "flight_results": flight_data,
        "messages": [AIMessage(content=flight_data)],
        "llm_calls": state.get("llm_calls",0) + llm_calls_made
    }


#hotel searching agent that will fetch results from tavily search tool in the mcp server for best hotels as per user query.
def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"
    # hotel_results = tavily_search(query)
    hotel_results = asyncio.run(tavily_mcp_search(query))

    return {
        "hotel_results": hotel_results,
        "messages": [
            AIMessage(content="Hotel information fetched.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }

#Weather agent for fetching current and forecast weather as per user query
def weather_agent(state: TravelState):

    city = extract_destination(state['user_query'])

    weather_data = asyncio.run(weather_mcp_search(city))

    forecast_data = asyncio.run(forecast_mcp_search(city))

    return {
        "weather_results": f"""
        **Current Weather for {city}**

        {weather_data}

        **Forecast Weather for {city}**

        {forecast_data}
        """,
        "messages": [
            AIMessage(content="Weather information fetched.")
        ],
    }

#This agent will return a detailed itinerary as per user query, flight and hotel agent results:
def itinerary_agent(state: TravelState):
    prompt = f"""
      Create a complete travel itinerary.

      User Query:
      {state['user_query']}

      Flight Results:
      {state['flight_results']}

      Hotel Results:
      {state['hotel_results']}

      Weather Results:
      {state['weather_results']}

      Instructions:
      - Use the Weather Results to shape the plan practically — favor outdoor activities on clear/mild days, and suggest indoor alternatives on days with rain, extreme heat, or poor conditions.
      - Base the itinerary strictly on the Flight, Hotel, and Weather data provided above. Do NOT invent flight numbers, hotel names, or prices that aren't present in the data.
      - If any of the above data is missing or incomplete, acknowledge the gap briefly rather than fabricating details.
      - Make the itinerary rational, practical, budget-aware, and easy to follow.
      """

    response = llm.invoke([
        SystemMessage(content="You are an expert travel planner with best in class budget planning."),
        HumanMessage(content=prompt)
    ])

    return {
        "itinerary": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


def final_agent(state: TravelState):
    prompt = f"""
    Synthesize the provided travel data into a comprehensive, beautiful, and practical travel plan.

    ---
    **INPUT DATA**
    - User Request: {state['user_query']}
    - Flight Results: {state['flight_results']}
    - Hotel Results: {state['hotel_results']}
    - Weather: {state['weather_results']}
    - Proposed Itinerary: {state['itinerary']} 
    ---

    **OUTPUT FORMAT**
    Structure your response using clean Markdown with the following exact sections:

    ### 1. 🌟 Trip Summary
    [Provide a brief, engaging 2-3 sentence overview of the trip, matching the user's requested vibe.]

    ### 2. ☀️ Weather Overview
    [Summarize current conditions and the forecast from the Weather data above. Call out anything that should influence packing or daily plans — rain, extreme heat/cold, or notably pleasant days.]

    ### 3. ✈️ Flight Information
    [Detail the flight options cleanly. If pricing is missing from the data, explicitly state: "Note: Live ticket prices are currently unavailable from the API. Please verify fares directly with the airline."]

    ### 4. 🏨 Hotel Suggestions
    [Present the hotel options clearly, highlighting location, price (if available), and why it fits the user's request.]

    ### 5. 🗺️ Day-by-Day Itinerary
    [Break down the schedule into a highly readable day-by-day format using bullet points. Factor in the Weather Overview above — favor outdoor plans on clear days, indoor alternatives when weather is poor.]

    ### 6. 💰 Estimated Budget
    [Summarize the expected costs based strictly on the provided flight and hotel data. Add a reasonable estimate for daily food/transportation to give a realistic total trip cost.]

    ### 7. 💡 Final Recommendations
    [Provide 3-4 practical travel tips (e.g., local transit, weather prep, booking advice) specific to this destination.]

    **CRITICAL INSTRUCTIONS:**
    - Do NOT invent flights, hotels, prices, or weather conditions. Stick strictly to the provided input data.
    - If any section of the input data is empty or missing, gracefully acknowledge it and advise the user on how to find that information.
    - Keep the tone professional, inspiring, and highly actionable.
    """

    response = llm.invoke([
        SystemMessage(content="You are an expert, high-end travel concierge. Your goal is to format raw travel data into visually appealing, highly practical, and easy-to-read itineraries."),
        HumanMessage(content=prompt)
    ])

    return {
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }



#building the graph

workflow = StateGraph(TravelState)


workflow.add_node("flight_agent", flight_agent)
workflow.add_node("hotel_agent", hotel_agent)
workflow.add_node("weather_agent", weather_agent)
workflow.add_node("itinerary_agent", itinerary_agent)
workflow.add_node("final_agent", final_agent)


workflow.add_edge(START, "flight_agent")
workflow.add_edge("flight_agent", "hotel_agent")
workflow.add_edge("hotel_agent", "weather_agent")
workflow.add_edge("weather_agent", "itinerary_agent")
workflow.add_edge("itinerary_agent", "final_agent")
workflow.add_edge("final_agent", END)

DATABASE_URL = get_database_url()

_conn = psycopg.connect(
    DATABASE_URL,
    autocommit=True,
    row_factory=dict_row
)

checkpointer = PostgresSaver(_conn)

checkpointer.setup()

travel_workflow = workflow.compile(checkpointer=checkpointer)

#function 

def run_travel_agent(user_input: str, thread_id: str | None = None):
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    result = travel_workflow.invoke(
        {
            "messages": [HumanMessage(content=user_input)],
            "user_query": user_input,
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "itinerary": "",
            "llm_calls": 0
        },
        config=config
    )

    final_answer = result["messages"][-1].text
    
    #returning on frontend ui
    return {
        "thread_id": thread_id,
        "answer": final_answer,
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "itinerary": result.get("itinerary", ""),
        "weather_results": result.get("weather_results", ""),
        "llm_calls": result.get("llm_calls", 0),
    }





    


    


     




    






    