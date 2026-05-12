import os
import re
import sqlite3
import hashlib
import datetime
import smtplib
import requests
import feedparser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── CONFIG ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER         = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL    = os.environ["RECIPIENT_EMAIL"]

TODAY   = datetime.date.today().strftime("%Y-%m-%d")
DB_PATH = "seen_articles.db"

PORTFOLIO_SYMBOLS = [
    "AMZN", "ADBE", "PTC", "OSPN", "OTEX", "LULU",
    "CSPX", "EXSA", "IWDP", "BET",
    "Amazon", "Adobe", "Lululemon", "OpenText",
    "S&P", "STOXX", "REIT", "Romania", "RON", "EUR",
    "Fed", "ECB", "inflation", "interest rate", "recession",
]

MAX_ITEMS_TOTAL   = 30
MAX_PER_FEED      = 3
SUMMARY_MAX_CHARS = 150

# ── RSS FEED DEFINITIONS ──────────────────────────────────────────────────────
RSS_FEEDS = {
    "General Financial News": [
        ("MarketWatch",   "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("CNBC",          "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("Seeking Alpha", "https://seekingalpha.com/feed.xml"),
        ("Reuters",       "https://feeds.reuters.com/reuters/businessNews"),
    ],
    "Individual Stocks": [
        ("AMZN", "https://finance.yahoo.com/rss/headline?s=AMZN"),
        ("ADBE", "https://finance.yahoo.com/rss/headline?s=ADBE"),
        ("PTC",  "https://finance.yahoo.com/rss/headline?s=PTC"),
        ("OSPN", "https://finance.yahoo.com/rss/headline?s=OSPN"),
        ("OTEX", "https://finance.yahoo.com/rss/headline?s=OTEX"),
        ("LULU", "https://finance.yahoo.com/rss/headline?s=LULU"),
    ],
    "ETFs & Markets": [
        ("S&P500", "https://finance.yahoo.com/rss/headline?s=^GSPC"),
    ],
    "Romania": [
        ("Profit.ro", "https://www.profit.ro/rss"),
        ("Ziare.com", "https://www.ziare.com/rss/business.xml"),
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
        (str(datetime.date.today() - datetime.timedelta(days=14)),)
    )
    conn.commit()
    return conn

def is_seen(conn, url):
    return conn.execute("SELECT 1 FROM seen_articles WHERE url = ?", (url,)).fetchone() is not None

def mark_seen(conn, url):
    conn.execute("INSERT OR IGNORE INTO seen_articles (url, seen_on) VALUES (?, ?)", (url, TODAY))
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

def is_relevant(title, summary):
    text = (title + " " + summary).upper()
    return any(sym.upper() in text for sym in PORTFOLIO_SYMBOLS)

def md5(text):
    return hashlib.md5(text.encode()).hexdigest()

def claude_call(model, system, user, max_tokens):
    """Single reusable API call function."""
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
    data = response.json()
    usage = data.get("usage", {})
    print(f"  [{model}] input: {usage.get('input_tokens',0)}, output: {usage.get('output_tokens',0)}")
    return "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")

# ── RSS FETCHER ───────────────────────────────────────────────────────────────
def fetch_feed(label, url, conn, general=False):
    try:
        feed = feedparser.parse(url, request_headers=FEED_HEADERS)
        results = []
        for entry in feed.entries[:20]:
            title   = strip_html(entry.get("title", ""))
            summary = strip_html(entry.get("summary", entry.get("description", "")))[:SUMMARY_MAX_CHARS]
            link    = entry.get("link", entry.get("id", ""))
            if not title:
                continue
            if is_seen(conn, link or title):
                continue
            if general and not is_relevant(title, summary):
                continue
            mark_seen(conn, link or title)
            results.append({"label": label, "title": title, "summary": summary})
            if len(results) >= MAX_PER_FEED:
                break
        print(f"  [{label}] {len(results)} new items")
        return results
    except Exception as e:
        print(f"  Warning: [{label}] {e}")
        return []

def fetch_all_news():
    conn = init_db()
    sections = {}
    total = 0
    for category, feeds in RSS_FEEDS.items():
        is_general = category == "General Financial News"
        items = []
        for label, url in feeds:
            items.extend(fetch_feed(label, url, conn, general=is_general))
        sections[category] = items
        total += len(items)
    conn.close()

    if total > MAX_ITEMS_TOTAL:
        ratio = MAX_ITEMS_TOTAL / total
        for cat in sections:
            sections[cat] = sections[cat][:max(1, int(len(sections[cat]) * ratio))]
        total = sum(len(v) for v in sections.values())

    print(f"[{TODAY}] Total news items: {total}")
    lines = [f"# News Digest — {TODAY} ({total} items)\n"]
    for category, items in sections.items():
        if not items:
            continue
        lines.append(f"\n## {category}")
        for item in items:
            lines.append(f"[{item['label']}] {item['title']}")
            if item["summary"]:
                lines.append(f"  → {item['summary']}")
    return "\n".join(lines)

# ── GOOGLE SHEETS ─────────────────────────────────────────────────────────────
SHEET_ID = "1qbb0x_kNtIUp4cq-_O9uFi6stbcSPwTeTnXOd1DbzOo"

def fetch_sheet_csv(gid, name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return f"[{name} unavailable]"
        print(f"[{TODAY}] Fetched {name} ({len(r.text)} chars)")
        return r.text
    except Exception as e:
        print(f"[{TODAY}] Warning: {name} failed: {e}")
        return f"[{name} unavailable]"

# ── PORTFOLIO CHANGE DETECTION ────────────────────────────────────────────────
def portfolio_changed(summary_csv, utilities_csv):
    conn = init_db()
    current_hash = md5(summary_csv + utilities_csv)
    last_hash    = get_state(conn, "portfolio_hash")
    changed      = current_hash != last_hash
    set_state(conn, "portfolio_hash", current_hash)
    conn.close()
    print(f"[{TODAY}] Portfolio {'CHANGED' if changed else 'UNCHANGED'} since last run")
    return changed

# ── LOAD SKILL ────────────────────────────────────────────────────────────────
skill_path = os.path.join(os.path.dirname(__file__), "SKILL.md")
with open(skill_path, "r", encoding="utf-8") as f:
    SKILL_CONTENT = f.read().replace("{{TODAY}}", TODAY)

# ── FETCH DATA ────────────────────────────────────────────────────────────────
print(f"[{TODAY}] Fetching portfolio data...")
summary_csv   = fetch_sheet_csv("1633571629", "Summary")
utilities_csv = fetch_sheet_csv("2066207814", "Utilities")

print(f"[{TODAY}] Fetching RSS feeds...")
news_digest = fetch_all_news()

is_full = portfolio_changed(summary_csv, utilities_csv)

if is_full:
    print(f"[{TODAY}] Mode: FULL")
    analysis_scope = """Perform a FULL analysis — 6 sections only:
1. Portfolio Overview — total value EUR, all holdings in one compact table (ETFs + stocks + Romania)
2. Individual Stocks — each stock: days held, tax rate (3%/6%), buy/sell/hold recommendation
3. Global News — 3-5 items from digest
4. Stock-Specific News — per ticker from digest
5. Romania News — from digest
6. Watchlist & Alerts — 3-5 opportunities or risks

Do NOT include: separate ETF section, separate Romania portfolio section, tax notes, dividend income, positions >365 days detail."""
else:
    print(f"[{TODAY}] Mode: INCREMENTAL")
    analysis_scope = """Portfolio UNCHANGED. Sections 1-2: one-line summary each only.
Focus on sections 3-6 in full detail:
3. Global News — 3-5 items from digest
4. Stock-Specific News — per ticker from digest
5. Romania News — from digest
6. Watchlist & Alerts — 3-5 opportunities or risks

Do NOT include: separate ETF section, separate Romania portfolio section, tax notes, dividend income."""

# ── STEP 1: SONNET ANALYSIS (plain text, cheap output) ───────────────────────
SONNET_SYSTEM = SKILL_CONTENT

SONNET_USER = f"""Analyse this portfolio for {TODAY}. Output plain text only — NO HTML, NO markdown.
Use short labeled sections. Be concise, use numbers not prose where possible.

Portfolio data:
### Summary
{summary_csv}

### Exchange rates
{utilities_csv}

### News digest
{news_digest}

{analysis_scope}"""

print(f"[{TODAY}] Step 1: Sonnet analysis...")
analysis_text = claude_call(
    model      = "claude-sonnet-4-6",
    system     = SONNET_SYSTEM,
    user       = SONNET_USER,
    max_tokens = 6000,   # enough for all 9 sections in plain text
)
print(f"[{TODAY}] Analysis: {len(analysis_text)} chars")

# ── STEP 2: HAIKU HTML RENDERING (cheap, just formats the text) ──────────────
HAIKU_SYSTEM = """You are an HTML report renderer. Convert the analysis text you receive into a clean, 
readable HTML report. Use simple styling only — no complex dashboards, no heavy CSS frameworks.
Output ONLY the complete HTML document, nothing else."""

HAIKU_USER = f"""Convert this portfolio analysis into a clean HTML report.

Title: portfolio-analysis-{TODAY}

Style requirements (keep it minimal to save tokens):
- White background, dark text, simple sans-serif font
- Use a simple <table> for data, <h2> for section headers
- Green for positive values, red for negative values
- No external dependencies, no complex CSS, fully self-contained
- Mobile-friendly with max-width: 800px centered

Analysis to render:
{analysis_text}"""

print(f"[{TODAY}] Step 2: Haiku HTML rendering...")
html_report = claude_call(
    model      = "claude-haiku-4-5-20251001",
    system     = HAIKU_SYSTEM,
    user       = HAIKU_USER,
    max_tokens = 12000,
)
print(f"[{TODAY}] Report: {len(html_report)} chars")

if not html_report.strip():
    raise RuntimeError("Empty HTML report from Haiku")

# ── SAVE HTML ─────────────────────────────────────────────────────────────────
filename = f"portfolio-analysis-{TODAY}.html"
with open(filename, "w", encoding="utf-8") as f:
    f.write(html_report)
print(f"[{TODAY}] Saved {filename}")

# ── SEND EMAIL ────────────────────────────────────────────────────────────────
mode = "Full" if is_full else "Incremental"
msg  = MIMEMultipart("alternative")
msg["Subject"] = f"Portfolio Analysis ({mode}) — {TODAY}"
msg["From"]    = GMAIL_USER
msg["To"]      = RECIPIENT_EMAIL

msg.attach(MIMEText(f"Portfolio analysis ready.\nDate: {TODAY} | Mode: {mode}", "plain"))
msg.attach(MIMEText(html_report, "html"))
attachment = MIMEText(html_report, "html")
attachment.add_header("Content-Disposition", "attachment", filename=filename)
msg.attach(attachment)

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
print(f"[{TODAY}] Email sent — Done!")
