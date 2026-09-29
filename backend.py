from win32.lib.win32con import EMR_POLYPOLYGON
import uuid
import psycopg
import os
import certifi
from dotenv import load_dotenv
import operator
import asyncio
import json

from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.types import interrupt, Command
from typing import TypedDict, Annotated, Any
from psycopg.rows import dict_row
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    AnyMessage
)


from mcp_client import (
    _extract_text,
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
    model="gemini-3.8-flash",
    api_key=GEMINI_API_KEY,
)

class TravelState(TypedDict, total=False):

    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str
    
    #supervisor and guardrail state
    guardrail_allowed: bool
    guardrail_reason: str
    selected_agents: list[str]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str


    #agent results
    flight_results: str
    hotel_results: str
    itinerary: str
    weather_results: str
    
    #budget and hitl state
    budget_results: str
    approval_request: str
    approved: bool
    human_feedback: str
    final_response: str

    llm_calls: int

#no duplicates
KNOWN_AGENTS = {
    "flight_agent", 
    "hotel_agent", 
    "weather_agent", 
    "itinerary_agent", 
    "budget_agent", 
    "supervisor_agent"
    }

#Order of agents to be called
AGENT_ORDER = [
    "flight_agent", 
    "hotel_agent", 
    "weather_agent", 
    "budget_agent", 
    "itinerary_agent"
    ]

#llm functions to call llm anywhere in the project
def llm_text(system_prompt: str, user_prompt: str):
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
    )

    return _extract_text(response.content)


#function to extract json from the llm response
def json_from_llm(text: str)-> dict[str, Any]:
    '''Extract the first complete JSON object returned by the model'''

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("The model did not return a JSON object.")

    return json.loads(text[start : end + 1])



def empty_constraints() -> dict[str, Any]:
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": ""
    }

#Supervisor agent
def supervisor_agent(state: TravelState):
    query = state["user_query"]
    llm_calls = state.get("llm_calls", 0)

    guardrail_prompt = f"""
Determine whether the following user request is a valid travel-planning request.

Valid requests include destinations, flights, hotels, weather, budgets, visas,
transportation, sightseeing, food, packing, or itineraries — including vague or
incomplete requests, as long as they are travel-related.

Block only requests that are clearly unrelated to travel, or that ask for harmful
or illegal instructions.

User request:
{query}

Return ONLY a JSON object in this exact shape, with no markdown, no code fences,
and no text before or after it:
{{
    "allowed": true,
    "reason": ""
}}
Leave "reason" empty if allowed is true. If allowed is false, give a short,
user-facing explanation in "reason".
"""

    try:
        guardrail_raw = llm_text(
            "You are a strict travel-planning guardrail. Decide only whether the "
            "request is in scope for a travel planning assistant. Return strict "
            "JSON only, with no extra commentary or formatting.",
            guardrail_prompt
        )
        guardrail_result = json_from_llm(guardrail_raw)
        allowed = bool(guardrail_result.get("allowed", True))
        guardrail_reason = str(guardrail_result.get("reason", "")).strip()
        llm_calls += 1

    except Exception as e:
        print(f"Guardrail fallback used: {e}")
        allowed = True
        guardrail_reason = "Guardrail validation fallback allowed the request"

    if not allowed:
        reason = guardrail_reason or (
            "Waypoint can only help with travel planning and related requests. "
            "Kindly ask about a destination, itinerary, flight, hotel, weather or budget and I can help."
        )

        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "selected_agents": [],
            "trip_constraints": empty_constraints(),
            "supervisor_reasoning": reason,
            "messages": [AIMessage(content=f"Guardrail blocked request: {reason}")],
            "llm_calls": llm_calls
        }

    supervisor_prompt = f"""
You are the supervisor of a multi-agent travel-planning system. Based on the
user's request, choose only the specialist agents actually needed to fulfill it.

Available specialist agents:
- flight_agent: flights, airports, airlines, routes, airfare, or booking advice
- hotel_agent: hotels, accommodation, neighborhoods, or places to stay
- weather_agent: weather, climate, season, forecast, or packing advice
- budget_agent: cost, affordability, price limits, or budget feasibility

itinerary_agent always runs automatically after your selected agents, so do not
include it in "selected_agents".

Extract any trip details mentioned in the request into "trip_constraints". Leave
a field as an empty string (or empty list for "special_preferences") if the user
did not mention it — do not guess or invent values.

User request:
{query}

Return ONLY a JSON object in this exact shape, with no markdown, no code fences,
and no text before or after it:
{{
  "selected_agents": ["flight_agent", "hotel_agent", "weather_agent", "budget_agent"],
  "trip_constraints": {{
    "destination": "",
    "origin": "",
    "duration": "",
    "budget": "",
    "travel_style": "",
    "special_preferences": []
  }},
  "reasoning": ""
}}
"""
    try:
        supervisor_raw = llm_text(
            "You are a routing supervisor for a travel-planning multi-agent system. "
            "Decide which specialist agents are needed and extract trip constraints. "
            "Return strict JSON only, with no extra commentary or formatting.",
            supervisor_prompt,
        )

        parsed = json_from_llm(supervisor_raw)
        requested_agents = parsed.get("selected_agents", [])

        selected_agents = [
            name for name in AGENT_ORDER
            if name in requested_agents and name in KNOWN_AGENTS
        ]

        if "itinerary_agent" not in selected_agents:
            selected_agents.append("itinerary_agent")

        constraints = empty_constraints()
        parsed_constraints = parsed.get("trip_constraints", {})
        if isinstance(parsed_constraints, dict):
            constraints.update(parsed_constraints)

        reasoning = str(parsed.get("reasoning", "")).strip()
        llm_calls += 1

    except Exception as e:
        print(f"Supervisor fallback used: {e}")
        selected_agents = AGENT_ORDER.copy()
        constraints = empty_constraints()
        reasoning = (
            "Supervisor parsing failed, so the original full travel workflow "
            "was selected as a safe fallback"
        )

    return {
        "guardrail_allowed": True,
        "guardrail_reason": guardrail_reason,
        "selected_agents": selected_agents,
        "trip_constraints": constraints,
        "supervisor_reasoning": reasoning,
        "messages": [AIMessage(content=reasoning)],
        "llm_calls": llm_calls
    }

#guardrail blocked agent
def guardrail_blocked_agent(state: TravelState):
    reason = state.get("final_response") or state.get("guardrail_reason") or (
        "This request was blocked by the travel input guardrail"
    )
    return {
        "final_response": reason,
        "messages": [AIMessage(content=reason)]
    }




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
        "messages": [AIMessage(content="Flight recommendations generated")],
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

#budget agent for analyzing user query weather results and hotel and flight results and checking whether the trip is realistic for the user's budget
def budget_agent(state: TravelState):
    prompt = f"""
Analyze whether this trip is realistic for the user's budget.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{state.get('flight_results', 'Not available.')}

Hotel Results:
{state.get('hotel_results', 'Not available.')}

Weather Results:
{state.get('weather_results', 'Not available.')}

Using ONLY the information provided above, return:
1. **Estimated Cost Categories** — a rough breakdown (flights, hotels, food, local transport, activities).
2. **Budget Risk Areas** — where costs are likely to run higher than expected, especially anything flagged as peak season or high demand above.
3. **Money-Saving Suggestions** — 2-3 practical, specific tips grounded in the data above.
4. **Overall Feasibility** — whether the trip looks realistic, and if a budget was stated in Trip Constraints, whether it's likely sufficient.

Rules:
- If exact live prices are unavailable above, clearly label estimates as approximate rather than presenting them as confirmed prices.
- Do NOT invent specific prices not grounded in the Flight/Hotel data above.
- If a section's input data is missing, acknowledge that briefly rather than guessing.
"""

    budget_text = llm_text(
        "You are a practical, detail-oriented travel budget analyst. Use only the "
        "provided data and clearly flag any estimates as approximate.",
        prompt
    )

    return {
        "budget_results": budget_text,
        "messages": [AIMessage(content="Budget assessment generated.")],
        "llm_calls": state.get("llm_calls", 0) + 1
    }



#This agent will return a detailed itinerary as per user query, flight, hotel, weather and budget agent results
def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{state.get('flight_results', 'Not available.')}

Hotel Results:
{state.get('hotel_results', 'Not available.')}

Weather Results:
{state.get('weather_results', 'Not available.')}

Budget Results:
{state.get('budget_results', 'Not available.')}

Instructions:
- Respect the Trip Constraints above (destination, duration, travel style, and any special preferences) as the frame for the plan.
- Use the Weather Results to shape the plan practically — favor outdoor activities on clear/mild days, and suggest indoor alternatives on days with rain, extreme heat, or poor conditions.
- Use the Budget Results to keep suggested activities and pacing realistic for the stated budget, and call out anywhere the plan pushes close to a stated budget limit.
- Base the itinerary strictly on the Flight, Hotel, Weather, and Budget data provided above. Do NOT invent flight numbers, hotel names, or prices that aren't present in the data.
- If any of the above data is missing or incomplete, acknowledge the gap briefly rather than fabricating details.
- Make the itinerary rational, practical, budget-aware, and easy to follow.
"""

    itinerary_text = llm_text(
        "You are an expert travel planner with best-in-class budget planning. "
        "Ground every recommendation strictly in the data provided.",
        prompt
    )
    

    approval_request = (
        "Please review the generated draft itinerary. Approve it to create the "
        "final polished plan, or provide feedback for revision."
    )

    return {
        "itinerary": itinerary_text,
        "approval_request": approval_request,
        "messages": [AIMessage(content="Draft itinerary created for human review.")],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


#function for human in the loop
def human_approval_agent(state: TravelState):
    review = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "selected_agents": state.get("selected_agents", []),
            "supervisor_reasoning": state.get("supervisor_reasoning", ""),
            "expected_response": {"approved":True , "feedback": "Optional revision feedback"}
        }
    )

    approved = bool(review.get("approved", False))
    human_feedback = str(review.get("feedback","")).strip()

    return {
        "approved": approved,
        "human_feedback": human_feedback,
        "messages": [AIMessage(content="Human review complete.")]
    }


#
def final_agent(state: TravelState):
    if state.get("approved", False):
        review_instruction = "The user approved the draft. Preserve its decisions while polishing it."
    else:
        review_instruction = f"""
The user requested a revision. Apply this feedback carefully:
{state.get('human_feedback', '') or 'Improve the draft before finalizing it.'}
"""

    final_prompt = f"""
Synthesize the provided travel data into a comprehensive, beautiful, and practical travel plan.

---
**INPUT DATA**
- Human Review: {review_instruction}
- User Request: {state['user_query']}
- Trip Constraints: {state.get('trip_constraints', {})}
- Flights: {state.get('flight_results', 'Not available.')}
- Hotels: {state.get('hotel_results', 'Not available.')}
- Weather: {state.get('weather_results', 'Not available.')}
- Budget Analysis: {state.get('budget_results', 'Not available.')}
- Draft Itinerary: {state.get('itinerary', 'Not available.')}

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
[Synthesize the Budget Analysis above into a clear, readable cost breakdown. If it flagged risk areas or savings suggestions, fold those in naturally rather than repeating the analysis verbatim.]

### 7. 💡 Final Recommendations
[Provide 3-4 practical travel tips (e.g., local transit, weather prep, booking advice) specific to this destination.]

**CRITICAL INSTRUCTIONS:**
- Follow the Human Review instruction above above all else — either preserve the approved draft's decisions while polishing wording/formatting, or apply the requested feedback precisely.
- Do NOT invent flights, hotels, prices, or weather conditions. Stick strictly to the provided input data.
- If any section of the input data is empty or missing, gracefully acknowledge it and advise the user on how to find that information.
- Keep the tone professional, inspiring, and highly actionable.
"""

    final_text = llm_text(
        "You are an expert, high-end travel concierge. Your goal is to format raw "
        "travel data into visually appealing, highly practical, and easy-to-read "
        "itineraries, strictly honoring any human review instructions given.",
        final_prompt
    )

    return {
        "final_response": final_text,
        "messages": [AIMessage(content=final_text)],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


#"label the router returns": "node to go to"
ROUTE_MAP = {
    "guardrail_blocked":"guardrail_blocked",
    "flight_agent": "flight_agent",
    "hotel_agent":"hotel_agent",
    "weather_agent":"weather_agent",
    "budget_agent": "budget_agent",
    "itinerary_agent": "itinerary_agent"
}


def selected_agents(state: TravelState) -> list[str]:
    selected = state.get("selected_agents",[])
    return [agent for agent in AGENT_ORDER if agent in selected]

#if guardrails not blocked then supervisor selects agents and this function returns the first agent in order
def route_from_supervisor(state: TravelState) -> str:
    if not state.get("guardrail_allowed", True):
        return "guardrail_blocked"

    selected = selected_agents(state)

    #itinerary agent always runs
    return selected[0] if selected else "itinerary_agent"


# Builds a router that, after current_agent runs,
# sends the graph to the next supervisor selected agent in AGENT_ORDER (falling back to itinerary_agent).
def route_after_agent(current_agent: str):
    #closure function as it remembers current_agent from outer function
    def route(state: TravelState) -> str:
        #list of agents the supervisor chose
        selected = selected_agents(state)
        current_index = AGENT_ORDER.index(current_agent)
        
        for next_agent in AGENT_ORDER[current_index + 1:]:
            if next_agent in selected:
                return next_agent
        
        return "itinerary_agent"

    return route

#building the graph

workflow = StateGraph(TravelState)

#adding nodes
workflow.add_node("supervisor", supervisor_agent)
workflow.add_node("guardrail_blocked", guardrail_blocked_agent)
workflow.add_node("flight_agent", flight_agent)
workflow.add_node("hotel_agent", hotel_agent)
workflow.add_node("weather_agent", weather_agent)
workflow.add_node("budget_agent", budget_agent)
workflow.add_node("itinerary_agent", itinerary_agent)
workflow.add_node("human_approval", human_approval_agent)
workflow.add_node("final_agent", final_agent)

#add edges
workflow.add_edge(START, "supervisor")
workflow.add_conditional_edges("supervisor", route_from_supervisor, ROUTE_MAP)

for name in ["flight_agent", "hotel_agent", "weather_agent", "budget_agent"]:
    workflow.add_conditional_edges(name, route_after_agent(name), ROUTE_MAP)

#after selected agents agents run
workflow.add_edge("itinerary_agent", "human_approval")
workflow.add_edge("human_approval", "final_agent")
workflow.add_edge("final_agent", END)
#if guardrails block user request in guardrail_blocked_agent then graph will come to end
workflow.add_edge("guardrail_blocked", END)


DATABASE_URL = get_database_url()

_conn = psycopg.connect(
    DATABASE_URL,
    autocommit=True,
    row_factory=dict_row
)

checkpointer = PostgresSaver(_conn)

checkpointer.setup()

travel_workflow = workflow.compile(checkpointer=checkpointer)


#check whether the graph paused and, if so, pull out the data passed to interrupt()
def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return None
    
    first_interrupt = interrupts[0]
    payload = getattr(first_interrupt, "value", first_interrupt)
    return payload if isinstance(payload, dict) else {"value": payload}



#converts langgraph's raw state into the JSON shape the frontend expects:
def _serialize_result(result: dict[str, Any], thread_id: str) -> dict[str, Any]:
    messages = result.get("messages", [])
    last_message = messages[-1].content if messages else ""
    answer = result.get("final_response") or last_message
    interrupt_payload = _interrupt_payload(result)
    
    
    if interrupt_payload:
        answer = interrupt_payload.get("draft_itinerary") or result.get("itinerary", "")

    return {
        "thread_id": thread_id,
        "answer": answer,
        "requires_approval": interrupt_payload is not None,
        "approval_request": (
            interrupt_payload.get("approval_request", "")
            if interrupt_payload
            else result.get("approval_request", "")
        ),
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "weather_results": result.get("weather_results", ""),
        "budget_results": result.get("budget_results", ""),
        "itinerary": (
            interrupt_payload.get("draft_itinerary")
            if interrupt_payload
            else result.get("itinerary", "")
        ),
        "selected_agents": result.get("selected_agents", []),
        "trip_constraints":result.get("trip_constraints",{}),
        "supervisor_reasoning": result.get("supervisor_reasoning",""),
        "guardrail_allowed": result.get("guardrail_allowed",True),
        "approved": result.get("approved"),
        "human_feedback": result.get("human_feedback",""),
        "llm_calls":result.get("llm_calls",0)
    }



#function for fastapi
def run_travel_agent(user_input: str, thread_id: str | None = None):
    '''Start a new travel planning run and pause at human approval'''
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    
    result = travel_workflow.invoke(
        #empty initial state
        {
            "messages": [HumanMessage(content=user_input)],
            "user_query": user_input,
            "guardrail_allowed": True,
            "guardrail_reason": "",
            "selected_agents": [],
            "trip_constraints": empty_constraints(),
            "supervisor_reasoning": "",
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "budget_results": "",
            "itinerary": "",
            "approval_request": "",
            "approved": False,
            "human_feedback": "",
            "final_response": "",
            "llm_calls": 0
        },
        config=config
    )

    return _serialize_result(result, thread_id)

#resume the paused langgraph thread after human review
def resume_travel_agent(thread_id: str, approved: bool, feedback: str = ""):
    if not thread_id:
        raise ValueError("thread_id is required to resume a travel plan.")

    config = {"configurable": {"thread_id": thread_id}}
    result = travel_workflow.invoke(
        Command(
            resume={
                "approved": approved,
                "feedback": feedback.strip(),
            }
        ),
        config=config
    )

    return _serialize_result(result, thread_id)


























    


    


     




    






    