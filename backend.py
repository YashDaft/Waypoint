from langchain_core.utils import uuid
import psycopg
import os
import dotenv
import certifi
from dotenv import load_dotenv
import operator

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

from tools.flight_tool import search_flights
from tools.tavily_tool import tavily_search

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

print(url)

GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in environment variables, please add gemini api key to .env file")


llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",
    api_key=GEMINI_API_KEY,
)

class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str
    flight_results: str
    hotel_results: str
    itinerary: str
    llm_calls: int


#Flight Agent:
def flight_agent(state: TravelState):
    query = state["user_query"]
    flight_data = search_flights(query)

    return {
        "flight_results": flight_data,
        "messages": [
            AIMessage(content="Flight results fetched successfully.")
        ],
        "llm_calls": state.get("llm_calls",0) + 1
    }


#hotel searching agent that will fetch results from tavily search tool for best hotels as per user query.
def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"
    hotel_results = tavily_search(query)

    return {
        "hotel_results": hotel_results,
        "messages": [
            AIMessage(content="Hotel information fetched.")
        ],
        "llm_calls": state.get("llm_calls",0) + 1
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

Make the itinerary rational, practical, budget-aware, and easy to follow.
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
    # Use a more descriptive and structured prompt template
    prompt = f"""
    Synthesize the provided travel data into a comprehensive, beautiful, and practical travel plan.

    ---
    **INPUT DATA**
    - User Request: {state['user_query']}
    - Flight Results: {state['flight_results']}
    - Hotel Results: {state['hotel_results']}
    - Proposed Itinerary: {state['itinerary']}
    ---

    **OUTPUT FORMAT**
    Structure your response using clean Markdown with the following exact sections:

    ### 1. 🌟 Trip Summary
    [Provide a brief, engaging 2-3 sentence overview of the trip, matching the user's requested vibe.]

    ### 2. ✈️ Flight Information
    [Detail the flight options cleanly. If pricing is missing from the data, explicitly state: "Note: Live ticket prices are currently unavailable from the API. Please verify fares directly with the airline."]

    ### 3. 🏨 Hotel Suggestions
    [Present the hotel options clearly, highlighting location, price (if available), and why it fits the user's request.]

    ### 4. 🗺️ Day-by-Day Itinerary
    [Break down the schedule into a highly readable day-by-day format using bullet points.]

    ### 5. 💰 Estimated Budget
    [Summarize the expected costs based strictly on the provided flight and hotel data. Add a reasonable estimate for daily food/transportation to give a realistic total trip cost.]

    ### 6. 💡 Final Recommendations
    [Provide 3-4 practical travel tips (e.g., local transit, weather prep, booking advice) specific to this destination.]

    **CRITICAL INSTRUCTIONS:**
    - Do NOT invent flights, hotels, or prices. Stick strictly to the provided input data.
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



#build the graph

workflow = StateGraph(TravelState)


workflow.add_node("flight_agent", flight_agent)
workflow.add_node("hotel_agent", hotel_agent)
workflow.add_node("itinerary_agent", itinerary_agent)
workflow.add_node("final_agent", final_agent)


workflow.add_edge(START, "flight_agent")
workflow.add_edge("flight_agent", "hotel_agent")
workflow.add_edge("hotel_agent", "itinerary_agent")
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
            "itinerary": "",
            "llm_calls": 0
        },
        config=config
    )

    final_answer = result["messages"][-1].text
    
    #returning on frontend
    return {
        "thread_id": thread_id,
        "answer": final_answer,
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "itinerary": result.get("itinerary", ""),
        "llm_calls": result.get("llm_calls", 0),
    }





    


    


     




    






    