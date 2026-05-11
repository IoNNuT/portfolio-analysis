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

TODAY    = datetime.date.today().strftime("%Y-%m-%d")
DB_PATH  = "seen_articles.db"   # SQLite cache — persists in GitHub Actions workspace

# Portfolio symbols used for keyword filtering
PORTFOLIO_SYMBOLS = [
    "AMZN", "ADBE", "PTC", "OSPN", "OTEX", "LULU",   # individual stocks
    "CSPX", "EXSA", "IWDP", "BET",                     # ETFs
    "Amazon", "Adobe", "Lululemon", "OpenText",         # company names
    "S&P", "STOXX", "REIT", "Romania", "RON", "EUR",   # macro keywords
]

MAX_ITEMS_TOTAL = 50   # hard cap on items sent to Claude

# ── RSS FEED DEFINITIONS ──────────────────────────────────────────────────────
RSS_FEEDS = {
    "General Financial News": [
        ("MarketWatch",   "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("CNBC",          "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("Seeking Alpha", "https://seekingalpha.com/feed.xml"),
        ("Reuters",       "https://feeds.reuters.com/reuters/businessNews"),
        ("Investing.com", "https://www.investing.com/rss/news.rss"),
    ],
    "Individual Stocks": [
        ("AMZN", "https://finance.yahoo.com/rss/headline?s=AMZN"),
        ("ADBE", "https://finance.yahoo.com/rss/headline?s=ADBE"),
        ("PTC",  "https://finance.yahoo.com/rss/headline?s=PTC"),
        ("OSPN", "https://finance.yahoo.com/rss/headline?s=OSPN"),
        ("OTEX", "https://finance.yahoo.com/rss/headline?s=OTEX"),
        ("LULU", "https://finance.yahoo.com/rss/headline?s=LULU"),
        # Google News per ticker (broader coverage)
        ("AMZN-GNews", "https://news.google.com/rss/search?q=AMZN+stock&hl=en-US&gl=US&ceid=US:en"),
        ("ADBE-GNews", "https://news.google.com/rss/search?q=ADBE+stock&hl=en-US&gl=US&ceid=US:en"),
        ("LULU-GNews", "https://news.google.com/rss/search?q=LULU+stock&hl=en-US&gl=US&ceid=US:en"),
    ],
    "ETFs & Markets": [
        ("S&P500",     "https://finance.yahoo.com/rss/headline?s=^GSPC"),
        ("CSPX",       "https://finance.yahoo.com/rss/headline?s=CSPX.L"),
        ("EXSA",       "https://finance.yahoo.com/rss/headline?s=EXSA.DE"),
        ("IWDP-REIT",  "https://finance.yahoo.com/rss/headline?s=IWDP.L"),
    ],
    "Romania": [
        ("Profit.ro",  "https://www.profit.ro/rss"),
        ("Ziare.com",  "https://www.ziare.com/rss/business.xml"),
        ("GNews-RO",   "https://news.google.com/rss/search?q=Romania+economy&hl=en-US&gl=US&ceid=US:en"),
    ],
}

FEED_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioBot/1.0)"}

# ── SQLITE CACHE ──────────────────────────────────────────────────────────────
def init_db() -> sqlite3.Connection:
    """Create (or open) the SQLite cache and return a connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_articles (
            url     TEXT PRIMARY KEY,
            seen_on TEXT NOT NULL
        )
    """)
    # Clean up entries older than 14 days to keep the DB small
    conn.execute(
        "DELETE FROM seen_articles WHERE seen_on < ?",
        (str(datetime.date.today() - datetime.timedelta(days=14)),)
    )
    conn.commit()
    return conn

def is_seen(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute("SELECT 1 FROM seen_articles WHERE url = ?", (url,)).fetchone()
    return row is not None

def mark_seen(conn: sqlite3.Connection, url: str):
    conn.execute(
        "INSERT OR IGNORE INTO seen_articles (url, seen_on) VALUES (?, ?)",
        (url, TODAY)
    )
    conn.commit()

# ── SYMBOL FILTER ─────────────────────────────────────────────────────────────
def is_relevant(title: str, summary: str) -> bool:
    """Return True if the article mentions at least one portfolio keyword."""
    text = (title + " " + summary).upper()
    return any(sym.upper() in text for sym in PORTFOLIO_SYMBOLS)

# ── RSS PARSER ────────────────────────────────────────────────────────────────
def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()

def fetch_feed(label: str, url: str, conn: sqlite3.Connection,
               general: bool = False, max_per_feed: int = 8) -> list:
    """
    Parse one RSS feed via feedparser.
    - general feeds: filter by PORTFOLIO_SYMBOLS keywords
    - stock/etf feeds: accept all items (already ticker-specific)
    Returns a list of dicts {label, title, summary, link}.
    """
    try:
        feed = feedparser.parse(url, request_headers=FEED_HEADERS)
        results = []
        for entry in feed.entries[:30]:   # look at up to 30 raw entries
            title   = strip_html(entry.get("title", ""))
            summary = strip_html(entry.get("summary", entry.get("description", "")))[:250]
            link    = entry.get("link", entry.get("id", ""))

            if not title:
                continue
            if is_seen(conn, link or title):
                continue
            if general and not is_relevant(title, summary):
                continue

            mark_seen(conn, link or title)
            results.append({"label": label, "title": title,
                             "summary": summary, "link": link})
            if len(results) >= max_per_feed:
                break

        print(f"  [{label}] {len(results)} new relevant items")
        return results

    except Exception as e:
        print(f"  Warning: feed error [{label}]: {e}")
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

    # Enforce global 50-item cap — trim proportionally per category
    if total > MAX_ITEMS_TOTAL:
        ratio = MAX_ITEMS_TOTAL / total
        for cat in sections:
            keep = max(1, int(len(sections[cat]) * ratio))
            sections[cat] = sections[cat][:keep]
        total = sum(len(v) for v in sections.values())

    print(f"[{TODAY}] Total news items after filtering & cap: {total}")

    # Format as plain text for the prompt
    lines = [f"# News Digest — {TODAY}  ({total} items)\n"]
    for category, items in sections.items():
        if not items:
            continue
        lines.append(f"\n## {category}")
        for item in items:
            lines.append(f"\n[{item['label']}] {item['title']}")
            if item["summary"]:
                lines.append(f"  {item['summary']}")
            if item["link"]:
                lines.append(f"  {item['link']}")

    return "\n".join(lines)

# ── LOAD SKILL ────────────────────────────────────────────────────────────────
skill_path = os.path.join(os.path.dirname(__file__), "SKILL.md")
with open(skill_path, "r", encoding="utf-8") as f:
    SKILL_CONTENT = f.read()

SYSTEM_PROMPT = SKILL_CONTENT.replace("{{TODAY}}", TODAY)

# ── FETCH GOOGLE SHEETS DATA ──────────────────────────────────────────────────
SHEET_ID = "1qbb0x_kNtIUp4cq-_O9uFi6stbcSPwTeTnXOd1DbzOo"

def fetch_sheet_csv(gid: str, name: str) -> str:
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

## News Digest (pre-fetched & filtered from RSS — max 50 items)
{news_digest}

---

Use the portfolio data as the source of truth for holdings, values, and exchange rates.
Use the news digest as the source of truth for all news — do NOT search the web.

IMPORTANT: Complete ALL sections below — do not stop early:
1. Portfolio Overview (total value in EUR, allocation breakdown)
2. ETF Portfolio (holdings, performance, notes)
3. Individual Stocks (status, tax holding period, buy/sell/hold recommendation)
4. Romania Portfolio (BET ETF, bonds)
5. Romanian Tax Notes (positions >365 days, capital gains implications)
6. Global News (summarise relevant items from the digest)
7. Stock-Specific News (summarise per-ticker items from the digest)
8. Romania News (summarise Romanian items from the digest)
9. Watchlist & Alerts (stocks to watch, risks, opportunities)

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
        "max_tokens": 16000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": USER_PROMPT}],
        # web_search intentionally removed — news pre-fetched via RSS (free)
    }

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=300,
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
def save_report(html: str) -> str:
    filename = f"portfolio-analysis-{TODAY}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[{TODAY}] Report saved to {filename}")
    return filename

# ── SEND EMAIL ────────────────────────────────────────────────────────────────
def send_email(html: str, filename: str):
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
