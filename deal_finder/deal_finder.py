"""
Zanzibar Deal Finder Agent
==========================
Scours the internet daily for the best all-inclusive holiday deals
from Johannesburg to Zanzibar.

Usage:
    python deal_finder.py              # Run a single scan now
    python deal_finder.py --schedule   # Run daily on a schedule
    python deal_finder.py --report     # Show latest report only
"""

import argparse
import json
import logging
import os
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import schedule as schedule_lib

from flight_checker import search_all_flights
from package_checker import search_all_packages
from price_tracker import save_deals, get_best_deals, detect_price_drops, get_summary_stats
from notifier import (
    generate_html_report,
    save_report,
    send_email,
    print_console_summary,
)

CONFIG_PATH = Path(__file__).parent / "config.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def run_scan(config: dict = None, open_report: bool = True):
    """Execute a full scan across all sources and date ranges."""
    if config is None:
        config = load_config()

    search = config["search"]
    date_ranges = search["date_ranges"]

    print("\n" + "=" * 70)
    print("  ZANZIBAR DEAL FINDER - Starting scan...")
    print(f"  {datetime.now().strftime('%A %d %B %Y, %H:%M')}")
    print(f"  Route: {search['origin_city']} -> {search['destination_city']}")
    print(f"  Dates: {' | '.join(dr['label'] for dr in date_ranges)}")
    loc_filter = search.get("location_filter", "")
    print(f"  Looking for: All-Inclusive, {search['adults']} adults")
    if loc_filter:
        print(f"  Location: {loc_filter}")
    print("=" * 70 + "\n")

    all_deals = []

    for date_range in date_ranges:
        logger.info(f"--- Scanning {date_range['label']} ---")

        flight_deals = search_all_flights(config, date_range)
        all_deals.extend(flight_deals)

        package_deals = search_all_packages(config, date_range)
        all_deals.extend(package_deals)

        logger.info(
            f"  {date_range['label']}: {len(flight_deals)} flight results, "
            f"{len(package_deals)} package results"
        )

    priced_deals = [d for d in all_deals if d.get("price_per_person")]
    logger.info(f"\nTotal: {len(all_deals)} results ({len(priced_deals)} with prices)")

    if priced_deals:
        save_deals(priced_deals)
        logger.info("Saved to price tracker database")

    threshold = config.get("notifications", {}).get("price_drop_threshold_percent", 5)
    price_drops = detect_price_drops(threshold)
    stats = get_summary_stats()

    html = generate_html_report(all_deals, price_drops, stats, config)
    report_path = save_report(html)

    print_console_summary(all_deals, price_drops, stats)

    if open_report:
        try:
            webbrowser.open(report_path.as_uri())
        except Exception:
            print(f"  Report saved to: {report_path}")

    if config.get("notifications", {}).get("enabled") and price_drops:
        subject = f"Zanzibar Deal Alert - {len(price_drops)} price drop(s) found!"
        send_email(config, subject, html)
    elif config.get("notifications", {}).get("enabled"):
        today = datetime.now().strftime("%d %b")
        subject = f"Zanzibar Deal Report - {today} - {len(priced_deals)} deals found"
        send_email(config, subject, html)

    return all_deals


def show_latest_report():
    """Open the most recent HTML report in the browser."""
    results_dir = Path(__file__).parent / "results"
    reports = sorted(results_dir.glob("report_*.html"), reverse=True)
    if reports:
        print(f"Opening: {reports[0]}")
        webbrowser.open(reports[0].as_uri())
    else:
        print("No reports found yet. Run a scan first: python deal_finder.py")


def run_scheduled(config: dict):
    """Run the agent on a daily schedule."""
    run_time = config.get("schedule", {}).get("run_daily_at", "08:00")

    logger.info(f"Deal Finder scheduled to run daily at {run_time}")
    logger.info("Press Ctrl+C to stop.\n")

    logger.info("Running initial scan now...")
    run_scan(config, open_report=True)

    schedule_lib.every().day.at(run_time).do(run_scan, config=config, open_report=False)

    while True:
        schedule_lib.run_pending()
        next_run = schedule_lib.next_run()
        if next_run:
            delta = next_run - datetime.now()
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes = remainder // 60
            sys.stdout.write(f"\r  Next scan in {hours}h {minutes}m — Press Ctrl+C to stop  ")
            sys.stdout.flush()
        time.sleep(60)


def main():
    parser = argparse.ArgumentParser(
        description="Zanzibar Deal Finder — Scours the internet for the best holiday deals"
    )
    parser.add_argument(
        "--schedule", action="store_true",
        help="Run daily on a schedule (default: 08:00)"
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Open the latest report without scanning"
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Don't open the report in the browser"
    )
    args = parser.parse_args()

    config = load_config()

    if args.report:
        show_latest_report()
    elif args.schedule:
        run_scheduled(config)
    else:
        run_scan(config, open_report=not args.no_browser)


if __name__ == "__main__":
    main()
