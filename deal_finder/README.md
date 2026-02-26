# Zanzibar Deal Finder Agent

Automated agent that scours the internet daily for the best all-inclusive holiday deals from Johannesburg to Zanzibar. Tracks prices over time, detects price drops, and generates rich HTML reports.

## What It Does

- **Searches multiple sources** — Kiwi.com + Amadeus flight APIs, travel agency sites (Quintrip, AfricaStay), resort websites, and web search
- **Tracks prices over time** — SQLite database stores every price found, so you can see trends and detect drops
- **Detects price drops** — Alerts you when a deal drops below its previous best price
- **Generates HTML reports** — Beautiful daily report saved to `results/` with all deals ranked by price
- **Email notifications** — Optional email alerts when price drops are found
- **Configurable** — Edit `config.json` to change dates, destinations, budget, search queries, and more

## Quick Start

### 1. Install Python dependencies

```bash
cd deal_finder
pip install -r requirements.txt
```

### 2. Install Playwright browsers

Playwright enables scraping of travel agency sites (Quintrip, AfricaStay) for package deals.

```bash
playwright install chromium
```

### 3. Set up flight price APIs (recommended)

The all-inclusive package search works out of the box, but for standalone flight prices you need at least one API key. Both are free:

**Option A: Kiwi.com Tequila API** (recommended — 3000 searches/month free)
1. Register at https://tequila.kiwi.com
2. Create a "solution" and get your API key
3. Set the environment variable:

```powershell
# PowerShell (add to your profile for persistence)
$env:KIWI_API_KEY = "your-api-key-here"
```

```bash
# Bash / Linux / Mac
export KIWI_API_KEY="your-api-key-here"
```

**Option B: Amadeus API** (500 calls/month free)
1. Register at https://developers.amadeus.com
2. Create an app and get your API key + secret
3. Set the environment variables:

```powershell
$env:AMADEUS_API_KEY = "your-api-key"
$env:AMADEUS_API_SECRET = "your-api-secret"
```

### 4. Run a scan

```bash
python deal_finder.py
```

This will:
- Search for flights and all-inclusive packages for both date ranges
- Save results to the SQLite database
- Print a summary to the console
- Open an HTML report in your browser

### 5. Run daily on a schedule

```bash
python deal_finder.py --schedule
```

Runs an immediate scan, then repeats daily at the configured time (default: 08:00). Leave it running in a terminal, or set up Windows Task Scheduler (see below).

### 6. View the latest report

```bash
python deal_finder.py --report
```

## Configuration

Edit `config.json` to customise the search:

```json
{
  "search": {
    "origin": "JNB",
    "destination": "ZNZ",
    "date_ranges": [
      { "label": "Option A: 10-17 Oct", "depart": "2026-10-10", "return": "2026-10-17" },
      { "label": "Option B: 17-24 Oct", "depart": "2026-10-17", "return": "2026-10-24" }
    ],
    "adults": 2,
    "max_budget_per_person": 30000
  }
}
```

### Email Notifications (Optional)

To receive email alerts when prices drop:

1. Edit `config.json` > `notifications`:
   - Set `"enabled": true`
   - Fill in your Gmail address and an [App Password](https://myaccount.google.com/apppasswords)
   - Set `recipient_email` to where you want alerts sent
2. The agent sends an email whenever a price drop exceeding the threshold is detected

## Windows Task Scheduler Setup

To run the agent daily without keeping a terminal open:

1. Open **Task Scheduler** (search in Start menu)
2. Click **Create Basic Task**
3. Name: `Zanzibar Deal Finder`
4. Trigger: **Daily** at your preferred time
5. Action: **Start a program**
   - Program: `python`
   - Arguments: `deal_finder.py --no-browser`
   - Start in: `C:\GIT\ZanzibarPlanner\deal_finder`
6. Finish

If you use API keys, set them as system environment variables (System > Advanced > Environment Variables) so they're available to the scheduled task.

## Data Sources

| Source | Type | How | API Key? |
|---|---|---|---|
| **Kiwi.com Tequila** | Flights | REST API | Yes (free) |
| **Amadeus** | Flights | REST API | Yes (free) |
| **Quintrip** | All-inclusive packages | Playwright scraping | No |
| **AfricaStay** | All-inclusive packages | Playwright scraping | No |
| **Travelstart** | All-inclusive packages | Playwright scraping | No |
| **Resort websites** | Hotel direct | HTTP requests | No |
| **DuckDuckGo** | Everything | Web search | No |

## Project Structure

```
deal_finder/
├── deal_finder.py        # Main entry point & scheduler
├── flight_checker.py     # Flight price search (APIs + web search)
├── package_checker.py    # Package deal search (web + site scraping)
├── price_tracker.py      # SQLite database for price history
├── notifier.py           # HTML reports & email notifications
├── config.json           # Your search configuration
├── requirements.txt      # Python dependencies
└── results/
    ├── deals.db          # Price history database (auto-created)
    └── report_*.html     # Daily HTML reports
```

## Tips

- Run it daily for at least a week to build up price history — that's when price drop detection becomes useful
- The Kiwi API gives the best flight data — it's worth the 2 minutes to register
- The package deals from Quintrip and AfricaStay already include flights from JHB, so they're the most relevant for all-inclusive trips
- Check the HTML reports in `results/` — they're designed to be easy to scan quickly
- Prices labelled "pps" mean "per person sharing"
