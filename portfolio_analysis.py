import os
import re
import csv
import io
import json
import sqlite3
import hashlib
import datetime
import smtplib
import requests
import feedparser
from collections import deque
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── CONFIG ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]

# API pricing per million tokens
_MODEL_PRICES = {
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output":  4.00},
}
GMAIL_USER         = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL    = os.environ["RECIPIENT_EMAIL"]
DASHBOARD_URL      = os.environ.get("DASHBOARD_URL", "")

# Newsletters arrive on iCloud Mail (not Gmail). Optional — a missing credential
# degrades gracefully: the report still sends, just without the newsletter block.
ICLOUD_EMAIL        = os.environ.get("ICLOUD_EMAIL", "")
ICLOUD_APP_PASSWORD = os.environ.get("ICLOUD_APP_PASSWORD", "")

TODAY     = datetime.date.today()
TODAY_STR = TODAY.strftime("%Y-%m-%d")
DB_PATH   = os.path.join(os.path.dirname(__file__), "seen_articles.db")

SHEET_ID   = "1qbb0x_kNtIUp4cq-_O9uFi6stbcSPwTeTnXOd1DbzOo"
SHEET_GIDS = {
    "Summary":    "1633571629",
    "Utilities":  "2066207814",
}

# Clean per-portfolio transaction tabs feeding the FIFO tax table. Each is a flat
# ledger with headers on row 1: Date | Ticker | Price | Transaction | Shares | Amount.
# Keyed by tab name -> gid; all tabs are unioned. The gid is in the tab's URL
# (the #gid=... at the end). Add a line here as you create each tab.
TX_SHEETS = {
    "TXs_USD": "1053431702",       # Stocks Portfolio (XTB, USD)
    "TXs_ETF": "1595916700",       # ETF Portfolio (XTB, EUR)
    # "TXs_RON": "PASTE_GID_HERE", # TradeVille (RON)          — add once created
}

# Column resolution — case-insensitive substring match on the sheet headers.
# Add/edit hints if your headers differ.
SUMMARY_COL_HINTS = {
    "ticker": ["symbol", "ticker"],
    "shares": ["shares", "qty", "quantity", "units"],
}
TRANZACTII_COL_HINTS = {
    "date":   ["date", "data"],
    "ticker": ["symbol", "ticker", "instrument"],
    "action": ["action", "type", "side", "operation"],
    "shares": ["shares", "qty", "quantity", "units", "amount"],
}

# Macro/topic keywords — filter the general financial news bucket AND act as the
# relevance themes for the newsletter distill pass (see distill_newsletters).
MACRO_KEYWORDS = [
    "Fed", "FOMC", "ECB", "BNR", "inflation", "interest rate",
    "recession", "Romania", "RON", "EUR/USD", "EUR",
    "S&P 500", "STOXX", "REIT", "bond yield", "Treasury",
    "Bitcoin", "BTC", "crypto", "cryptocurrency", "Ethereum", "ETH",
    "AI", "artificial intelligence", "IPO",
    "Trump", "Musk",
]

MAX_ITEMS_TOTAL = 30
MAX_PER_FEED    = 3

# ── NEWSLETTERS (iCloud) ────────────────────────────────────────────────────────
# Subscribed newsletters land on iCloud Mail. They're pulled by sender, deduped
# against the seen_articles cache, then Haiku-distilled into a compact, portfolio-
# relevant digest before the Sonnet analysis ever sees them (keeps the run in budget).
# Each source: a sender to match, plus an optional `subject` substring (server-side
# IMAP SUBJECT match) to narrow which of that sender's mails to pull. NYT sends ~3
# dailies/day from one address; only DealBook is finance-relevant, so we filter on it.
NEWSLETTER_SOURCES       = [
    {"from": "nytdirect@nytimes.com", "subject": "DealBook"},
]
# Folders to scan. A mail rule files newsletters into "Newsletters", but the rule may
# not have run yet (client-side rules only fire when the Mail app is open), so scan
# INBOX too. Message-ID dedup makes the overlap harmless. Missing folders are skipped.
NEWSLETTER_FOLDERS       = ["INBOX", "Newsletters"]
NEWSLETTER_LOOKBACK_DAYS = 7
NEWSLETTER_BODY_CAP      = 6000   # chars of body text kept per newsletter before distilling
NEWSLETTER_MAX           = 12     # cap on newsletters pulled per run (safety on cost)
ICLOUD_HOST = "imap.mail.me.com"
ICLOUD_PORT = 993

# ── RSS FEEDS ─────────────────────────────────────────────────────────────────
# Only live, verified feeds. Per-ticker feeds are built at runtime from holdings
RSS_FEEDS_STATIC = {
    "General Financial News": [
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
        ("CNBC",        "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("NYT Business",    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
        ("NYT Economy",     "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"),
        ("NYT Technology",  "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"),
        ("NYT US",          "https://rss.nytimes.com/services/xml/rss/nyt/US.xml"),
        ("NYT World",       "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ],
    "Crypto": [
        ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ("Decrypt",  "https://decrypt.co/feed"),
    ],
    "Romania": [
        ("Profit.ro", "https://www.profit.ro/rss"),
        ("GNews-RO",  "https://news.google.com/rss/search?q=Romania+economy&hl=en-US&gl=US&ceid=US:en"),
    ],
}

FEED_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioBot/1.0)"}

# ── SQLITE CACHE ──────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_articles (
            url     TEXT PRIMARY KEY,
            seen_on TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    # Per-ticker recommendation ledger — one row per stock per weekly run. Gives the
    # analysis a memory of its own prior calls so stances don't whipsaw on noise.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            week_date    TEXT NOT NULL,
            ticker       TEXT NOT NULL,
            stance       TEXT NOT NULL,
            conviction   TEXT,
            thesis       TEXT,
            catalyst     TEXT,
            stance_since TEXT,
            price        REAL,
            pnl_pct      REAL,
            PRIMARY KEY (week_date, ticker)
        )
    """)
    conn.execute(
        "DELETE FROM seen_articles WHERE seen_on < ?",
        (str(TODAY - datetime.timedelta(days=14)),)
    )
    conn.commit()
    return conn

def is_seen(conn, url):
    return conn.execute("SELECT 1 FROM seen_articles WHERE url = ?", (url,)).fetchone() is not None

def mark_seen(conn, url):
    conn.execute("INSERT OR IGNORE INTO seen_articles (url, seen_on) VALUES (?, ?)", (url, TODAY_STR))
    conn.commit()

def get_state(conn, key):
    row = conn.execute("SELECT value FROM portfolio_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None

def set_state(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO portfolio_state (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

# ── RECOMMENDATION MEMORY ─────────────────────────────────────────────────────
# Machine-readable markers Sonnet wraps its per-ticker call ledger in. The block
# is parsed out and persisted, then stripped before the analysis reaches Haiku.
REC_START = "===RECOMMENDATIONS_JSON==="
REC_END   = "===END_RECOMMENDATIONS_JSON==="

# One-time baseline so the consistency guard has prior calls to anchor on from the
# very first run instead of starting blank. Self-expires (see BASELINE_MAX_AGE_DAYS)
# so a cache wipe weeks later can't resurrect stale stances.
BASELINE_PATH         = os.path.join(os.path.dirname(__file__), "baseline_recommendations.json")
BASELINE_MAX_AGE_DAYS = 21

def _to_float(v):
    """Coerce values like 148.76, '$148.76', '-4.9%' to float; None on failure."""
    if v is None:
        return None
    try:
        return float(str(v).replace("$", "").replace("%", "").replace(",", "").strip())
    except ValueError:
        return None

def seed_baseline_if_empty(conn):
    """Bootstrap the ledger from baseline_recommendations.json when it has no rows
    yet, so the consistency guard works from the first run. No-op once any real run
    has written rows. Self-expires after BASELINE_MAX_AGE_DAYS so a late cache wipe
    can't reintroduce stale stances."""
    if conn.execute("SELECT 1 FROM recommendations LIMIT 1").fetchone():
        return 0
    if not os.path.exists(BASELINE_PATH):
        return 0
    try:
        with open(BASELINE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[{TODAY_STR}] Warning: could not read baseline file: {e}")
        return 0
    week_date = (data.get("week_date") or "").strip()
    recs      = data.get("recommendations", [])
    if not week_date or not recs:
        return 0
    try:
        age = (TODAY - datetime.date.fromisoformat(week_date)).days
    except ValueError:
        return 0
    if not 0 <= age <= BASELINE_MAX_AGE_DAYS:
        print(f"[{TODAY_STR}] Baseline {week_date} is {age}d old — outside seed window, skipping")
        return 0
    seeded = 0
    for rec in recs:
        ticker = (rec.get("ticker") or "").strip().upper()
        stance = (rec.get("stance") or "").strip().upper()
        if not ticker or not stance:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO recommendations "
            "(week_date, ticker, stance, conviction, thesis, catalyst, stance_since, price, pnl_pct) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (week_date, ticker, stance,
             (rec.get("conviction") or "").strip(),
             (rec.get("thesis") or "").strip(),
             (rec.get("catalyst") or "").strip(),
             (rec.get("stance_since") or week_date).strip(),
             _to_float(rec.get("price")), _to_float(rec.get("pnl_pct"))),
        )
        seeded += 1
    conn.commit()
    print(f"[{TODAY_STR}] Seeded {seeded} baseline recommendations from {week_date}")
    return seeded

def get_prior_recommendations(conn):
    """Return (prior_week_date, rows) from the most recent run BEFORE today.
    Using '< today' keeps same-day reruns (e.g. manual dispatch) idempotent."""
    row = conn.execute(
        "SELECT MAX(week_date) FROM recommendations WHERE week_date < ?", (TODAY_STR,)
    ).fetchone()
    prior_week = row[0] if row else None
    if not prior_week:
        return None, []
    cur = conn.execute(
        "SELECT ticker, stance, conviction, thesis, catalyst, stance_since, price, pnl_pct "
        "FROM recommendations WHERE week_date = ? ORDER BY ticker", (prior_week,)
    )
    cols = [d[0] for d in cur.description]
    return prior_week, [dict(zip(cols, r)) for r in cur.fetchall()]

def save_recommendations(conn, recs):
    """Upsert this week's calls. Carry stance_since forward when the stance is
    unchanged vs the most recent prior week, so we can tell a long-held conviction
    from a fresh one."""
    _, prior_rows = get_prior_recommendations(conn)
    prior_by_ticker = {r["ticker"]: r for r in prior_rows}
    saved = 0
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        ticker = (rec.get("ticker") or "").strip().upper()
        stance = (rec.get("stance") or "").strip().upper()
        if not ticker or not stance:
            continue
        prev = prior_by_ticker.get(ticker)
        if prev and (prev.get("stance") or "").upper() == stance and prev.get("stance_since"):
            stance_since = prev["stance_since"]
        else:
            stance_since = TODAY_STR
        conn.execute(
            "INSERT OR REPLACE INTO recommendations "
            "(week_date, ticker, stance, conviction, thesis, catalyst, stance_since, price, pnl_pct) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (TODAY_STR, ticker, stance,
             (rec.get("conviction") or "").strip(),
             (rec.get("thesis") or "").strip(),
             (rec.get("catalyst") or "").strip(),
             stance_since, _to_float(rec.get("price")), _to_float(rec.get("pnl_pct"))),
        )
        saved += 1
    conn.commit()
    return saved

def format_prior_recommendations(prior_week, rows):
    """Render prior calls as a compact prompt block."""
    if not rows:
        return ("(No prior recommendations on record — this is the first tracked run. "
                "Establish a baseline stance per stock.)")
    lines = [f"(from last tracked run {prior_week} — these were YOUR calls)"]
    for r in rows:
        parts = [f"{r['ticker']}: {r['stance']}"]
        if r.get("conviction"):
            parts.append(f"conviction {r['conviction']}")
        if r.get("stance_since"):
            parts.append(f"since {r['stance_since']}")
        if r.get("thesis"):
            parts.append(f"thesis: {r['thesis']}")
        if r.get("catalyst"):
            parts.append(f"catalyst: {r['catalyst']}")
        if r.get("pnl_pct") is not None:
            parts.append(f"P&L then {r['pnl_pct']:+.1f}%")
        lines.append("  - " + " | ".join(parts))
    return "\n".join(lines)

def extract_recommendations(text):
    """Split the machine-readable ledger out of Sonnet's analysis.
    Returns (clean_text_without_block, list_of_dicts). Degrades to (text, [])."""
    start = text.find(REC_START)
    if start == -1:
        return text, []
    # The report text is everything before the marker; the ledger (and anything the
    # model stray-appended after it) lives from the marker onward and is discarded.
    clean = text[:start].rstrip()
    end = text.find(REC_END, start)
    raw = text[start + len(REC_START): end if end != -1 else len(text)]
    raw = raw.strip().strip("`").strip()
    if raw.lower().startswith("json"):       # tolerate a ```json language hint
        raw = raw[4:].strip()
    try:
        recs = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"[{TODAY_STR}] Warning: could not parse recommendations JSON: {e}")
        return clean, []
    if isinstance(recs, dict):
        recs = recs.get("recommendations", [])
    return clean, recs if isinstance(recs, list) else []

# ── HELPERS ───────────────────────────────────────────────────────────────────
def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()

def md5(text):
    return hashlib.md5(text.encode()).hexdigest()

def claude_call(model, system, user, max_tokens, temperature=None):
    """Returns (text, cost_usd)."""
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if temperature is not None:
        payload["temperature"] = temperature
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=300,
    )
    if response.status_code != 200:
        raise RuntimeError(f"API error {response.status_code}: {response.text}")
    data  = response.json()
    usage = data.get("usage", {})
    inp   = usage.get("input_tokens", 0)
    out   = usage.get("output_tokens", 0)
    prices = _MODEL_PRICES.get(model, {"input": 0, "output": 0})
    cost   = (inp * prices["input"] + out * prices["output"]) / 1_000_000
    print(f"  [{model}] input: {inp}, output: {out}, cost: ${cost:.4f}")
    text = "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")
    return text, cost

# ── CSV PARSING ───────────────────────────────────────────────────────────────
def parse_csv(text):
    """Return (headers, rows). rows are dicts keyed by header."""
    if not text or text.startswith("["):
        return [], []
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    headers = [h.strip() for h in rows[0]]
    out = [dict(zip(headers, r)) for r in rows[1:] if any(c.strip() for c in r)]
    return headers, out

def find_col(headers, hints):
    """Case-insensitive substring match. Returns the actual header name or None."""
    lower = {h.lower(): h for h in headers}
    for hint in hints:
        for k, original in lower.items():
            if hint.lower() in k:
                return original
    return None

def resolve_columns(headers, hint_map):
    return {key: find_col(headers, hints) for key, hints in hint_map.items()}

# ── DATE PARSING ──────────────────────────────────────────────────────────────
def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    # Transaction tabs use US M/D/Y, so try month-first before day-first.
    # (ISO stays first for the History sheet; day-first remains a fallback.)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

# ── SYMBOL EXTRACTION ─────────────────────────────────────────────────────────
def extract_symbols(summary_rows, cols):
    if not cols.get("ticker"):
        return []
    seen, out = set(), []
    for row in summary_rows:
        sym = (row.get(cols["ticker"]) or "").strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out

# ── TAX TABLE (FIFO over Tranzactii) ──────────────────────────────────────────
BUY_ACTIONS  = {"BUY", "B", "CUMPARARE", "CUMPĂRARE", "ACHIZITIE", "ACHIZIȚIE"}
SELL_ACTIONS = {"SELL", "S", "VANZARE", "VÂNZARE"}

def build_tax_table(tranzactii_rows, cols, today):
    """FIFO match buys against sells per ticker. Returns per-ticker dict with
    long_shares (held >365d, 3% tax), short_shares (≤365d, 6%), earliest open
    buy date, and the soonest number of days until another lot rolls into 3%.
    Returns None if required columns aren't resolved."""
    if not all(cols.get(k) for k in ("date", "ticker", "action", "shares")):
        return None

    parsed = []
    for row in tranzactii_rows:
        d = parse_date(row.get(cols["date"]))
        if not d:
            continue
        action = (row.get(cols["action"]) or "").strip().upper()
        ticker = (row.get(cols["ticker"]) or "").strip().upper()
        raw    = (row.get(cols["shares"]) or "0").replace(",", ".").strip()
        try:
            shares = float(raw)
        except ValueError:
            continue
        if not ticker or shares <= 0:
            continue
        parsed.append((d, ticker, action, shares))
    parsed.sort(key=lambda x: x[0])

    lots = {}  # ticker -> deque of [buy_date, remaining_shares]
    for d, ticker, action, shares in parsed:
        q = lots.setdefault(ticker, deque())
        if action in BUY_ACTIONS:
            q.append([d, shares])
        elif action in SELL_ACTIONS:
            remaining = shares
            while remaining > 1e-9 and q:
                front = q[0]
                if front[1] <= remaining + 1e-9:
                    remaining -= front[1]
                    q.popleft()
                else:
                    front[1] -= remaining
                    remaining = 0

    result = {}
    for ticker, q in lots.items():
        if not q:
            continue
        long_shares = short_shares = 0.0
        earliest = None
        days_to_long = None
        for buy_date, n in q:
            age = (today - buy_date).days
            if age > 365:
                long_shares += n
            else:
                short_shares += n
                d2l = 366 - age
                if days_to_long is None or d2l < days_to_long:
                    days_to_long = d2l
            if earliest is None or buy_date < earliest:
                earliest = buy_date
        result[ticker] = {
            "long_shares":  long_shares,
            "short_shares": short_shares,
            "earliest_buy": earliest,
            "days_to_long": days_to_long,
        }
    return result

def _fmt_shares(n):
    s = f"{n:.4f}".rstrip("0").rstrip(".")
    return s or "0"

def format_tax_table(tax_data):
    if tax_data is None:
        return "[Tax table unavailable — Tranzactii sheet not configured]"
    if not tax_data:
        return "[No open positions]"
    lines = ["Ticker | Long (3%) | Short (6%) | Earliest buy | Days→next 3% lot"]
    lines.append("-" * 70)
    for ticker, d in sorted(tax_data.items()):
        earliest = d["earliest_buy"].isoformat() if d["earliest_buy"] else "-"
        d2l      = str(d["days_to_long"]) if d["days_to_long"] is not None else "-"
        lines.append(
            f"{ticker} | {_fmt_shares(d['long_shares'])} | "
            f"{_fmt_shares(d['short_shares'])} | {earliest} | {d2l}"
        )
    return "\n".join(lines)

# ── RSS FETCHER ───────────────────────────────────────────────────────────────
def is_macro_relevant(title):
    upper = title.upper()
    return any(kw.upper() in upper for kw in MACRO_KEYWORDS)

def fetch_feed(label, url, conn, filter_macro=False):
    try:
        feed = feedparser.parse(url, request_headers=FEED_HEADERS)
        results = []
        for entry in feed.entries[:20]:
            title = strip_html(entry.get("title", ""))
            link  = entry.get("link", entry.get("id", ""))
            if not title:
                continue
            if is_seen(conn, link or title):
                continue
            if filter_macro and not is_macro_relevant(title):
                continue
            mark_seen(conn, link or title)
            results.append({"label": label, "title": title})
            if len(results) >= MAX_PER_FEED:
                break
        print(f"  [{label}] {len(results)} new items")
        return results
    except Exception as e:
        print(f"  Warning: [{label}] {e}")
        return []

def build_ticker_feeds(symbols):
    """One Yahoo Finance feed per actively held ticker."""
    return [(sym, f"https://finance.yahoo.com/rss/headline?s={sym}") for sym in symbols]

def fetch_all_news(symbols):
    conn = init_db()
    feeds = dict(RSS_FEEDS_STATIC)
    if symbols:
        feeds["Individual Stocks"] = build_ticker_feeds(symbols)

    sections, total = {}, 0
    for category, feed_list in feeds.items():
        filter_macro = category == "General Financial News"
        items = []
        for label, url in feed_list:
            items.extend(fetch_feed(label, url, conn, filter_macro=filter_macro))
        sections[category] = items
        total += len(items)
    conn.close()

    if total > MAX_ITEMS_TOTAL:
        ratio = MAX_ITEMS_TOTAL / total
        for cat in sections:
            sections[cat] = sections[cat][:max(1, int(len(sections[cat]) * ratio))]
        total = sum(len(v) for v in sections.values())

    print(f"[{TODAY_STR}] Total news items: {total}")
    lines = [f"# News Digest — {TODAY_STR} ({total} items)\n"]
    for category, items in sections.items():
        if not items:
            continue
        lines.append(f"\n## {category}")
        for item in items:
            lines.append(f"[{item['label']}] {item['title']}")
    return "\n".join(lines)

# ── NEWSLETTERS (iCloud IMAP → Haiku distill) ──────────────────────────────────
def distill_newsletters(items, symbols):
    """Haiku pass: collapse raw newsletters into portfolio-relevant bullets.

    Sonnet only ever sees these distilled bullets, never the raw HTML — that's what
    keeps the run inside the cost budget. Returns (digest_text, cost_usd).
    """
    tickers = ", ".join(symbols) if symbols else "(none held)"
    themes  = ", ".join(MACRO_KEYWORDS)
    blocks  = [
        f'<<< {it["source"]} — "{it["subject"]}" — {it["date"]} >>>\n{it["body"]}'
        for it in items
    ]
    newsletters_text = "\n\n".join(blocks)

    system = (
        "You distill financial newsletters into portfolio-relevant bullet points. "
        "Keep ONLY points that bear on the given holdings or macro themes. Drop everything "
        "else (ads, subscription prompts, unrelated stories). Be factual, no hype, numbers "
        "over prose. Output plain text only — no HTML, no markdown beyond the format shown."
    )
    user = f"""Held tickers: {tickers}
Macro themes: {themes}

For each newsletter below, extract up to 5 bullets relevant to the holdings/themes above.
Tag each bullet with the ticker or theme it bears on. If a newsletter has nothing relevant,
write "(nothing relevant)". Use exactly this format:

## <source name>
- [<TICKER or THEME>] <one-line fact or claim>

### Newsletters
{newsletters_text}"""

    text, cost = claude_call(
        model       = "claude-haiku-4-5-20251001",
        system      = system,
        user        = user,
        max_tokens  = 1200,
        temperature = 0,
    )
    text = text.strip()
    if not text:
        return "", cost
    header = f"# Newsletter Insights — {TODAY_STR} ({len(items)} newsletter(s))\n"
    return header + "\n" + text, cost

def fetch_newsletters(symbols):
    """Pull this week's newsletters from iCloud, dedup, distill. Returns (digest, cost).

    Mirrors the email-cleanup agent's iCloud IMAP backend. Any failure — missing creds,
    missing dep, IMAP error — degrades gracefully to ("", 0.0) so the report still sends.
    """
    if not (ICLOUD_EMAIL and ICLOUD_APP_PASSWORD and NEWSLETTER_SOURCES):
        print(f"[{TODAY_STR}] Newsletters: skipped (iCloud not configured)")
        return "", 0.0
    try:
        from imap_tools import AND, MailBox
    except ImportError:
        print(f"[{TODAY_STR}] Newsletters: skipped (imap-tools not installed)")
        return "", 0.0

    since = TODAY - datetime.timedelta(days=NEWSLETTER_LOOKBACK_DAYS)
    conn  = init_db()
    # (dedup_key, item) — seen-marking is deferred until distillation succeeds, so a
    # failed run retries the same newsletters next week instead of silently dropping them.
    pending  = []
    run_seen = set()   # in-run guard so the same message in two folders isn't added twice
    try:
        with MailBox(ICLOUD_HOST, port=ICLOUD_PORT).login(
            ICLOUD_EMAIL, ICLOUD_APP_PASSWORD, initial_folder="INBOX"
        ) as box:
            for folder in NEWSLETTER_FOLDERS:
                try:
                    box.folder.set(folder)
                except Exception as e:
                    print(f"  Warning: [newsletters] folder {folder!r} skipped: {e}")
                    continue
                for src in NEWSLETTER_SOURCES:
                    # date_gte → IMAP SINCE; subject → IMAP SUBJECT substring (optional).
                    crit = {"from_": src["from"], "date_gte": since}
                    if src.get("subject"):
                        crit["subject"] = src["subject"]
                    for msg in box.fetch(AND(**crit), limit=NEWSLETTER_MAX, reverse=True,
                                         mark_seen=False, bulk=True):
                        mid = (msg.headers.get("message-id") or (msg.uid,))[0]
                        dedup_key = f"newsletter:{mid}"
                        if dedup_key in run_seen or is_seen(conn, dedup_key):
                            continue
                        body = (msg.text or strip_html(msg.html) or "").strip()
                        if not body:
                            continue
                        run_seen.add(dedup_key)
                        pending.append((dedup_key, {
                            "source":  msg.from_ or "",
                            "subject": msg.subject or "",
                            "date":    msg.date.strftime("%Y-%m-%d") if msg.date else "",
                            "body":    body[:NEWSLETTER_BODY_CAP],
                        }))
    except Exception as e:
        print(f"  Warning: [newsletters] {e}")
        conn.close()
        return "", 0.0

    if not pending:
        print(f"[{TODAY_STR}] Newsletters: 0 new")
        conn.close()
        return "", 0.0

    print(f"[{TODAY_STR}] Newsletters: {len(pending)} new, distilling with Haiku...")
    try:
        digest, cost = distill_newsletters([it for _, it in pending], symbols)
    except Exception as e:
        print(f"  Warning: [newsletters] distill failed: {e}")
        conn.close()
        return "", 0.0

    for dedup_key, _ in pending:
        mark_seen(conn, dedup_key)
    conn.close()
    return digest, cost

# ── GOOGLE SHEETS ─────────────────────────────────────────────────────────────
def fetch_sheet_csv(gid, name):
    if not gid:
        return f"[{name} unavailable: no gid configured]"
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return f"[{name} unavailable]"
        print(f"[{TODAY_STR}] Fetched {name} ({len(r.text)} chars)")
        return r.text
    except Exception as e:
        print(f"[{TODAY_STR}] Warning: {name} failed: {e}")
        return f"[{name} unavailable]"

# ── PORTFOLIO CHANGE DETECTION ────────────────────────────────────────────────
def portfolio_signature(summary_rows, cols):
    """Hash ticker+shares pairs only. Excludes prices, FX, and value columns
    that change every run and would otherwise force a daily FULL re-analysis."""
    if not cols.get("ticker") or not cols.get("shares"):
        # Fallback: hash all cell values (only triggers if column mapping fails)
        return md5("\n".join(",".join(sorted(r.values())) for r in summary_rows))
    pairs = sorted(
        (
            (row.get(cols["ticker"], "").strip().upper(),
             row.get(cols["shares"], "").strip())
            for row in summary_rows
        ),
        key=lambda x: x[0],
    )
    return md5("|".join(f"{t}:{s}" for t, s in pairs))

def portfolio_changed(signature):
    conn = init_db()
    last = get_state(conn, "portfolio_hash")
    changed = signature != last
    set_state(conn, "portfolio_hash", signature)
    conn.close()
    print(f"[{TODAY_STR}] Portfolio {'CHANGED' if changed else 'UNCHANGED'} since last run")
    return changed

# ── INVESTMENT INCOME ─────────────────────────────────────────────────────────
def load_income_summary():
    """Load YTD investment income from the broker DB. Returns formatted text."""
    try:
        from parse_broker_csv import get_ytd_summary
        db = os.path.join(os.path.dirname(__file__), "utils", "taxes", str(TODAY.year), "investment_income.db")
        if not os.path.exists(db):
            return "[Investment income DB not found — run parse_broker_csv.py first]"
        conn = sqlite3.connect(db)
        summary = get_ytd_summary(conn, TODAY.year)
        conn.close()
    except Exception as e:
        return f"[Investment income unavailable: {e}]"

    lines = [f"Investment Income YTD {summary['year']} (all brokers, all accounts):"]
    for ccy, data in summary["by_currency"].items():
        sections = []
        d = data["dividends"]
        if d["gross"]:
            sections.append(f"Dividends: gross={d['gross']} withheld={d['tax_withheld']} net={d['net']}")
        bonds = data["ro_gov_bonds_exempt"]["total_coupons"]
        if bonds:
            sections.append(f"RO Gov Bonds (tax-exempt): coupons={bonds}")
        g = data["realized_gains"]
        if g["gross"]:
            sections.append(f"Realized gains: gross={g['gross']} RO-tax={g['ro_tax_paid']} net={g['net']}")
        i = data["interest"]
        if i["net"]:
            by_broker = i.get("by_broker", {})
            if len(by_broker) > 1:
                broker_parts = ", ".join(
                    f"{b}: {v['net']}" for b, v in sorted(by_broker.items())
                )
                if i["tax_withheld"]:
                    sections.append(f"Interest: gross={i['gross']} tax={i['tax_withheld']} net={i['net']} ({broker_parts})")
                else:
                    sections.append(f"Interest: {i['net']} ({broker_parts})")
            elif by_broker:
                broker_name = next(iter(by_broker))
                if i["tax_withheld"]:
                    sections.append(f"Interest ({broker_name}): gross={i['gross']} tax={i['tax_withheld']} net={i['net']}")
                else:
                    sections.append(f"Interest ({broker_name}): {i['net']}")
            else:
                if i["tax_withheld"]:
                    sections.append(f"Interest: gross={i['gross']} tax={i['tax_withheld']} net={i['net']}")
                else:
                    sections.append(f"Interest: {i['net']}")
        if sections:
            lines.append(f"\n{ccy}:")
            for s in sections:
                lines.append(f"  {s}")

    return "\n".join(lines) if len(lines) > 1 else "[No investment income recorded yet]"

# ── WEEKLY PERFORMANCE COMPARISON ────────────────────────────────────────────
def _fetch_sp500_weekly_change():
    try:
        now     = datetime.datetime.now(datetime.timezone.utc)
        period2 = int(now.timestamp())
        period1 = period2 - 14 * 86400  # 14 days back → ~10 trading days
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC"
               f"?interval=1d&period1={period1}&period2={period2}")
        r = requests.get(url, headers=FEED_HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        closes = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        idx = max(0, len(closes) - 6)  # ~5 trading days ago
        return (closes[-1] / closes[idx] - 1) * 100
    except Exception as e:
        print(f"[{TODAY_STR}] Warning: S&P 500 weekly fetch failed: {e}")
        return None

def _fetch_history_weekly_change(sheet_name):
    """Returns (portfolio_pct, sp500_pct) using Modified Dietz to strip out cash flows."""
    try:
        url = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
               f"/gviz/tq?tqx=out:csv&sheet={requests.utils.quote(sheet_name)}")
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None, None
        reader   = csv.reader(io.StringIO(r.text))
        all_rows = list(reader)
        if len(all_rows) < 3:
            return None, None

        def parse_num(s):
            s = s.replace(",", "").replace("€", "").replace("$", "").strip()
            try:
                return float(s) if s else None
            except ValueError:
                return None

        rows = []
        for row in all_rows[1:]:  # skip header
            if len(row) < 2:
                continue
            d = parse_date(row[0].strip())
            if not d:
                continue
            mv       = parse_num(row[1]) if len(row) > 1 else None
            invested = parse_num(row[2]) if len(row) > 2 else None
            sp500    = parse_num(row[5]) if len(row) > 5 else None
            if mv is not None:
                rows.append((d, mv, invested, sp500))

        if len(rows) < 2:
            return None, None

        week_ago  = TODAY - datetime.timedelta(days=7)
        start_row = next((row for row in reversed(rows) if row[0] <= week_ago), None)
        if start_row is None:
            return None, None
        end_row = rows[-1]

        # S&P 500 weekly return read directly from the sheet
        sp500_start = start_row[3]
        sp500_end   = end_row[3]
        sp500_pct = (sp500_end / sp500_start - 1) * 100 if sp500_start and sp500_end else None

        # Modified Dietz: removes the effect of cash injections/withdrawals.
        # CF detected as day-over-day change in the Invested column.
        v_start    = start_row[1]
        v_end      = end_row[1]
        start_date = start_row[0]
        end_date   = end_row[0]
        D = max((end_date - start_date).days, 1)

        in_window     = [row for row in rows if start_date < row[0] <= end_date]
        cf_sum        = 0.0
        weighted_cf   = 0.0
        prev_invested = start_row[2]
        for row in in_window:
            curr_invested = row[2]
            if curr_invested is not None and prev_invested is not None:
                cf = curr_invested - prev_invested
                if abs(cf) > 0.01:
                    d_i = (row[0] - start_date).days
                    w_i = (D - d_i) / D
                    cf_sum      += cf
                    weighted_cf += w_i * cf
            if curr_invested is not None:
                prev_invested = curr_invested

        denominator = v_start + weighted_cf
        if denominator <= 0:
            return None, sp500_pct
        portfolio_pct = (v_end - v_start - cf_sum) / denominator * 100

        return portfolio_pct, sp500_pct

    except Exception as e:
        print(f"[{TODAY_STR}] Warning: {sheet_name} weekly fetch failed: {e}")
        return None, None

def fetch_weekly_comparison():
    etf_pct,    sp500_from_etf    = _fetch_history_weekly_change("ETF History")
    stocks_pct, sp500_from_stocks = _fetch_history_weekly_change("Stocks History")
    sp500_pct = sp500_from_etf or sp500_from_stocks
    if sp500_pct is None:
        sp500_pct = _fetch_sp500_weekly_change()  # fallback to Yahoo Finance
    if sp500_pct is None and etf_pct is None and stocks_pct is None:
        return "[Weekly comparison unavailable]"
    lines = ["Past 7 days vs S&P 500:"]
    if sp500_pct is not None:
        lines.append(f"  S&P 500:          {sp500_pct:+.2f}%")
    if etf_pct is not None:
        delta = etf_pct - sp500_pct if sp500_pct is not None else None
        delta_str = f"  (delta {delta:+.2f}%)" if delta is not None else ""
        lines.append(f"  ETF Portfolio:    {etf_pct:+.2f}%{delta_str}")
    if stocks_pct is not None:
        delta = stocks_pct - sp500_pct if sp500_pct is not None else None
        delta_str = f"  (delta {delta:+.2f}%)" if delta is not None else ""
        lines.append(f"  Stocks Portfolio: {stocks_pct:+.2f}%{delta_str}")
    return "\n".join(lines)

# ── LOAD SKILL ────────────────────────────────────────────────────────────────
skill_path = os.path.join(os.path.dirname(__file__), "SKILL.md")
with open(skill_path, "r", encoding="utf-8") as f:
    SKILL_CONTENT = f.read().replace("{{TODAY}}", TODAY_STR)

tax_path = os.path.join(os.path.dirname(__file__), "ROMANIAN_TAX.md")
with open(tax_path, "r", encoding="utf-8") as f:
    ROMANIAN_TAX_CONTENT = f.read()

# ── FETCH DATA ────────────────────────────────────────────────────────────────
print(f"[{TODAY_STR}] Fetching portfolio data...")
summary_csv    = fetch_sheet_csv(SHEET_GIDS["Summary"],    "Summary")
utilities_csv  = fetch_sheet_csv(SHEET_GIDS["Utilities"],  "Utilities")

summary_headers, summary_rows = parse_csv(summary_csv)
summary_cols = resolve_columns(summary_headers, SUMMARY_COL_HINTS)
print(f"[{TODAY_STR}] Summary cols resolved: {summary_cols}")

symbols = extract_symbols(summary_rows, summary_cols)
print(f"[{TODAY_STR}] Symbols from Summary: {symbols}")

# Build the FIFO tax table from the clean per-portfolio transaction tabs, unioned.
# Each tab resolves its own columns; rows are normalized to canonical keys so tabs
# with slightly different headers still combine cleanly.
_REQUIRED_TX = ("date", "ticker", "action", "shares")
tx_rows = []
for tab, gid in TX_SHEETS.items():
    headers, rows = parse_csv(fetch_sheet_csv(gid, tab))
    if not rows:
        print(f"[{TODAY_STR}] Warning: {tab} empty or unavailable")
        continue
    cols = resolve_columns(headers, TRANZACTII_COL_HINTS)
    if not all(cols.get(k) for k in _REQUIRED_TX):
        print(f"[{TODAY_STR}] Warning: {tab} missing required columns, skipped: {cols}")
        continue
    tx_rows.extend({k: r.get(cols[k], "") for k in _REQUIRED_TX} for r in rows)
    print(f"[{TODAY_STR}] {tab}: {len(rows)} transactions")

tax_data  = build_tax_table(tx_rows, {k: k for k in _REQUIRED_TX}, TODAY) if tx_rows else None
tax_table = format_tax_table(tax_data)
print(f"[{TODAY_STR}] Tax table:\n{tax_table}")

print(f"[{TODAY_STR}] Loading investment income...")
income_summary = load_income_summary()
print(f"[{TODAY_STR}] Income summary:\n{income_summary}")

print(f"[{TODAY_STR}] Fetching RSS feeds...")
news_digest = fetch_all_news(symbols)

print(f"[{TODAY_STR}] Fetching newsletters (iCloud)...")
newsletter_digest, newsletter_cost = fetch_newsletters(symbols)

print(f"[{TODAY_STR}] Fetching weekly comparison...")
weekly_comparison = fetch_weekly_comparison()
print(f"[{TODAY_STR}] Weekly comparison:\n{weekly_comparison}")

# Hash on positional columns only — won't drift with daily price/FX moves
signature = portfolio_signature(summary_rows, summary_cols)
is_full   = portfolio_changed(signature)

if is_full:
    print(f"[{TODAY_STR}] Mode: FULL")
    analysis_scope = """Perform a FULL analysis — 8 sections only:
1. Portfolio Overview — total value EUR, all holdings in one compact table. Include the weekly ETF vs S&P 500 comparison AND Stocks portfolio vs S&P 500 comparison from the data provided (1 line each).
2. Individual Stocks — per stock: long/short share split, tax bracket, buy/sell/hold. Show values in their ORIGINAL currency (USD for US stocks, RON for Romanian stocks). Do NOT convert individual stock values to EUR.
3. Global News — 3-5 items from digest
4. Stock-Specific News — per ticker from digest
5. Romania News — from digest
6. Crypto / Bitcoin — BTC price trend, key news from digest, brief outlook (1 paragraph)
7. Watchlist & Alerts — 3-5 opportunities or risks
8. Investment Income YTD — per currency: dividends (gross/net/withheld), realized gains (gross/net/tax), interest. Note RO gov bonds separately as tax-exempt. Keep it factual, no narrative.

Currency rule: Use EUR only for portfolio-level totals and cross-portfolio comparisons. Individual stock values stay in their original currency.
Do NOT include: separate ETF section, separate Romania portfolio section, tax notes."""
else:
    print(f"[{TODAY_STR}] Mode: INCREMENTAL")
    analysis_scope = """Portfolio UNCHANGED. Sections 1-2: one-line summary each only. Section 1 must include the weekly ETF vs S&P 500 comparison AND Stocks portfolio vs S&P 500 comparison from the data provided (1 line each).
Focus on sections 3-8 in full detail:
3. Global News — 3-5 items from digest
4. Stock-Specific News — per ticker from digest
5. Romania News — from digest
6. Crypto / Bitcoin — BTC price trend, key news from digest, brief outlook (1 paragraph)
7. Watchlist & Alerts — 3-5 opportunities or risks
8. Investment Income YTD — per currency: dividends (gross/net/withheld), realized gains (gross/net/tax), interest. Note RO gov bonds separately as tax-exempt. Keep it factual, no narrative.

Currency rule: Use EUR only for portfolio-level totals and cross-portfolio comparisons. Individual stock values stay in their original currency (USD for US stocks, RON for Romanian stocks).
Do NOT include: separate ETF section, separate Romania portfolio section, tax notes."""

# ── STEP 1: SONNET ANALYSIS ───────────────────────────────────────────────────
# Load prior calls (memory) so stances stay consistent week-to-week instead of
# whipsawing on a single noisy week. Same SQLite/cache rail as the article dedup.
_mem_conn = init_db()
seed_baseline_if_empty(_mem_conn)
prior_week, prior_recs = get_prior_recommendations(_mem_conn)
_mem_conn.close()
prior_recs_block = format_prior_recommendations(prior_week, prior_recs)
print(f"[{TODAY_STR}] Prior recommendations: {len(prior_recs)} from {prior_week}")

# Standing instruction (both modes) — emit the machine-readable ledger we persist.
REC_INSTRUCTION = (
    "After the report text, output a machine-readable block used to track your calls "
    "week-to-week. Wrap it EXACTLY in these markers and write NOTHING after the closing marker:\n"
    f"{REC_START}\n"
    '[{"ticker":"VST","stance":"HOLD","conviction":"medium","thesis":"<=10 words",'
    '"catalyst":"<=10 words or empty","price":148.76,"pnl_pct":-4.9}, ...]\n'
    f"{REC_END}\n"
    "Include one object for EVERY US individual stock in the holdings (exclude ETFs, bonds, "
    "and Romanian holdings). stance must be one of BUY, ADD, HOLD, TRIM, SELL. Use plain numbers "
    "for price and pnl_pct (no $ or %). This block is metadata only and must NOT appear anywhere "
    "in the report sections above."
)

SONNET_SYSTEM = SKILL_CONTENT + "\n\n---\n\n" + ROMANIAN_TAX_CONTENT

# Newsletter insights are folded into the existing News/Stock-Specific/Watchlist
# sections — no separate report section. Empty when nothing new came in this week.
newsletter_block = (
    "\n### Newsletter insights (distilled from subscribed newsletters)\n"
    "Use these to inform the Global News, Stock-Specific News, and Watchlist sections — "
    "do NOT create a separate newsletter section.\n"
    f"{newsletter_digest}\n"
    if newsletter_digest else ""
)

SONNET_USER = f"""Analyse this portfolio for {TODAY_STR}. Output plain text only — NO HTML, NO markdown.
Use short labeled sections. Be concise, use numbers not prose.

### Holdings (Summary)
{summary_csv}

### Exchange rates (Utilities)
{utilities_csv}

### Tax brackets (pre-computed FIFO from Tranzactii — use these, do not recompute)
{tax_table}

### Investment Income YTD {TODAY.year} (all brokers, all accounts)
{income_summary}

### Weekly Performance vs S&P 500
{weekly_comparison}

### Prior recommendations (YOUR previous calls — maintain unless something specific changed)
{prior_recs_block}

### News digest (titles only)
{news_digest}
{newsletter_block}
{analysis_scope}

{REC_INSTRUCTION}"""

print(f"[{TODAY_STR}] Step 1: Sonnet analysis...")
analysis_text, sonnet_cost = claude_call(
    model      = "claude-sonnet-4-6",
    system     = SONNET_SYSTEM,
    user       = SONNET_USER,
    max_tokens = 4000,
)
print(f"[{TODAY_STR}] Analysis: {len(analysis_text)} chars")

# Split the machine-readable ledger out (so it never reaches Haiku/the report) and
# persist it as this week's memory. A parse miss degrades gracefully — the report
# still sends; only the memory update is skipped.
analysis_text, recs = extract_recommendations(analysis_text)
if recs:
    _mem_conn = init_db()
    saved = save_recommendations(_mem_conn, recs)
    _mem_conn.close()
    print(f"[{TODAY_STR}] Saved {saved} recommendations to memory")
else:
    print(f"[{TODAY_STR}] No recommendations parsed — memory not updated this run")

# ── STEP 2: HAIKU HTML RENDERING ──────────────────────────────────────────────
# The report format is pinned to a fixed golden template (the 2026-05-25 layout).
# Haiku reproduces the template's structure/CSS verbatim and only swaps in the new
# data — this keeps every weekly report visually identical week-to-week.
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "report_template.html")
with open(TEMPLATE_PATH, encoding="utf-8") as f:
    TEMPLATE_HTML = f.read().replace("__DASHBOARD_URL__", DASHBOARD_URL)

HAIKU_SYSTEM = """You are an HTML report renderer. You are given a GOLDEN TEMPLATE (a complete, \
styled HTML report) and a new portfolio analysis. Reproduce the template EXACTLY — identical <style> \
block, identical section order and headings, identical HTML structure and CSS classes — but replace its \
example data with data from the new analysis. Do not invent, add, remove, or reorder sections, and do not \
change any CSS. Output ONLY the raw HTML document starting with <!DOCTYPE html>. No markdown, no code \
fences, no commentary."""

HAIKU_USER = f"""Render the portfolio analysis below into HTML by reproducing the GOLDEN TEMPLATE exactly.

Rules:
- Copy the template's <style> block verbatim — same colours, fonts, spacing, class names.
- Keep the same 8 sections in the same order with the same headings and numbering.
- Reuse the template's component patterns: .summary-box rows, the holdings <table>, .stock-detail cards
  grouped under "Sell Recommendations" / "Hold Recommendations", .section-intro callouts,
  .alert / .alert.opportunity / .alert.sell cards, and .summary-row lists.
- Use class="positive" for gains and class="negative" for losses.
- Keep the dashboard button at the very top with the exact href already present in the template.
- Populate every section from the analysis. The template's data is only an EXAMPLE — replace all of it.
  If the analysis has no data for a row, omit that row (never leave example values in).
- Do NOT add any "API Cost" footer; that is appended separately.
- Set the <title> and the .report-date to {TODAY_STR}.
- Output raw HTML only. No ``` fences, no commentary.

===== GOLDEN TEMPLATE (reproduce this structure and style exactly) =====
{TEMPLATE_HTML}

===== NEW ANALYSIS TO RENDER (this is the data source) =====
Report date: {TODAY_STR}

{analysis_text}"""

print(f"[{TODAY_STR}] Step 2: Haiku HTML rendering...")
html_report, haiku_cost = claude_call(
    model       = "claude-haiku-4-5-20251001",
    system      = HAIKU_SYSTEM,
    user        = HAIKU_USER,
    max_tokens  = 10000,
    temperature = 0,
)
print(f"[{TODAY_STR}] Report: {len(html_report)} chars")

# Defensive: strip any stray markdown code fences Haiku may wrap the document in.
html_report = html_report.strip()
if html_report.startswith("```"):
    html_report = html_report[html_report.find("\n") + 1:]
    html_report = html_report.rsplit("```", 1)[0]
    html_report = html_report.strip()

if not html_report.strip():
    raise RuntimeError("Empty HTML report from Haiku")

total_cost = sonnet_cost + haiku_cost + newsletter_cost
print(f"[{TODAY_STR}] Total API cost: ${total_cost:.4f}")

# Newsletter distill row only appears when there were newsletters to distill.
newsletter_cost_row = (
    f'    <tr><td style="padding:2px 16px 2px 0">Haiku 4.5 (newsletter distill)</td>'
    f'<td style="text-align:right">${newsletter_cost:.4f}</td></tr>\n'
    if newsletter_cost else ""
)

cost_footer = f"""
<div style="margin-top:40px;padding:12px 16px;background:#f8f8f8;border-top:1px solid #ddd;font-family:sans-serif;font-size:13px;color:#555">
  <strong>API Cost — {TODAY_STR}</strong>
  <table style="margin-top:6px;border-collapse:collapse">
    <tr><td style="padding:2px 16px 2px 0">Sonnet 4.6 (analysis)</td><td style="text-align:right">${sonnet_cost:.4f}</td></tr>
    <tr><td style="padding:2px 16px 2px 0">Haiku 4.5 (HTML render)</td><td style="text-align:right">${haiku_cost:.4f}</td></tr>
{newsletter_cost_row}    <tr style="font-weight:bold;border-top:1px solid #ccc"><td style="padding:4px 16px 2px 0">Total</td><td style="text-align:right">${total_cost:.4f}</td></tr>
  </table>
</div>"""

if "</body>" in html_report:
    html_report = html_report.replace("</body>", cost_footer + "\n</body>", 1)
else:
    html_report += cost_footer

# ── SAVE HTML ─────────────────────────────────────────────────────────────────
filename = os.path.join(os.path.dirname(__file__), f"portfolio-analysis-{TODAY_STR}.html")
with open(filename, "w", encoding="utf-8") as f:
    f.write(html_report)
print(f"[{TODAY_STR}] Saved {filename}")

# ── SEND EMAIL ────────────────────────────────────────────────────────────────
mode = "Full" if is_full else "Incremental"
msg  = MIMEMultipart("alternative")
msg["Subject"] = f"Portfolio Analysis ({mode}) — {TODAY_STR}"
msg["From"]    = GMAIL_USER
msg["To"]      = RECIPIENT_EMAIL

msg.attach(MIMEText(f"Portfolio analysis ready.\nDate: {TODAY_STR} | Mode: {mode}", "plain"))
msg.attach(MIMEText(html_report, "html"))
attachment = MIMEText(html_report, "html")
attachment.add_header("Content-Disposition", "attachment", filename=os.path.basename(filename))
msg.attach(attachment)

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
print(f"[{TODAY_STR}] Email sent — Done!")
