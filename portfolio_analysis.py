import os
import re
import csv
import io
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

TODAY     = datetime.date.today()
TODAY_STR = TODAY.strftime("%Y-%m-%d")
DB_PATH   = os.path.join(os.path.dirname(__file__), "seen_articles.db")

# Google Sheet — Tranzactii gid must be set via env var TRANZACTII_GID
SHEET_ID   = "1qbb0x_kNtIUp4cq-_O9uFi6stbcSPwTeTnXOd1DbzOo"
SHEET_GIDS = {
    "Summary":    "1633571629",
    "Utilities":  "2066207814",
    "Tranzactii": "1445112517",
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

# Macro/topic keywords — only used to filter the general financial news bucket.
MACRO_KEYWORDS = [
    "Fed", "FOMC", "ECB", "BNR", "inflation", "interest rate",
    "recession", "Romania", "RON", "EUR/USD", "EUR",
    "S&P 500", "STOXX", "REIT", "bond yield", "Treasury",
    "Bitcoin", "BTC", "crypto", "cryptocurrency", "Ethereum", "ETH",
    "Trump", "Musk",
]

MAX_ITEMS_TOTAL = 30
MAX_PER_FEED    = 3

# ── RSS FEEDS ─────────────────────────────────────────────────────────────────
# Only live, verified feeds. Per-ticker feeds are built at runtime from holdings
RSS_FEEDS_STATIC = {
    "General Financial News": [
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("CNBC",        "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("NYT Business",    "https://rss.nytimes.com/services/xml/rss/nf/Business.xml"),
        ("NYT Economy",     "https://rss.nytimes.com/services/xml/rss/nf/Economy.xml"),
        ("NYT Technology",  "https://rss.nytimes.com/services/xml/rss/nf/Technology.xml"),
        ("NYT US",          "https://rss.nytimes.com/services/xml/rss/nf/US.xml"),
        ("NYT World",       "https://rss.nytimes.com/services/xml/rss/nf/World.xml"),
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

# ── HELPERS ───────────────────────────────────────────────────────────────────
def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()

def md5(text):
    return hashlib.md5(text.encode()).hexdigest()

def claude_call(model, system, user, max_tokens):
    """Returns (text, cost_usd)."""
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
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
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y", "%Y/%m/%d"):
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
tranzactii_csv = fetch_sheet_csv(SHEET_GIDS["Tranzactii"], "Tranzactii")

summary_headers,    summary_rows    = parse_csv(summary_csv)
tranzactii_headers, tranzactii_rows = parse_csv(tranzactii_csv)

summary_cols    = resolve_columns(summary_headers,    SUMMARY_COL_HINTS)
tranzactii_cols = resolve_columns(tranzactii_headers, TRANZACTII_COL_HINTS)

print(f"[{TODAY_STR}] Summary cols resolved: {summary_cols}")
print(f"[{TODAY_STR}] Tranzactii cols resolved: {tranzactii_cols}")

symbols = extract_symbols(summary_rows, summary_cols)
print(f"[{TODAY_STR}] Symbols from Summary: {symbols}")

tax_data  = build_tax_table(tranzactii_rows, tranzactii_cols, TODAY)
tax_table = format_tax_table(tax_data)
print(f"[{TODAY_STR}] Tax table:\n{tax_table}")

print(f"[{TODAY_STR}] Fetching RSS feeds...")
news_digest = fetch_all_news(symbols)

# Hash on positional columns only — won't drift with daily price/FX moves
signature = portfolio_signature(summary_rows, summary_cols)
is_full   = portfolio_changed(signature)

if is_full:
    print(f"[{TODAY_STR}] Mode: FULL")
    analysis_scope = """Perform a FULL analysis — 7 sections only:
1. Portfolio Overview — total value EUR, all holdings in one compact table
2. Individual Stocks — per stock: long/short share split, tax bracket, buy/sell/hold
3. Global News — 3-5 items from digest
4. Stock-Specific News — per ticker from digest
5. Romania News — from digest
6. Crypto / Bitcoin — BTC price trend, key news from digest, brief outlook (1 paragraph)
7. Watchlist & Alerts — 3-5 opportunities or risks

Do NOT include: separate ETF section, separate Romania portfolio section, tax notes, dividend income."""
else:
    print(f"[{TODAY_STR}] Mode: INCREMENTAL")
    analysis_scope = """Portfolio UNCHANGED. Sections 1-2: one-line summary each only.
Focus on sections 3-7 in full detail:
3. Global News — 3-5 items from digest
4. Stock-Specific News — per ticker from digest
5. Romania News — from digest
6. Crypto / Bitcoin — BTC price trend, key news from digest, brief outlook (1 paragraph)
7. Watchlist & Alerts — 3-5 opportunities or risks

Do NOT include: separate ETF section, separate Romania portfolio section, tax notes, dividend income."""

# ── STEP 1: SONNET ANALYSIS ───────────────────────────────────────────────────
SONNET_SYSTEM = SKILL_CONTENT + "\n\n---\n\n" + ROMANIAN_TAX_CONTENT

SONNET_USER = f"""Analyse this portfolio for {TODAY_STR}. Output plain text only — NO HTML, NO markdown.
Use short labeled sections. Be concise, use numbers not prose.

### Holdings (Summary)
{summary_csv}

### Exchange rates (Utilities)
{utilities_csv}

### Tax brackets (pre-computed FIFO from Tranzactii — use these, do not recompute)
{tax_table}

### News digest (titles only)
{news_digest}

{analysis_scope}"""

print(f"[{TODAY_STR}] Step 1: Sonnet analysis...")
analysis_text, sonnet_cost = claude_call(
    model      = "claude-sonnet-4-6",
    system     = SONNET_SYSTEM,
    user       = SONNET_USER,
    max_tokens = 4000,
)
print(f"[{TODAY_STR}] Analysis: {len(analysis_text)} chars")

# ── STEP 2: HAIKU HTML RENDERING ──────────────────────────────────────────────
HAIKU_SYSTEM = """You are an HTML report renderer. Convert the analysis text into a clean,
readable HTML report. Use simple styling only. Output ONLY the complete HTML document."""

HAIKU_USER = f"""Convert this portfolio analysis into a clean HTML report.

Title: portfolio-analysis-{TODAY_STR}

Style:
- White background, dark text, simple sans-serif font
- Use a simple <table> for data, <h2> for section headers
- Green for positive values, red for negative
- No external dependencies, fully self-contained
- Mobile-friendly with max-width: 800px centered

Dashboard Link:
Add a prominent button/link at the TOP of the report: "View Interactive Dashboard"
URL: {DASHBOARD_URL}
Style it as a blue button or link that stands out.

Analysis to render:
{analysis_text}"""

print(f"[{TODAY_STR}] Step 2: Haiku HTML rendering...")
html_report, haiku_cost = claude_call(
    model      = "claude-haiku-4-5-20251001",
    system     = HAIKU_SYSTEM,
    user       = HAIKU_USER,
    max_tokens = 10000,
)
print(f"[{TODAY_STR}] Report: {len(html_report)} chars")

if not html_report.strip():
    raise RuntimeError("Empty HTML report from Haiku")

total_cost = sonnet_cost + haiku_cost
print(f"[{TODAY_STR}] Total API cost: ${total_cost:.4f}")

cost_footer = f"""
<div style="margin-top:40px;padding:12px 16px;background:#f8f8f8;border-top:1px solid #ddd;font-family:sans-serif;font-size:13px;color:#555">
  <strong>API Cost — {TODAY_STR}</strong>
  <table style="margin-top:6px;border-collapse:collapse">
    <tr><td style="padding:2px 16px 2px 0">Sonnet 4.6 (analysis)</td><td style="text-align:right">${sonnet_cost:.4f}</td></tr>
    <tr><td style="padding:2px 16px 2px 0">Haiku 4.5 (HTML render)</td><td style="text-align:right">${haiku_cost:.4f}</td></tr>
    <tr style="font-weight:bold;border-top:1px solid #ccc"><td style="padding:4px 16px 2px 0">Total</td><td style="text-align:right">${total_cost:.4f}</td></tr>
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
