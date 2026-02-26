"""
Flight price checker using multiple sources:
1. Amadeus API (primary - free self-service tier)
2. Web scraping via DuckDuckGo for deal discovery
"""

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

_env_loaded = False


def _load_env():
    """Load variables from .env file if present."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

AMADEUS_API_KEY = os.environ.get("AMADEUS_API_KEY", "")
AMADEUS_API_SECRET = os.environ.get("AMADEUS_API_SECRET", "")
AMADEUS_BASE_URL = os.environ.get("AMADEUS_BASE_URL", "https://test.api.amadeus.com")


def search_flights_amadeus(origin: str, destination: str, depart: str, return_date: str,
                           adults: int = 2, currency: str = "ZAR") -> list:
    """
    Search Amadeus Flight Offers API for real flight prices.
    Free self-service tier: 500 calls/month.
    """
    if not AMADEUS_API_KEY or not AMADEUS_API_SECRET:
        logger.warning("  Amadeus API: no keys set. Check .env file or set AMADEUS_API_KEY & AMADEUS_API_SECRET env vars.")
        return []

    deals = []
    try:
        # Step 1: Get OAuth token
        logger.info("  Amadeus: authenticating...")
        token_resp = requests.post(
            f"{AMADEUS_BASE_URL}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": AMADEUS_API_KEY,
                "client_secret": AMADEUS_API_SECRET,
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
        logger.info("  Amadeus: authenticated successfully")

        # Step 2: Search for flights
        logger.info(f"  Amadeus: searching {origin} -> {destination}, {depart} to {return_date}")
        resp = requests.get(
            f"{AMADEUS_BASE_URL}/v2/shopping/flight-offers",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "originLocationCode": origin,
                "destinationLocationCode": destination,
                "departureDate": depart,
                "returnDate": return_date,
                "adults": adults,
                "currencyCode": currency,
                "max": 20,
                "nonStop": "false",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        # Lookup table for airline names
        carriers = {}
        for code, info in data.get("dictionaries", {}).get("carriers", {}).items():
            carriers[code] = info

        for offer in data.get("data", []):
            price_total = float(offer.get("price", {}).get("grandTotal", 0))
            price_pp = price_total / adults if adults > 0 else price_total

            itineraries = offer.get("itineraries", [])
            outbound = itineraries[0] if len(itineraries) > 0 else {}
            inbound = itineraries[1] if len(itineraries) > 1 else {}

            out_segments = outbound.get("segments", [])
            in_segments = inbound.get("segments", [])
            stops_out = max(0, len(out_segments) - 1)
            stops_in = max(0, len(in_segments) - 1)
            max_stops = max(stops_out, stops_in)

            airline_codes = list(set(
                seg.get("carrierCode", "") for seg in out_segments + in_segments
            ))
            airline_names = [carriers.get(c, c) for c in airline_codes]

            out_duration = outbound.get("duration", "")
            in_duration = inbound.get("duration", "")
            out_duration_str = _format_iso_duration(out_duration)
            in_duration_str = _format_iso_duration(in_duration)

            depart_time = out_segments[0].get("departure", {}).get("at", "") if out_segments else ""
            arrive_time = out_segments[-1].get("arrival", {}).get("at", "") if out_segments else ""

            stops_text = "Direct" if max_stops == 0 else f"{max_stops} stop{'s' if max_stops > 1 else ''}"
            via_airports = []
            if stops_out > 0:
                for seg in out_segments[:-1]:
                    via_airports.append(seg.get("arrival", {}).get("iataCode", ""))

            title_parts = [f"JNB -> ZNZ return R{price_pp:,.0f}"]
            if airline_names:
                title_parts.append(", ".join(airline_names))
            title_parts.append(stops_text)
            if via_airports:
                title_parts.append(f"via {', '.join(via_airports)}")
            if out_duration_str:
                title_parts.append(out_duration_str)

            booking_class = ""
            traveler_pricings = offer.get("travelerPricings", [])
            if traveler_pricings:
                segments_detail = traveler_pricings[0].get("fareDetailsBySegment", [])
                if segments_detail:
                    booking_class = segments_detail[0].get("cabin", "")

            deals.append({
                "source": "amadeus",
                "deal_type": "flight",
                "provider": ", ".join(airline_names) if airline_names else "Amadeus",
                "title": " | ".join(title_parts),
                "price_zar": round(price_total, 2),
                "price_per_person": round(price_pp, 2),
                "url": "",
                "details": {
                    "airlines": airline_names,
                    "airline_codes": airline_codes,
                    "stops_outbound": stops_out,
                    "stops_inbound": stops_in,
                    "via": via_airports,
                    "outbound_duration": out_duration_str,
                    "inbound_duration": in_duration_str,
                    "departure_time": depart_time,
                    "arrival_time": arrive_time,
                    "cabin": booking_class,
                },
                "is_all_inclusive": False,
            })

        logger.info(f"  Amadeus: found {len(deals)} flights")

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        body = ""
        try:
            body = e.response.json() if e.response is not None else ""
        except Exception:
            pass
        if status == 401:
            logger.error("  Amadeus API: authentication failed. Check your API key and secret in .env")
        else:
            logger.warning(f"  Amadeus API error (HTTP {status}): {body}")
    except Exception as e:
        logger.warning(f"  Amadeus API search failed: {e}")

    return deals


def search_flights_web(origin_city: str, destination_city: str, depart: str,
                       return_date: str, currency: str = "ZAR") -> list:
    """Search the web for flight deals using DuckDuckGo."""
    deals = []
    depart_dt = datetime.strptime(depart, "%Y-%m-%d")
    return_dt = datetime.strptime(return_date, "%Y-%m-%d")
    month_year = depart_dt.strftime("%B %Y")

    queries = [
        f"cheap flights {origin_city} to {destination_city} {month_year} return price ZAR",
        f"flights JNB to ZNZ {depart_dt.strftime('%d %B')} to {return_dt.strftime('%d %B %Y')} price",
        f"{origin_city} Zanzibar flight deals {month_year} round trip",
    ]

    with DDGS() as ddgs:
        for query in queries:
            try:
                results = list(ddgs.text(query, max_results=8))
                for r in results:
                    full_text = f"{r.get('title', '')} {r.get('body', '')}"
                    price = _extract_flight_price(full_text, currency)
                    url = r.get("href", "")
                    domain = _extract_domain(url)

                    if not _is_flight_relevant(full_text):
                        continue

                    deals.append({
                        "source": "web_search",
                        "deal_type": "flight",
                        "provider": domain,
                        "title": r.get("title", "")[:200],
                        "price_zar": price * 2 if price else None,
                        "price_per_person": price,
                        "url": url,
                        "details": {"snippet": r.get("body", "")[:200]},
                        "is_all_inclusive": False,
                    })
            except Exception as e:
                logger.warning(f"Web search failed for query '{query}': {e}")

    return _deduplicate(deals)


def search_all_flights(config: dict, date_range: dict) -> list:
    """Run all flight search methods for a given date range."""
    origin = config["search"]["origin"]
    destination = config["search"]["destination"]
    origin_city = config["search"]["origin_city"]
    dest_city = config["search"]["destination_city"]
    depart = date_range["depart"]
    return_date = date_range["return"]
    adults = config["search"]["adults"]
    currency = config["search"]["currency"]

    all_deals = []
    label = date_range["label"]

    logger.info(f"Searching flights for {label}: {depart} to {return_date}")

    # Primary: Amadeus API (real flight prices)
    amadeus_deals = search_flights_amadeus(origin, destination, depart, return_date, adults, currency)
    for d in amadeus_deals:
        d["date_range"] = label
    all_deals.extend(amadeus_deals)

    # Secondary: Web search for broader deal discovery
    web_deals = search_flights_web(origin_city, dest_city, depart, return_date, currency)
    for d in web_deals:
        d["date_range"] = label
    all_deals.extend(web_deals)
    logger.info(f"  Web search found {len(web_deals)} flight results")

    return all_deals


# --- Helpers ---

def _format_iso_duration(iso_dur: str) -> str:
    """Convert ISO 8601 duration like PT7H30M to '7h 30m'."""
    if not iso_dur:
        return ""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso_dur)
    if match:
        hours = match.group(1) or "0"
        minutes = match.group(2) or "0"
        return f"{hours}h {minutes}m"
    return iso_dur


def _extract_flight_price(text: str, currency: str = "ZAR") -> float | None:
    """Extract flight price from text, returning per-person estimate."""
    patterns = [
        (r"R\s?([\d,]+)\s*(?:pp|per\s*person|pps|each)", False),
        (r"from\s+R\s?([\d,]+)", False),
        (r"R\s?([\d,]+(?:\.\d{2})?)", False),
        (r"ZAR\s?([\d,]+)", False),
        (r"\$\s?([\d,]+)", True),
    ]
    candidates = []
    for pattern, is_usd in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            try:
                price = float(m.replace(",", ""))
                if is_usd and currency == "ZAR":
                    price *= 18.5
                if 2000 < price < 80000:
                    candidates.append(price)
            except ValueError:
                continue
    return min(candidates) if candidates else None


def _is_flight_relevant(text: str) -> bool:
    text_lower = text.lower()
    has_destination = any(w in text_lower for w in ["zanzibar", "znz", "tanzania"])
    has_flight_terms = any(w in text_lower for w in [
        "flight", "fly", "airline", "airport", "book", "cheap",
        "fare", "ticket", "return", "round trip", "one way"
    ])
    return has_destination and has_flight_terms


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return url[:50]


def _deduplicate(deals: list) -> list:
    seen = set()
    unique = []
    for d in deals:
        key = (d.get("url", ""), d.get("price_per_person"))
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique
