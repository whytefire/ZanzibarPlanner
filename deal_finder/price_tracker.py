"""
SQLite-based price tracker that stores historical deal data
and detects price drops over time.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "results" / "deals.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            found_at TEXT NOT NULL,
            source TEXT NOT NULL,
            deal_type TEXT NOT NULL,       -- 'flight', 'package', 'hotel'
            date_range TEXT NOT NULL,       -- 'Option A: 10-17 Oct' etc.
            provider TEXT,
            title TEXT NOT NULL,
            price_zar REAL,
            price_per_person REAL,
            url TEXT,
            details TEXT,                  -- JSON blob for extra info
            is_all_inclusive INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_fingerprint TEXT NOT NULL, -- hash of source+title+date_range
            recorded_at TEXT NOT NULL,
            price_zar REAL,
            price_per_person REAL
        );

        CREATE INDEX IF NOT EXISTS idx_deals_found ON deals(found_at);
        CREATE INDEX IF NOT EXISTS idx_deals_source ON deals(source);
        CREATE INDEX IF NOT EXISTS idx_history_fp ON price_history(deal_fingerprint);
    """)
    conn.commit()
    conn.close()


def _fingerprint(source: str, title: str, date_range: str) -> str:
    import hashlib
    raw = f"{source}|{title}|{date_range}".lower().strip()
    return hashlib.md5(raw.encode()).hexdigest()


def save_deal(deal: dict):
    conn = get_connection()
    now = datetime.now().isoformat()
    fp = _fingerprint(deal["source"], deal["title"], deal["date_range"])

    conn.execute("""
        INSERT INTO deals (found_at, source, deal_type, date_range, provider,
                          title, price_zar, price_per_person, url, details, is_all_inclusive)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now,
        deal.get("source", "unknown"),
        deal.get("deal_type", "package"),
        deal.get("date_range", ""),
        deal.get("provider", ""),
        deal.get("title", ""),
        deal.get("price_zar"),
        deal.get("price_per_person"),
        deal.get("url", ""),
        json.dumps(deal.get("details", {})),
        1 if deal.get("is_all_inclusive") else 0,
    ))

    conn.execute("""
        INSERT INTO price_history (deal_fingerprint, recorded_at, price_zar, price_per_person)
        VALUES (?, ?, ?, ?)
    """, (fp, now, deal.get("price_zar"), deal.get("price_per_person")))

    conn.commit()
    conn.close()


def save_deals(deals: list):
    for deal in deals:
        save_deal(deal)


def get_price_history(source: str, title: str, date_range: str) -> list:
    conn = get_connection()
    fp = _fingerprint(source, title, date_range)
    rows = conn.execute("""
        SELECT recorded_at, price_zar, price_per_person
        FROM price_history
        WHERE deal_fingerprint = ?
        ORDER BY recorded_at
    """, (fp,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_deals(limit: int = 50) -> list:
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM deals
        ORDER BY found_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_best_deals(date_range: str = None, deal_type: str = None, limit: int = 10) -> list:
    conn = get_connection()
    query = """
        SELECT *, MIN(price_per_person) as best_price
        FROM deals
        WHERE price_per_person IS NOT NULL
    """
    params = []
    if date_range:
        query += " AND date_range = ?"
        params.append(date_range)
    if deal_type:
        query += " AND deal_type = ?"
        params.append(deal_type)
    query += " GROUP BY source, title, date_range ORDER BY best_price LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def detect_price_drops(threshold_percent: float = 5.0) -> list:
    """Find deals where today's price is lower than the previous best."""
    conn = get_connection()
    today = datetime.now().date().isoformat()

    previous_bests = conn.execute("""
        SELECT deal_fingerprint, MIN(price_per_person) as prev_best
        FROM price_history
        WHERE date(recorded_at) < ?
          AND price_per_person IS NOT NULL
        GROUP BY deal_fingerprint
    """, (today,)).fetchall()

    drops = []
    for pb in previous_bests:
        pb = dict(pb)
        fp = pb["deal_fingerprint"]
        prev_best = pb["prev_best"]
        if not prev_best:
            continue

        current = conn.execute("""
            SELECT price_per_person FROM price_history
            WHERE deal_fingerprint = ? AND date(recorded_at) = ?
              AND price_per_person IS NOT NULL
            ORDER BY recorded_at DESC LIMIT 1
        """, (fp, today)).fetchone()

        if not current:
            continue
        current_price = current["price_per_person"]
        if current_price >= prev_best:
            continue

        pct = ((prev_best - current_price) / prev_best) * 100
        if pct < threshold_percent:
            continue

        deal_info = conn.execute("""
            SELECT title, source, date_range, url FROM deals
            WHERE source || '|' || title || '|' || date_range IN (
                SELECT source || '|' || title || '|' || date_range FROM deals
            )
            ORDER BY found_at DESC LIMIT 1
        """).fetchone()

        deal_row = conn.execute("""
            SELECT title, source, date_range, url FROM deals
            ORDER BY found_at DESC LIMIT 1
        """).fetchone()

        drops.append({
            "deal_fingerprint": fp,
            "current_price": current_price,
            "previous_best": prev_best,
            "drop_percent": round(pct, 1),
            "title": dict(deal_row).get("title", "Unknown") if deal_row else "Unknown",
            "source": dict(deal_row).get("source", "") if deal_row else "",
            "date_range": dict(deal_row).get("date_range", "") if deal_row else "",
            "url": dict(deal_row).get("url", "") if deal_row else "",
        })

    conn.close()
    return drops


def get_summary_stats() -> dict:
    conn = get_connection()
    stats = {}

    row = conn.execute("SELECT COUNT(*) as cnt, MIN(found_at) as first, MAX(found_at) as last FROM deals").fetchone()
    stats["total_deals_tracked"] = row["cnt"]
    stats["tracking_since"] = row["first"]
    stats["last_scan"] = row["last"]

    row = conn.execute("""
        SELECT MIN(price_per_person) as cheapest, AVG(price_per_person) as avg_price
        FROM deals WHERE price_per_person IS NOT NULL AND is_all_inclusive = 1
    """).fetchone()
    stats["cheapest_all_inclusive_pps"] = row["cheapest"]
    stats["avg_all_inclusive_pps"] = round(row["avg_price"], 2) if row["avg_price"] else None

    conn.close()
    return stats


init_db()
