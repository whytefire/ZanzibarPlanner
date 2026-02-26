"""
Package deal checker — searches for all-inclusive Zanzibar packages
from multiple SA travel agencies and deal aggregators.

Uses:
1. DuckDuckGo web search for broad deal discovery
2. Playwright browser automation for scraping specific travel agency sites
3. Direct HTTP requests where possible
"""

import re
import json
import logging
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

KNOWN_PACKAGE_URLS = [
    {
        "name": "Quintrip Zanzibar",
        "url": "https://www.quintrip.co.za/zanzibar-holiday-packages",
        "selector": ".package-card, .holiday-package, [class*='package']",
    },
    {
        "name": "AfricaStay Zanzibar",
        "url": "https://holidays.africastay.com/?s=zanzibar+all+inclusive",
        "selector": ".product, .package, [class*='deal']",
    },
    {
        "name": "Travelstart Zanzibar",
        "url": "https://www.travelstart.co.za/lp/cheap-flights-from-johannesburg-to-zanzibar",
        "selector": "[class*='price'], [class*='deal']",
    },
]


def search_packages_web(config: dict, date_range: dict) -> list:
    """Discover package deals via DuckDuckGo search."""
    deals = []
    queries = config.get("deal_search_queries", [])

    depart = date_range["depart"]
    return_date = date_range["return"]
    label = date_range["label"]

    extra_queries = [
        f"Zanzibar all inclusive package from Johannesburg {depart} to {return_date}",
        f"Zanzibar holiday deal flights hotel all inclusive October 2026 South Africa",
        f"best Zanzibar package deals {datetime.now().strftime('%B %Y')}",
    ]
    all_queries = queries + extra_queries

    with DDGS() as ddgs:
        for query in all_queries:
            try:
                results = list(ddgs.text(query, max_results=10))
                for r in results:
                    full_text = f"{r.get('title', '')} {r.get('body', '')}"
                    price = _extract_package_price(full_text)
                    is_ai = _is_all_inclusive(full_text)

                    if not _is_relevant(full_text):
                        continue

                    deals.append({
                        "source": "web_search",
                        "deal_type": "package" if is_ai else "mixed",
                        "date_range": label,
                        "provider": _extract_domain(r.get("href", "")),
                        "title": r.get("title", "")[:200],
                        "price_zar": price * 2 if price else None,
                        "price_per_person": price,
                        "url": r.get("href", ""),
                        "details": {
                            "snippet": r.get("body", ""),
                            "search_query": query,
                        },
                        "is_all_inclusive": is_ai,
                    })
            except Exception as e:
                logger.warning(f"Web search failed for '{query}': {e}")

    return _deduplicate(deals)


def scrape_package_sites(config: dict, date_range: dict) -> list:
    """Scrape known travel agency sites using Playwright."""
    deals = []
    label = date_range["label"]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("Playwright not installed — skipping site scraping")
        return deals

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for site in KNOWN_PACKAGE_URLS:
                try:
                    page = browser.new_page()
                    page.goto(site["url"], wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(2000)

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")

                    site_deals = _parse_package_page(soup, site["name"], site["url"], label)
                    deals.extend(site_deals)
                    logger.info(f"  {site['name']}: found {len(site_deals)} deals")

                    page.close()
                except Exception as e:
                    logger.warning(f"  Failed to scrape {site['name']}: {e}")

            browser.close()
    except Exception as e:
        logger.warning(f"Playwright scraping failed: {e}")

    return deals


def scrape_specific_resort_sites(date_range: dict) -> list:
    """Check specific resort websites for direct booking deals."""
    deals = []
    label = date_range["label"]

    resort_urls = [
        ("Baraza Resort & Spa", "https://www.baraza-zanzibar.com/"),
        ("Royal Zanzibar", "https://www.royalzanzibar.com/"),
        ("Melia Zanzibar", "https://www.melia.com/en/hotels/tanzania/zanzibar/melia-zanzibar"),
    ]

    for resort_name, url in resort_urls:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                text = soup.get_text(" ", strip=True)

                price = _extract_package_price(text)
                specials = _find_special_offers(text)

                if price or specials:
                    deals.append({
                        "source": "resort_direct",
                        "deal_type": "hotel",
                        "date_range": label,
                        "provider": resort_name,
                        "title": f"{resort_name} — Direct Booking",
                        "price_zar": price,
                        "price_per_person": price,
                        "url": url,
                        "details": {"specials": specials},
                        "is_all_inclusive": "all inclusive" in text.lower() or "all-inclusive" in text.lower(),
                    })
        except Exception as e:
            logger.warning(f"Failed to check {resort_name}: {e}")

    return deals


def search_all_packages(config: dict, date_range: dict) -> list:
    """Run all package search methods for a given date range."""
    label = date_range["label"]
    logger.info(f"Searching packages for {label}")

    all_deals = []

    web_deals = search_packages_web(config, date_range)
    all_deals.extend(web_deals)
    logger.info(f"  Web search found {len(web_deals)} package results")

    scraped_deals = scrape_package_sites(config, date_range)
    all_deals.extend(scraped_deals)

    resort_deals = scrape_specific_resort_sites(date_range)
    all_deals.extend(resort_deals)
    logger.info(f"  Resort direct found {len(resort_deals)} results")

    return all_deals


def _parse_package_page(soup: BeautifulSoup, site_name: str, base_url: str, label: str) -> list:
    """Extract deal information from a package site's HTML."""
    deals = []

    price_patterns = [
        soup.find_all(string=re.compile(r"R\s?[\d,]+\s*(p\.?p\.?s?|per person)", re.I)),
        soup.find_all(string=re.compile(r"from\s+R\s?[\d,]+", re.I)),
        soup.find_all(class_=re.compile(r"price|cost|rate", re.I)),
    ]

    seen = set()
    for elements in price_patterns:
        for elem in elements:
            text = elem.get_text(strip=True) if hasattr(elem, "get_text") else str(elem)
            price = _extract_package_price(text)
            if price and price not in seen:
                seen.add(price)
                parent = elem.parent if hasattr(elem, "parent") else None
                context = ""
                if parent:
                    for _ in range(3):
                        if parent.parent:
                            parent = parent.parent
                    context = parent.get_text(" ", strip=True)[:300]

                link = ""
                if parent:
                    a_tag = parent.find("a", href=True) if hasattr(parent, "find") else None
                    if a_tag:
                        href = a_tag["href"]
                        if href.startswith("/"):
                            from urllib.parse import urljoin
                            href = urljoin(base_url, href)
                        link = href

                deals.append({
                    "source": site_name.lower().replace(" ", "_"),
                    "deal_type": "package",
                    "date_range": label,
                    "provider": site_name,
                    "title": context[:200] if context else f"{site_name} Deal - R{price:,.0f}",
                    "price_zar": price * 2,
                    "price_per_person": price,
                    "url": link or base_url,
                    "details": {"raw_text": text},
                    "is_all_inclusive": _is_all_inclusive(context or text),
                })
    return deals


def _extract_package_price(text: str) -> float | None:
    patterns = [
        r"R\s?([\d,]+)\s*(?:p\.?p\.?s?|per\s*person)",
        r"from\s+R\s?([\d,]+)",
        r"R\s?([\d,]+(?:\.\d{2})?)",
        r"ZAR\s?([\d,]+)",
    ]
    best_price = None
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            try:
                price = float(m.replace(",", ""))
                if 3000 < price < 200000:
                    if best_price is None or price < best_price:
                        best_price = price
            except ValueError:
                continue
    return best_price


def _is_all_inclusive(text: str) -> bool:
    indicators = ["all inclusive", "all-inclusive", "full board", "meals included",
                   "drinks included", "unlimited", "meal plan"]
    text_lower = text.lower()
    return any(ind in text_lower for ind in indicators)


def _is_relevant(text: str) -> bool:
    text_lower = text.lower()
    required = ["zanzibar"]
    bonus = ["johannesburg", "jnb", "south africa", "package", "hotel", "resort",
             "all inclusive", "flight", "deal", "offer", "price", "from r"]
    if not any(r in text_lower for r in required):
        return False
    return any(b in text_lower for b in bonus)


def _find_special_offers(text: str) -> list:
    patterns = [
        r"(\d+%\s*(?:off|discount|saving))",
        r"(stay\s+\d+\s+(?:pay|night).*?(?:\d+))",
        r"(early\s*bird.*?(?:\d+%|discount))",
        r"(special\s+offer.*?(?:R[\d,]+|\d+%))",
        r"(free\s+(?:night|transfer|massage|spa|upgrade))",
    ]
    offers = []
    for p in patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        offers.extend(matches[:2])
    return offers


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return url[:50]


def _deduplicate(deals: list) -> list:
    """Remove near-duplicate deals based on URL and price."""
    seen = set()
    unique = []
    for deal in deals:
        key = (deal.get("url", ""), deal.get("price_per_person"))
        if key not in seen:
            seen.add(key)
            unique.append(deal)
    return unique
