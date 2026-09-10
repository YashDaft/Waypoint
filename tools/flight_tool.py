import os
import re
import requests
import certifi
import airportsdata
import pycountry

from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("AVIATIONSTACK_API_KEY")

DEFAULT_ORIGIN_IATA = os.getenv("DEFAULT_ORIGIN_IATA","BOM")

BASE_URL = "https://api.aviationstack.com/v1/flights"

AIRPORTS = airportsdata.load("IATA")


COUNTRY_ALIASES = {
    # --- North America & Caribbean ---
    "usa": "US",
    "u.s.a": "US",
    "u.s.a.": "US",
    "u.s.": "US",
    "us": "US",
    "united states": "US",
    "united states of america": "US",
    "america": "US",
    "canada": "CA",
    "can": "CA",
    "mexico": "MX",
    "mex": "MX",
    "dominican republic": "DO",
    "dr": "DO",
    "dom rep": "DO",
    "cuba": "CU",
    "jamaica": "JM",
    "bahamas": "BS",
    "the bahamas": "BS",
    "puerto rico": "PR",
    "costa rica": "CR",
    "panama": "PA",

    # --- Europe ---
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "britain": "GB",
    "great britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "france": "FR",
    "french republic": "FR",
    "germany": "DE",
    "deutschland": "DE",
    "de": "DE",
    "italy": "IT",
    "italia": "IT",
    "spain": "ES",
    "espana": "ES",
    "españa": "ES",
    "portugal": "PT",
    "greece": "GR",
    "turkey": "TR",
    "turkiye": "TR",
    "türkiye": "TR",
    "netherlands": "NL",
    "the netherlands": "NL",
    "holland": "NL",
    "switzerland": "CH",
    "swiss": "CH",
    "austria": "AT",
    "belgium": "BE",
    "ireland": "IE",
    "eire": "IE",
    "republic of ireland": "IE",
    "croatia": "HR",
    "hrvatska": "HR",
    "iceland": "IS",
    "norway": "NO",
    "sweden": "SE",
    "finland": "FI",
    "denmark": "DK",
    "poland": "PL",
    "czech republic": "CZ",
    "czechia": "CZ",
    "hungary": "HU",
    "vatican": "VA",
    "vatican city": "VA",

    # --- Asia & Middle East ---
    "india": "IN",
    "bharat": "IN",
    "japan": "JP",
    "nippon": "JP",
    "china": "CN",
    "prc": "CN",
    "people's republic of china": "CN",
    "thailand": "TH",
    "siam": "TH",
    "vietnam": "VN",
    "viet nam": "VN",
    "indonesia": "ID",
    "malaysia": "MY",
    "singapore": "SG",
    "sg": "SG",
    "philippines": "PH",
    "the philippines": "PH",
    "south korea": "KR",
    "korea": "KR",
    "republic of korea": "KR",
    "uae": "AE",
    "u.a.e.": "AE",
    "united arab emirates": "AE",
    "emirates": "AE",
    "dubai": "AE",  # Frequently passed as a country by users in travel prompts
    "saudi arabia": "SA",
    "saudi": "SA",
    "ksa": "SA",
    "qatar": "QA",
    "israel": "IL",
    "jordan": "JO",
    "maldives": "MV",
    "the maldives": "MV",
    "sri lanka": "LK",
    "taiwan": "TW",
    "hong kong": "HK",
    "hk": "HK",

    # --- Oceania ---
    "australia": "AU",
    "oz": "AU",
    "aussie": "AU",
    "new zealand": "NZ",
    "nz": "NZ",
    "fiji": "FJ",

    # --- South America ---
    "brazil": "BR",
    "brasil": "BR",
    "argentina": "AR",
    "peru": "PE",
    "colombia": "CO",
    "chile": "CL",

    # --- Africa ---
    "egypt": "EG",
    "south africa": "ZA",
    "rsa": "ZA",
    "morocco": "MA",
    "kenya": "KE",
    "tanzania": "TZ",
    "zanzibar": "TZ",  # Frequently used travel alias
    "mauritius": "MU",
    "seychelles": "SC"
}


COUNTRY_PRIMARY_AIRPORTS = {
    # --- North America & Caribbean ---
    "US": "JFK",  # United States (John F. Kennedy Intl, NY / Alt: ATL, LAX)
    "CA": "YYZ",  # Canada (Toronto Pearson Intl)
    "MX": "MEX",  # Mexico (Mexico City Benito Juárez Intl)
    "DO": "PUJ",  # Dominican Republic (Punta Cana Intl - Primary for Tourism)
    "CU": "HAV",  # Cuba (Jose Marti Intl, Havana)
    "JM": "MBJ",  # Jamaica (Sangster Intl, Montego Bay)
    "BS": "NAS",  # Bahamas (Lynden Pindling Intl, Nassau)
    "PR": "SJU",  # Puerto Rico (Luis Muñoz Marín Intl, San Juan)
    "CR": "SJO",  # Costa Rica (Juan Santamaría Intl, San José)
    "PA": "PTY",  # Panama (Tocumen Intl, Panama City)

    # --- Europe ---
    "GB": "LHR",  # United Kingdom (London Heathrow)
    "FR": "CDG",  # France (Paris Charles de Gaulle)
    "DE": "FRA",  # Germany (Frankfurt Airport)
    "IT": "FCO",  # Italy (Rome Leonardo da Vinci–Fiumicino)
    "ES": "MAD",  # Spain (Madrid-Barajas)
    "PT": "LIS",  # Portugal (Humberto Delgado, Lisbon)
    "GR": "ATH",  # Greece (Athens International)
    "TR": "IST",  # Turkey (Istanbul Airport)
    "NL": "AMS",  # Netherlands (Amsterdam Airport Schiphol)
    "CH": "ZRH",  # Switzerland (Zurich Airport)
    "AT": "VIE",  # Austria (Vienna International)
    "BE": "BRU",  # Belgium (Brussels Airport)
    "IE": "DUB",  # Ireland (Dublin Airport)
    "HR": "ZAG",  # Croatia (Zagreb Airport / Tourism Alt: SPU)
    "IS": "KEF",  # Iceland (Keflavík International, Reykjavík)
    "NO": "OSL",  # Norway (Oslo Gardermoen)
    "SE": "ARN",  # Sweden (Stockholm Arlanda)
    "FI": "HEL",  # Finland (Helsinki-Vantaa)
    "DK": "CPH",  # Denmark (Copenhagen Airport)
    "PL": "WAW",  # Poland (Warsaw Chopin)
    "CZ": "PRG",  # Czech Republic (Václav Havel Airport Prague)
    "HU": "BUD",  # Hungary (Budapest Ferenc Liszt Intl)
    "VA": "FCO",  # Vatican City (Serviced via Rome Fiumicino, Italy)

    # --- Asia & Middle East ---
    "IN": "DEL",  # India (Indira Gandhi Intl, New Delhi / Alt: BOM)
    "JP": "HND",  # Japan (Tokyo Haneda / Alt: NRT)
    "CN": "PEK",  # China (Beijing Capital / Alt: PVG)
    "TH": "BKK",  # Thailand (Suvarnabhumi, Bangkok)
    "VN": "SGN",  # Vietnam (Tan Son Nhat, Ho Chi Minh City / Alt: HAN)
    "ID": "CGK",  # Indonesia (Soekarno-Hatta, Jakarta / Tourism Alt: DPS)
    "MY": "KUL",  # Malaysia (Kuala Lumpur Intl)
    "SG": "SIN",  # Singapore (Singapore Changi)
    "PH": "MNL",  # Philippines (Ninoy Aquino Intl, Manila)
    "KR": "ICN",  # South Korea (Incheon Intl, Seoul)
    "AE": "DXB",  # United Arab Emirates (Dubai International)
    "SA": "JED",  # Saudi Arabia (King Abdulaziz Intl, Jeddah / Alt: RUH)
    "QA": "DOH",  # Qatar (Hamad International, Doha)
    "IL": "TLV",  # Israel (Ben Gurion, Tel Aviv)
    "JO": "AMM",  # Jordan (Queen Alia Intl, Amman)
    "MV": "MLE",  # Maldives (Velana International, Malé)
    "LK": "CMB",  # Sri Lanka (Bandaranaike Intl, Colombo)
    "TW": "TPE",  # Taiwan (Taiwan Taoyuan Intl, Taipei)
    "HK": "HKG",  # Hong Kong (Hong Kong International)

    # --- Oceania ---
    "AU": "SYD",  # Australia (Sydney Kingsford Smith)
    "NZ": "AKL",  # New Zealand (Auckland Airport)
    "FJ": "NAN",  # Fiji (Nadi International)

    # --- South America ---
    "BR": "GRU",  # Brazil (São Paulo/Guarulhos Intl)
    "AR": "EZE",  # Argentina (Ministro Pistarini Intl, Buenos Aires)
    "PE": "LIM",  # Peru (Jorge Chávez Intl, Lima)
    "CO": "BOG",  # Colombia (El Dorado Intl, Bogotá)
    "CL": "SCL",  # Chile (Arturo Merino Benítez Intl, Santiago)

    # --- Africa ---
    "EG": "CAI",  # Egypt (Cairo International)
    "ZA": "JNB",  # South Africa (O.R. Tambo Intl, Johannesburg / Alt: CPT)
    "MA": "CMN",  # Morocco (Mohammed V Intl, Casablanca / Tourism Alt: RAK)
    "KE": "NBO",  # Kenya (Jomo Kenyatta Intl, Nairobi)
    "TZ": "DAR",  # Tanzania (Julius Nyerere Intl, Dar es Salaam / Alt: ZNZ)
    "MU": "MRU",  # Mauritius (Sir Seewoosagur Ramgoolam Intl)
    "SC": "SEZ",  # Seychelles (Seychelles International, Mahé)
}

CITY_PRIMARY_AIRPORTS = {
    # --- India ---
    "delhi": "DEL",
    "new delhi": "DEL",
    "mumbai": "BOM",
    "bombay": "BOM",
    "bangalore": "BLR",
    "bengaluru": "BLR",
    "hyderabad": "HYD",
    "chennai": "MAA",
    "madras": "MAA",
    "kolkata": "CCU",
    "calcutta": "CCU",
    "goa": "GOI",  # Dabolim Airport (Alt: GOX for Mopa)
    "goa mopa": "GOX",
    "ahmedabad": "AMD",
    "pune": "PNQ",
    "jaipur": "JAI",
    "kochi": "COK",
    "cochin": "COK",
    "thiruvananthapuram": "TRV",
    "trivandrum": "TRV",
    "varanasi": "VNS",
    "amritsar": "ATQ",
    "lucknow": "LKO",
    "guwahati": "GAU",
    "srinagar": "SXR",
    "bhopal": "BHO",
    "indore": "IDR",
    "nagpur": "NAG",
    "coimbatore": "CJB",
    "visakhapatnam": "VTZ",

    # --- Middle East & Africa ---
    "dubai": "DXB",
    "abu dhabi": "AUH",
    "sharjah": "SHJ",
    "doha": "DOH",
    "riyadh": "RUH",
    "jeddah": "JED",
    "muscat": "MCT",
    "cairo": "CAI",
    "istanbul": "IST",
    "johannesburg": "JNB",
    "cape town": "CPT",
    "casablanca": "CMN",
    "marrakech": "RAK",
    "nairobi": "NBO",

    # --- Europe ---
    "london": "LHR",  # Heathrow (Alt: LGW, STN)
    "paris": "CDG",   # Charles de Gaulle (Alt: ORY)
    "frankfurt": "FRA",
    "munich": "MUC",
    "amsterdam": "AMS",
    "rome": "FCO",
    "milan": "MXP",
    "madrid": "MAD",
    "barcelona": "BCN",
    "lisbon": "LIS",
    "vienna": "VIE",
    "zurich": "ZRH",
    "geneva": "GVA",
    "brussels": "BRU",
    "athens": "ATH",
    "prague": "PRG",
    "budapest": "BUD",
    "dublin": "DUB",
    "edinburgh": "EDI",
    "copenhagen": "CPH",
    "stockholm": "ARN",
    "oslo": "OSL",
    "helsinki": "HEL",

    # --- Asia-Pacific ---
    "singapore": "SIN",
    "bangkok": "BKK",
    "phuket": "HKT",
    "bali": "DPS",
    "denpasar": "DPS",
    "jakarta": "CGK",
    "kuala lumpur": "KUL",
    "tokyo": "HND",    # Haneda (Alt: NRT)
    "osaka": "KIX",
    "seoul": "ICN",
    "beijing": "PEK",
    "shanghai": "PVG",
    "hong kong": "HKG",
    "taipei": "TPE",
    "manila": "MNL",
    "hanoi": "HAN",
    "ho chi minh city": "SGN",
    "saigon": "SGN",
    "male": "MLE",
    "colombo": "CMB",
    "sydney": "SYD",
    "melbourne": "MEL",
    "auckland": "AKL",

    # --- Americas ---
    "new york": "JFK",     # JFK (Alt: EWR, LGA)
    "los angeles": "LAX",
    "chicago": "ORD",
    "san francisco": "SFO",
    "miami": "MIA",
    "las vegas": "LAS",
    "orlando": "MCO",
    "toronto": "YYZ",
    "vancouver": "YVR",
    "mexico city": "MEX",
    "cancun": "CUN",
    "rio de janeiro": "GIG",
    "sao paulo": "GRU",
    "buenos aires": "EZE"
}


#for cleaning the text
def clean_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    stop_words = [
        "flight", "flights", "ticket", "trip", "travel",
        "plan", "complete", "days", "day", "including", "hotel",
        "hotels", "sightseeing", "under", "budget", "info", "information"
    ]
    words = [w for w in text.split() if w not in stop_words]
    return " ".join(words).strip()

#for converting country name to code
def country_name_to_code(text: str):
    text = clean_text(text)

    if text in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[text]
    
    try:
        country = pycountry.countries.lookup(text)
        return country.alpha_2

    except LookupError:
        pass

    for country in pycountry.countries:
        country_name = country.name.lower()
        if country_name in text:
            return country.alpha_2
    
    for alias, code in COUNTRY_ALIASES.items():
        if alias in text:
            return code

    return None


print(pycountry.countries)

#for checking if the airport matches the country
def airport_country_matches(airport: dict, country_code: str):
    airport_country = str(airport.get("country", "")).upper().strip()

    if airport_country == country_code:
        return True
    
    try:
        country = pycountry.countries.get(alpha_2=country_code)
        if country and airport_country.lower() == country.name.lower():
            return True
    except Exception:
        pass

    return False

#for getting the best airport in the country

def get_best_airport_for_country(country_code: str):
    preferred = COUNTRY_PRIMARY_AIRPORTS.get(country_code.upper())

    if preferred and preferred in AIRPORTS:
        return preferred
    
    candidates = []

    for iata, airport in AIRPORTS.items():
        if not iata:
            continue

        if airport_country_matches(airport, country_code):
            name = str(airport.get("name", "")).lower()
            city = str(airport.get("city", "")).lower()
        
            score = 0

            if "international" in name:
                score += 50
            if "intl" in name:
                score +=40
            if "capital" in name:
                score += 20
            if city:
                score += 5
            
            candidates.append((score, iata))

    if not candidates:
        return None
    
    candidates.sort(reverse=True)
    return candidates[0][1]

def resolve_location_to_iata(location: str):
    '''
    Converts country/city/airports/IATA into IATA code.

    Examples:
    India -> DEL
    Japan -> NRT
    USA -> JFK
    Tokyo -> NRT
    '''

    if not location:
        return None

    raw_location = location.strip()

    if re.fullmatch(r"[A-Za-z]{3}", raw_location):
        code = raw_location.upper()
        if code in AIRPORTS:
            return code
        
    location_clean = clean_text(raw_location)

    if not location_clean:
        return None
    
    if location_clean in CITY_PRIMARY_AIRPORTS:
        return CITY_PRIMARY_AIRPORTS[location_clean]
    
    country_code = country_name_to_code(raw_location)

    if country_code:
        airport = get_best_airport_for_country(country_code)
        if airport:
            return airport
        
    city_matches = []

    for iata, airport in AIRPORTS.items():
        city = str(airport.get("city", "")).lower().strip()
        name = str(airport.get("name", "")).lower().strip()

        score = 0

        if city == location_clean:
            score += 100
        elif location_clean in city:
            score += 70
        if location_clean in name:
            score += 50
        if "international" in name:
            score += 10
        
        if score > 0:
            city_matches.append((score, iata))
        
    if city_matches:
        city_matches.sort(reverse=True)
        return city_matches[0][1]
    
    return None

  
def find_location_mentions(query: str):
    """
    Finds country or city names inside a natural language query.
    """

    q = query.lower()
    mentions = []

    # Country aliases
    for alias in COUNTRY_ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", q):
            mentions.append(alias)

    # Country names from pycountry
    for country in pycountry.countries:
        name = country.name.lower()
        if len(name) >= 4 and re.search(rf"\b{re.escape(name)}\b", q):
            mentions.append(name)

    # City names from our preferred city map
    for city in CITY_PRIMARY_AIRPORTS:
        if re.search(rf"\b{re.escape(city)}\b", q):
            mentions.append(city)

    # Remove duplicate while keeping order
    unique_mentions = []
    for item in mentions:
        if item not in unique_mentions:
            unique_mentions.append(item)

    return unique_mentions


def parse_route(query: str):
    """
    Returns:
    dep_iata, arr_iata

    Can return:
    None, None  -> global live flights
    DAC, NRT    -> filtered route
    DAC, None   -> all flights from DAC
    None, NRT   -> all flights to NRT
    """

    q = query.strip()
    q_lower = q.lower()

    # Global / all-country query
    global_keywords = [
        "all country",
        "all countries",
        "global flight",
        "global flights",
        "all flight",
        "all flights",
        "worldwide flight",
        "worldwide flights",
    ]

    if any(keyword in q_lower for keyword in global_keywords):
        return None, None

    # Direct IATA code route: DAC to NRT
    codes = re.findall(r"\b[A-Z]{3}\b", q)

    if len(codes) >= 2:
        dep = codes[0].upper()
        arr = codes[1].upper()
        return dep, arr

    # Pattern: from X to Y
    match = re.search(
        r"\bfrom\s+(.+?)\s+\bto\s+(.+?)(?:\s+(?:on|for|under|including|with|in|at)\b|[.!?]|$)",
        q_lower,
    )

    if match:
        origin_text = match.group(1)
        dest_text = match.group(2)

        dep_iata = resolve_location_to_iata(origin_text)
        arr_iata = resolve_location_to_iata(dest_text)

        return dep_iata, arr_iata

    # Pattern: to Y from X
    match = re.search(
        r"\bto\s+(.+?)\s+\bfrom\s+(.+?)(?:\s+(?:on|for|under|including|with|in|at)\b|[.!?]|$)",
        q_lower,
    )

    if match:
        dest_text = match.group(1)
        origin_text = match.group(2)

        dep_iata = resolve_location_to_iata(origin_text)
        arr_iata = resolve_location_to_iata(dest_text)

        return dep_iata, arr_iata

    # Pattern: flights from X
    match = re.search(r"\bfrom\s+(.+?)(?:[.!?]|$)", q_lower)

    if match:
        origin_text = match.group(1)
        dep_iata = resolve_location_to_iata(origin_text)
        return dep_iata, None

    # Pattern: flights to X
    match = re.search(r"\bto\s+(.+?)(?:[.!?]|$)", q_lower)

    if match:
        dest_text = match.group(1)
        arr_iata = resolve_location_to_iata(dest_text)
        return None, arr_iata

    # Fallback: find country/city mentions
    mentions = find_location_mentions(q)

    if len(mentions) >= 2:
        dep_iata = resolve_location_to_iata(mentions[0])
        arr_iata = resolve_location_to_iata(mentions[1])
        return dep_iata, arr_iata

    if len(mentions) == 1:
        arr_iata = resolve_location_to_iata(mentions[0])
        return DEFAULT_ORIGIN_IATA, arr_iata

    return None, None


def format_flight(flight: dict):
    airline = flight.get("airline", {}).get("name") or "Unknown airline"
    flight_number = flight.get("flight", {}).get("iata") or "Unknown flight number"
    status = flight.get("flight_status") or "Unknown"

    dep = flight.get("departure", {}) or {}
    arr = flight.get("arrival", {}) or {}

    dep_airport = dep.get("airport") or "Unknown departure airport"
    dep_iata = dep.get("iata") or "Unknown"
    dep_terminal = dep.get("terminal") or "N/A"
    dep_gate = dep.get("gate") or "N/A"
    dep_scheduled = dep.get("scheduled") or "Unknown"
    dep_delay = dep.get("delay")
    dep_delay_text = f"{dep_delay} minutes" if dep_delay is not None else "N/A"

    arr_airport = arr.get("airport") or "Unknown arrival airport"
    arr_iata = arr.get("iata") or "Unknown"
    arr_terminal = arr.get("terminal") or "N/A"
    arr_gate = arr.get("gate") or "N/A"
    arr_scheduled = arr.get("scheduled") or "Unknown"
    arr_delay = arr.get("delay")
    arr_delay_text = f"{arr_delay} minutes" if arr_delay is not None else "N/A"

    return f"""
Airline: {airline}
Flight: {flight_number}
Status: {status}

Departure:
- Airport: {dep_airport}
- IATA: {dep_iata}
- Terminal: {dep_terminal}
- Gate: {dep_gate}
- Scheduled: {dep_scheduled}
- Delay: {dep_delay_text}

Arrival:
- Airport: {arr_airport}
- IATA: {arr_iata}
- Terminal: {arr_terminal}
- Gate: {arr_gate}
- Scheduled: {arr_scheduled}
- Delay: {arr_delay_text}
""".strip()


def search_flights(query: str, limit: int = 10):
    if not API_KEY:
        return (
            "Flight API error: AVIATIONSTACK_API_KEY is missing.\n"
            "Please add this in your .env file:\n"
            "AVIATIONSTACK_API_KEY=your_api_key_here"
        )

    dep_iata, arr_iata = parse_route(query)

    params = {
        "access_key": API_KEY,
        "limit": min(limit, 100),
    }

    if dep_iata:
        params["dep_iata"] = dep_iata

    if arr_iata:
        params["arr_iata"] = arr_iata

    try:
        response = requests.get(BASE_URL, params=params, timeout=30)
        data = response.json()
    except requests.exceptions.RequestException as e:
        return f"Flight API request failed: {e}"
    except ValueError:
        return "Flight API returned invalid JSON."

    if "error" in data:
        error = data["error"]
        return (
            "Flight API error:\n"
            f"Code: {error.get('code', 'Unknown')}\n"
            f"Message: {error.get('message', 'Unknown error')}"
        )

    flight_data = data.get("data", [])

    if not flight_data:
        route_text = ""

        if dep_iata and arr_iata:
            route_text = f" for route {dep_iata} to {arr_iata}"
        elif dep_iata:
            route_text = f" from {dep_iata}"
        elif arr_iata:
            route_text = f" to {arr_iata}"

        return (
            f"No live flight data found{route_text}.\n\n"
            "Note: AviationStack provides live/status flight data, not ticket prices. "
            "For actual fare prices, use a flight-pricing API such as Amadeus."
        )

    route_info = "Global live flights"

    if dep_iata and arr_iata:
        route_info = f"Live flights from {dep_iata} to {arr_iata}"
    elif dep_iata:
        route_info = f"Live flights from {dep_iata}"
    elif arr_iata:
        route_info = f"Live flights to {arr_iata}"

    formatted_flights = [format_flight(flight) for flight in flight_data[:limit]]

    return f"{route_info}\n\n" + "\n\n---\n\n".join(formatted_flights)


if __name__ == "__main__":
    print(search_flights("Plan a seven days trip from India"))
    print("\n" + "=" * 80 + "\n")
    print(search_flights("all country flight info"))




    



    






 
    

            

            
            
            
    
    






    

    
    





