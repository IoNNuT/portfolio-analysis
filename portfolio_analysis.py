import os
import re
import json
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
def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_articles (
            url     TEXT PRIMARY KEY,
            seen_on TEXT NOT NULL
        )
    """)
    # Store portfolio data hash to detect changes week-over-week
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_state (
            key     TEXT PRIMARY KEY,
            value   TEXT NOT NULL
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

# ── CSV COMPRESSION ───────────────────────────────────────────────────────────
def compress_csv(csv_text: str) -> str:
    """
    Remove empty columns, strip whitespace, and drop fully empty rows.
    Reduces token count by 20-30% on typical spreadsheet exports.
    """
    lines = csv_text.strip().splitlines()
    if not lines:
        return csv_text

    rows = [line.split(",") for line in lines]
    if not rows:
        return csv_text

    # Find columns that have at least one non-empty value (beyond header)
    max_cols = max(len(r) for r in rows)
    rows = [r + [""] * (max_cols - len(r)) for r in rows]  # pad short rows

    non_empty_cols = [
        i for i in range(max_cols)
        if any(rows[r][i].strip() for r in range(1, len(rows)))
    ]

    # Rebuild with only non-empty columns, strip whitespace per cell
    compressed = []
    for row in rows:
        filtered = [row[i].strip() for i in non_empty_cols]
        # Skip rows where all values are empty
        if any(filtered):
            compressed.append(",".join(filtered))

    result = "\n".join(compressed)
    print(f"  CSV compressed: {len(csv_text)} → {len(result)} chars "
          f"({100 - int(len(result)/len(csv_text)*100)}% reduction)")
    return result

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
            results.append({"label": label, "title": title, "summary": summary})
            if len(results) >= MAX_PER_FEED:
                break
        print(f"  [{label}] {len(results)} new items")
        return results
    except Exception as e:
        print(f"  Warning: [{label}] {e}")
        return []

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

    if total > MAX_ITEMS_TOTAL:
        ratio = MAX_ITEMS_TOTAL / total
        for cat in sections:
            keep = max(1, int(len(sections[cat]) * ratio))
            sections[cat] = sections[cat][:keep]
        total = sum(len(v) for v in sections.values())

    print(f"[{TODAY}] Total news items after filtering & cap: {total}")

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

# ── HAIKU: PRE-FILTER NEWS ────────────────────────────────────────────────────
def haiku_filter_news(raw_digest: str, summary_csv: str) -> str:
    """
    Use Haiku (~20x cheaper than Sonnet) to select the top 10 most relevant
    news items given the actual portfolio holdings. Returns a trimmed digest.
    Cost: ~$0.001 per run.
    """
    print(f"[{TODAY}] Running Haiku news filter...")

    prompt = f"""You are a news filter for a stock portfolio. 
    
Portfolio holdings (CSV):
{summary_csv}

Below is a news digest with multiple items. Select the 10 most relevant items 
for this specific portfolio. Return ONLY a JSON array of the selected item titles, 
nothing else, no markdown, no explanation.

News digest:
{raw_digest}"""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=60,
        )
        if response.status_code != 200:
            print(f"  Haiku filter failed ({response.status_code}), using full digest")
            return raw_digest

        data = response.json()
        text = "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")

        # Parse the JSON list of selected titles
        selected_titles = json.loads(text.strip())
        selected_set = set(t.lower() for t in selected_titles)

        # Rebuild digest keeping only selected items
        filtered_lines = []
        current_section = ""
        skip = False
        for line in raw_digest.splitlines():
            if line.startswith("## "):
                current_section = line
                filtered_lines.append(line)
                continue
            # Check if this line is a news item title
            if line.startswith("[") and "]" in line:
                title_part = line.split("] ", 1)[-1].lower()
                skip = not any(sel in title_part for sel in selected_set)
            if not skip:
                filtered_lines.append(line)

        result = "\n".join(filtered_lines)
        print(f"  Haiku filtered digest: {len(raw_digest)} → {len(result)} chars")
        return result

    except Exception as e:
        print(f"  Haiku filter error: {e}, using full digest")
        return raw_digest

# ── DETECT PORTFOLIO CHANGES ──────────────────────────────────────────────────
def portfolio_changed(conn, summary_csv: str, utilities_csv: str) -> bool:
    """
    Returns True if portfolio data changed since last run.
    Used to decide whether to do a full re-analysis or incremental.
    """
    current_hash = md5(summary_csv + utilities_csv)
    last_hash    = get_state(conn, "portfolio_hash")
    changed      = current_hash != last_hash
    set_state(conn, "portfolio_hash", current_hash)
    print(f"[{TODAY}] Portfolio data {'CHANGED' if changed else 'UNCHANGED'} since last run")
    return changed

# ── LOAD SKILL (static — will be prompt-cached by Anthropic) ─────────────────
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

print(f"[{TODAY}] Fetching portfolio data...")
summary_csv   = compress_csv(fetch_sheet_csv("1633571629", "Summary"))
utilities_csv = compress_csv(fetch_sheet_csv("2066207814", "Utilities"))

# ── FETCH & FILTER NEWS ───────────────────────────────────────────────────────
print(f"[{TODAY}] Fetching RSS feeds...")
raw_news_digest = fetch_all_news()
news_digest     = haiku_filter_news(raw_news_digest, summary_csv)

# ── DETECT CHANGES FOR INCREMENTAL MODE ──────────────────────────────────────
db_conn  = init_db()
is_full  = portfolio_changed(db_conn, summary_csv, utilities_csv)
db_conn.close()

if is_full:
    print(f"[{TODAY}] Mode: FULL analysis (portfolio changed)")
    analysis_scope = """IMPORTANT: Perform a FULL analysis — all 9 sections in detail.

1. Portfolio Overview — total value in EUR, allocation breakdown table
2. ETF Portfolio — all holdings with current allocation vs target
3. Individual Stocks — each stock: status, days held, tax rate (3%/6%), recommendation
4. Romania Portfolio — BET ETF and bonds update
5. Romanian Tax Notes — positions >365 days, estimated tax on unrealised gains
6. Global News — 3-5 items from the General Financial News digest
7. Stock-Specific News — news per ticker from the digest
8. Romania News — items from the Romania digest
9. Watchlist & Alerts — 3-5 opportunities or risks"""
else:
    print(f"[{TODAY}] Mode: INCREMENTAL analysis (portfolio unchanged)")
    analysis_scope = """The portfolio holdings are UNCHANGED from last week. 

SKIP detailed recalculation of sections 1-5 — just show a one-line summary for each 
(e.g. "Total value: €X,XXX — no change from last week").

Focus your full effort on sections 6-9 which always change weekly:
6. Global News — 3-5 items from the General Financial News digest (DETAILED)
7. Stock-Specific News — news per ticker from the digest (DETAILED)
8. Romania News — items from the Romania digest (DETAILED)
9. Watchlist & Alerts — 3-5 specific opportunities or risks based on this week's news (DETAILED)"""

# ── USER PROMPT ───────────────────────────────────────────────────────────────
USER_PROMPT = f"""Please perform a portfolio analysis for today, {TODAY}.

## Portfolio Data (live from Google Sheets)

### Summary (current holdings)
```
{summary_csv}
```

### Utilities (exchange rates)
```
{utilities_csv}
```

## News Digest (pre-fetched & filtered from RSS)
{news_digest}

---

Use the portfolio data as the source of truth for holdings, values, and exchange rates.
Use the news digest as the source of truth for all news — do NOT search the web.
Be CONCISE — use compact tables over long paragraphs.

{analysis_scope}

Return a complete, polished HTML report titled "portfolio-analysis-{TODAY}".
Fully self-contained HTML with inline CSS. Dark financial dashboard aesthetic."""

# ── SONNET: FULL REPORT ───────────────────────────────────────────────────────
def run_analysis() -> str:
    print(f"[{TODAY}] Calling Sonnet API...")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",  # enables prompt caching
        "content-type": "application/json",
    }

    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 32000,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}  # cache the static skill content
            }
        ],
        "messages": [{"role": "user", "content": USER_PROMPT}],
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

    # Log cache performance
    usage = data.get("usage", {})
    cache_read    = usage.get("cache_read_input_tokens", 0)
    cache_created = usage.get("cache_creation_input_tokens", 0)
    input_tokens  = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    print(f"[{TODAY}] Tokens — input: {input_tokens}, output: {output_tokens}, "
          f"cache_read: {cache_read}, cache_created: {cache_created}")
    if cache_read > 0:
        print(f"[{TODAY}] Prompt cache HIT — saved ~{cache_read} input tokens")

    html_report = "".join(
        block["text"] for block in data.get("content", []) if block.get("type") == "text"
    )

    if not html_report.strip():
        raise RuntimeError("Empty response from Anthropic API")

    print(f"[{TODAY}] Report length: {len(html_report)} chars")
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
    mode = "Full" if is_full else "Incremental"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Portfolio Analysis ({mode}) — {TODAY}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL

    msg.attach(MIMEText(
        f"Your weekly portfolio analysis is ready.\n\nDate: {TODAY}\nMode: {mode}\n\n"
        "Open the attached HTML file to view the full report.",
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
