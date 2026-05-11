import os
import re
import sqlite3
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

# Portfolio keywords for filtering general feeds
PORTFOLIO_SYMBOLS = [
    "AMZN", "ADBE", "PTC", "OSPN", "OTEX", "LULU",
    "CSPX", "EXSA", "IWDP", "BET",
    "Amazon", "Adobe", "Lululemon", "OpenText",
    "S&P", "STOXX", "REIT", "Romania", "RON", "EUR",
    "Fed", "ECB", "inflation", "interest rate", "recession",
]

MAX_ITEMS_TOTAL  = 30   # hard cap — keeps prompt size manageable
MAX_PER_FEED     = 3    # max items per individual feed
SUMMARY_MAX_CHARS = 150 # keep summaries short to save tokens

# ── RSS FEED DEFINITIONS ──────────────────────────────────────────────────────
# Removed duplicate Google News feeds for same tickers — Yahoo Finance is enough
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
def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_articles (
            url     TEXT PRIMARY KEY,
            seen_on TEXT NOT NULL
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

# ── HELPERS ───────────────────────────────────────────────────────────────────
def strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()

def is_relevant(title, summary):
    text = (title + " " + summary).upper()
    return any(sym.upper() in text for sym in PORTFOLIO_SYMBOLS)

# ── RSS PARSER ────────────────────────────────────────────────────────────────
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
            results.append({"label": label, "title": title, "summary": summary, "link": link})
            if len(results) >= MAX_PER_FEED:
                break
        print(f"  [{label}] {len(results)} new items")
        return results
    except Exception as e:
        print(f"  Warning: [{label}] {e}")
        return []

# ── MAIN NEWS FETCHER ─────────────────────────────────────────────────────────
def fetch_all_news() -> str:
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

    # Enforce global cap — trim proportionally per category
    if total > MAX_ITEMS_TOTAL:
        ratio = MAX_ITEMS_TOTAL / total
        for cat in sections:
            keep = max(1, int(len(sections[cat]) * ratio))
            sections[cat] = sections[cat][:keep]
        total = sum(len(v) for v in sections.values())

    print(f"[{TODAY}] Total news items after filtering & cap: {total}")

    # Format compactly — title + short summary only, no full links (saves tokens)
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

# ── LOAD SKILL ────────────────────────────────────────────────────────────────
skill_path = os.path.join(os.path.dirname(__file__), "SKILL.md")
with open(skill_path, "r", encoding="utf-8") as f:
    SKILL_CONTENT = f.read()

SYSTEM_PROMPT = SKILL_CONTENT.replace("{{TODAY}}", TODAY)

# ── FETCH GOOGLE SHEETS DATA ──────────────────────────────────────────────────
SHEET_ID = "1qbb0x_kNtIUp4cq-_O9uFi6stbcSPwTeTnXOd1DbzOo"

def fetch_sheet_csv(gid, name):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            print(f"[{TODAY}] Warning: could not fetch {name} (status {r.status_code})")
            return f"[{name} data unavailable]"
        print(f"[{TODAY}] Fetched {name} ({len(r.text)} chars)")
        return r.text
    except Exception as e:
        print(f"[{TODAY}] Warning: {name} fetch failed: {e}")
        return f"[{name} data unavailable]"

summary_csv   = fetch_sheet_csv("1633571629", "Summary")
utilities_csv = fetch_sheet_csv("2066207814", "Utilities")

# ── FETCH NEWS ────────────────────────────────────────────────────────────────
print(f"[{TODAY}] Fetching RSS feeds...")
news_digest = fetch_all_news()

# ── USER PROMPT ───────────────────────────────────────────────────────────────
USER_PROMPT = f"""Please perform a full portfolio analysis for today, {TODAY}.

## Portfolio Data (live from Google Sheets)

### Summary (current holdings)
```
{summary_csv}
```

### Utilities (exchange rates)
```
{utilities_csv}
```

## News Digest (pre-fetched from RSS — max 30 items)
{news_digest}

---

Use the portfolio data as the source of truth for holdings, values, and exchange rates.
Use the news digest as the source of truth for all news — do NOT search the web.

IMPORTANT: You MUST write content for ALL 9 sections. Do not leave any section empty.

Be CONCISE on sections 1-5 — use compact tables, no long paragraphs. Reserve space for sections 6-9 which are equally important. Each section should be roughly equal in length.

1. Portfolio Overview — total value in EUR, allocation breakdown
2. ETF Portfolio — holdings, performance, notes
3. Individual Stocks — each stock: current status, days held, tax rate (3% or 6%), buy/sell/hold
4. Romania Portfolio — BET ETF, bonds update
5. Romanian Tax Notes — which positions exceed 365 days, estimated tax on unrealised gains
6. Global News — summarise 3-5 items from the General Financial News section of the digest
7. Stock-Specific News — summarise news per ticker from the digest
8. Romania News — summarise items from the Romania section of the digest
9. Watchlist & Alerts — 3-5 specific opportunities or risks based on the news and holdings

Return a complete, polished HTML report titled "portfolio-analysis-{TODAY}".
Fully self-contained HTML with inline CSS. Dark financial dashboard aesthetic."""

# ── CALL ANTHROPIC API ────────────────────────────────────────────────────────
def run_analysis() -> str:
    print(f"[{TODAY}] Calling Anthropic API...")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 32000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": USER_PROMPT}],
    }

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=500,
    )

    if response.status_code != 200:
        raise RuntimeError(f"Anthropic API error {response.status_code}: {response.text}")

    data = response.json()
    html_report = "".join(
        block["text"] for block in data.get("content", []) if block.get("type") == "text"
    )

    if not html_report.strip():
        raise RuntimeError("Empty response from Anthropic API")

    print(f"[{TODAY}] Analysis complete. Report length: {len(html_report)} chars.")
    return html_report

# ── SAVE HTML ─────────────────────────────────────────────────────────────────
def save_report(html):
    filename = f"portfolio-analysis-{TODAY}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[{TODAY}] Report saved to {filename}")
    return filename

# ── SEND EMAIL ────────────────────────────────────────────────────────────────
def send_email(html, filename):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Portfolio Analysis — {TODAY}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL

    msg.attach(MIMEText(
        f"Your weekly portfolio analysis is ready.\n\nDate: {TODAY}\n\n"
        "Open the attached HTML file or enable HTML email to view the full report.",
        "plain"
    ))
    msg.attach(MIMEText(html, "html"))
    attachment = MIMEText(html, "html")
    attachment.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(attachment)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    print(f"[{TODAY}] Email sent to {RECIPIENT_EMAIL}")

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    html_report = run_analysis()
    filename    = save_report(html_report)
    send_email(html_report, filename)
    print(f"[{TODAY}] Done!")
