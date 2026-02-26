"""
Notification system:
- Generates rich HTML reports saved to results/
- Sends email alerts when price drops are detected
- Prints a clean console summary
"""

import smtplib
import json
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent / "results"


def generate_html_report(deals: list, price_drops: list, stats: dict, config: dict) -> str:
    """Generate a styled HTML report of today's scan results."""
    now = datetime.now().strftime("%A %d %B %Y, %H:%M")
    search = config["search"]

    package_deals = [d for d in deals if d.get("is_all_inclusive")]
    flight_deals = [d for d in deals if d.get("deal_type") == "flight"]
    other_deals = [d for d in deals if not d.get("is_all_inclusive") and d.get("deal_type") != "flight"]

    package_deals.sort(key=lambda x: x.get("price_per_person") or 999999)
    flight_deals.sort(key=lambda x: x.get("price_per_person") or 999999)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: 'Segoe UI', Tahoma, sans-serif; margin: 0; padding: 20px; background: #f0f4f8; color: #2d3748; }}
    .container {{ max-width: 900px; margin: 0 auto; }}
    .header {{ background: linear-gradient(135deg, #0ea5e9, #06b6d4); color: white; padding: 30px;
               border-radius: 12px 12px 0 0; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 28px; }}
    .header p {{ margin: 8px 0 0; opacity: 0.9; }}
    .stats {{ display: flex; gap: 15px; padding: 20px; background: white; border-bottom: 1px solid #e2e8f0; }}
    .stat-box {{ flex: 1; text-align: center; padding: 12px; background: #f8fafc; border-radius: 8px; }}
    .stat-box .number {{ font-size: 24px; font-weight: bold; color: #0ea5e9; }}
    .stat-box .label {{ font-size: 12px; color: #64748b; text-transform: uppercase; }}
    .section {{ background: white; padding: 20px; margin-top: 2px; }}
    .section:last-child {{ border-radius: 0 0 12px 12px; }}
    .section h2 {{ color: #1e293b; border-bottom: 2px solid #0ea5e9; padding-bottom: 8px; font-size: 20px; }}
    .alert {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 16px; margin: 10px 0;
              border-radius: 0 8px 8px 0; }}
    .alert.drop {{ background: #dcfce7; border-left-color: #22c55e; }}
    .deal-card {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 10px 0;
                  transition: box-shadow 0.2s; }}
    .deal-card:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
    .deal-card .price {{ font-size: 22px; font-weight: bold; color: #059669; }}
    .deal-card .provider {{ color: #64748b; font-size: 13px; }}
    .deal-card .title {{ font-weight: 600; margin: 4px 0; }}
    .deal-card .date-range {{ display: inline-block; background: #e0f2fe; color: #0369a1;
                              padding: 2px 10px; border-radius: 12px; font-size: 12px; }}
    .deal-card a {{ color: #0ea5e9; text-decoration: none; }}
    .deal-card a:hover {{ text-decoration: underline; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px;
              font-weight: 600; }}
    .badge.ai {{ background: #dcfce7; color: #166534; }}
    .badge.flight {{ background: #e0f2fe; color: #0369a1; }}
    .no-deals {{ text-align: center; padding: 30px; color: #94a3b8; }}
    .footer {{ text-align: center; padding: 15px; color: #94a3b8; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Zanzibar Deal Finder</h1>
        <p>{search['origin_city']} &rarr; {search['destination_city']} &bull; {now}</p>
        <p style="font-size: 14px;">
            {' &nbsp;|&nbsp; '.join(dr['label'] for dr in search['date_ranges'])}
            &nbsp;|&nbsp; {search['adults']} adults &nbsp;|&nbsp; All-Inclusive
            {f" &nbsp;|&nbsp; {search.get('location_filter', '')}" if search.get('location_filter') else ''}
        </p>
    </div>

    <div class="stats">
        <div class="stat-box">
            <div class="number">{len(deals)}</div>
            <div class="label">Deals Found</div>
        </div>
        <div class="stat-box">
            <div class="number">{len(package_deals)}</div>
            <div class="label">All-Inclusive</div>
        </div>
        <div class="stat-box">
            <div class="number">{len(price_drops)}</div>
            <div class="label">Price Drops</div>
        </div>
        <div class="stat-box">
            <div class="number">{_format_price(stats.get('cheapest_all_inclusive_pps'))}</div>
            <div class="label">Best PPS Ever</div>
        </div>
    </div>
"""

    if price_drops:
        html += '<div class="section"><h2>Price Drops Detected</h2>'
        for drop in price_drops:
            html += f"""
        <div class="alert drop">
            <strong>{drop.get('title', 'Deal')}</strong> dropped
            <strong>{drop.get('drop_percent', '?')}%</strong> &mdash;
            now R{drop.get('current_price', 0):,.0f} pps
            (was R{drop.get('previous_best', 0):,.0f})
            {'&mdash; <a href="' + drop.get('url', '') + '">View</a>' if drop.get('url') else ''}
        </div>"""
        html += "</div>"

    html += _render_deal_section("All-Inclusive Packages", package_deals, "ai")
    html += _render_deal_section("Flights Only", flight_deals, "flight")
    if other_deals:
        html += _render_deal_section("Other Deals", other_deals[:10], "")

    html += f"""
    <div class="footer">
        Zanzibar Deal Finder &bull; Scanned at {now}<br>
        Total deals tracked to date: {stats.get('total_deals_tracked', 'N/A')}
        &bull; Tracking since: {stats.get('tracking_since', 'today')[:10] if stats.get('tracking_since') else 'today'}
    </div>
</div>
</body>
</html>"""

    return html


def _render_deal_section(title: str, deals: list, badge_type: str) -> str:
    if not deals:
        return f"""
    <div class="section">
        <h2>{title}</h2>
        <div class="no-deals">No deals found in this category yet. Check back tomorrow!</div>
    </div>"""

    html = f'<div class="section"><h2>{title}</h2>'
    for deal in deals[:15]:
        price_display = _format_price(deal.get("price_per_person"))
        total_display = _format_price(deal.get("price_zar"))
        badge = ""
        if badge_type == "ai":
            badge = '<span class="badge ai">ALL-INCLUSIVE</span>'
        elif badge_type == "flight":
            badge = '<span class="badge flight">FLIGHT</span>'

        url = deal.get("url", "")
        provider = deal.get("provider", "Unknown")
        snippet = deal.get("details", {}).get("snippet", "")[:150]

        html += f"""
        <div class="deal-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span class="date-range">{deal.get('date_range', '')}</span> {badge}
                    <div class="title">{deal.get('title', 'Deal')[:120]}</div>
                    <div class="provider">{provider}</div>
                    {f'<div style="color: #64748b; font-size: 13px; margin-top: 4px;">{snippet}</div>' if snippet else ''}
                </div>
                <div style="text-align: right;">
                    <div class="price">{price_display} <span style="font-size:13px;font-weight:normal;">pps</span></div>
                    <div style="font-size: 12px; color: #94a3b8;">{total_display} total</div>
                    {f'<a href="{url}" target="_blank">View deal &rarr;</a>' if url else ''}
                </div>
            </div>
        </div>"""
    html += "</div>"
    return html


def _format_price(price) -> str:
    if price is None:
        return "N/A"
    return f"R{price:,.0f}"


def save_report(html: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = RESULTS_DIR / f"report_{date_str}.html"
    filepath.write_text(html, encoding="utf-8")
    logger.info(f"Report saved to {filepath}")
    return filepath


def send_email(config: dict, subject: str, html_body: str):
    """Send an email notification with the HTML report."""
    import os

    email_cfg = config.get("notifications", {}).get("email", {})
    if not email_cfg.get("sender_email") or not email_cfg.get("recipient_email"):
        logger.info("Email not configured - skipping notification")
        return

    # Load SMTP password from .env (falls back to config for backwards compat)
    _load_env_file()
    smtp_password = os.environ.get("SMTP_PASSWORD", email_cfg.get("sender_password", ""))
    if not smtp_password:
        logger.error("No SMTP password found. Set SMTP_PASSWORD in .env file.")
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = email_cfg["sender_email"]
        msg["To"] = email_cfg["recipient_email"]
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"]) as server:
            server.starttls()
            server.login(email_cfg["sender_email"], smtp_password)
            server.sendmail(email_cfg["sender_email"], email_cfg["recipient_email"], msg.as_string())

        logger.info(f"Email sent to {email_cfg['recipient_email']}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


def _load_env_file():
    """Load .env file variables into os.environ."""
    import os
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def print_console_summary(deals: list, price_drops: list, stats: dict):
    """Print a clean summary to the console."""
    print("\n" + "=" * 70)
    print("  ZANZIBAR DEAL FINDER - Daily Report")
    print(f"  {datetime.now().strftime('%A %d %B %Y, %H:%M')}")
    print("=" * 70)

    package_deals = sorted(
        [d for d in deals if d.get("is_all_inclusive") and d.get("price_per_person")],
        key=lambda x: x["price_per_person"]
    )
    flight_deals = sorted(
        [d for d in deals if d.get("deal_type") == "flight" and d.get("price_per_person")],
        key=lambda x: x["price_per_person"]
    )

    if price_drops:
        print(f"\n  PRICE DROPS DETECTED ({len(price_drops)}):")
        for drop in price_drops:
            print(f"    {drop.get('title', 'Deal')[:60]}")
            print(f"      Was R{drop.get('previous_best', 0):,.0f} -> Now R{drop.get('current_price', 0):,.0f}"
                  f" ({drop.get('drop_percent', '?')}% off)")

    print(f"\n  BEST ALL-INCLUSIVE PACKAGES (top 5):")
    if package_deals:
        for i, d in enumerate(package_deals[:5], 1):
            print(f"    {i}. R{d['price_per_person']:,.0f} pps - {d.get('title', 'Deal')[:55]}")
            print(f"       {d.get('date_range', '')} | {d.get('provider', '')}")
            if d.get("url"):
                print(f"       {d['url'][:80]}")
    else:
        print("    No all-inclusive deals found yet.")

    print(f"\n  CHEAPEST FLIGHTS (top 5):")
    if flight_deals:
        for i, d in enumerate(flight_deals[:5], 1):
            print(f"    {i}. R{d['price_per_person']:,.0f} pps - {d.get('provider', 'Unknown')}")
            if d.get("url"):
                print(f"       {d['url'][:80]}")
    else:
        print("    No flight prices found yet.")

    print(f"\n  STATS:")
    print(f"    Total deals tracked: {stats.get('total_deals_tracked', 0)}")
    cheapest = stats.get("cheapest_all_inclusive_pps")
    if cheapest:
        print(f"    Best all-inclusive ever: R{cheapest:,.0f} pps")

    print("\n" + "=" * 70 + "\n")
