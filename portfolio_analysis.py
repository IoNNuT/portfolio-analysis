import os
import json
import datetime
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── CONFIG ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER        = os.environ["GMAIL_USER"]          # your Gmail address
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"] # Gmail App Password (not your real password)
RECIPIENT_EMAIL   = os.environ["RECIPIENT_EMAIL"]     # where to send the report (can be same as GMAIL_USER)

TODAY = datetime.date.today().strftime("%Y-%m-%d")

# ── LOAD SKILL ────────────────────────────────────────────────────────────────
skill_path = os.path.join(os.path.dirname(__file__), "SKILL.md")
with open(skill_path, "r", encoding="utf-8") as f:
    SKILL_CONTENT = f.read()

# Inject today's date into the skill content so the HTML title is always current
SYSTEM_PROMPT = SKILL_CONTENT.replace("{{TODAY}}", TODAY)

# ── FETCH GOOGLE SHEETS DATA ──────────────────────────────────────────────────
SHEET_ID = "1qbb0x_kNtIUp4cq-_O9uFi6stbcSPwTeTnXOd1DbzOo"

def fetch_sheet_csv(gid: str, name: str) -> str:
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    response = requests.get(url, timeout=30)
    if response.status_code != 200:
        print(f"[{TODAY}] Warning: could not fetch {name} sheet (status {response.status_code})")
        return f"[{name} data unavailable]"
    print(f"[{TODAY}] Fetched {name} sheet ({len(response.text)} chars)")
    return response.text

summary_csv   = fetch_sheet_csv("1633571629", "Summary")
utilities_csv = fetch_sheet_csv("2066207814", "Utilities")

# ── USER PROMPT ───────────────────────────────────────────────────────────────
USER_PROMPT = f"""Please perform a full portfolio analysis for today, {TODAY}.

Here is the live data fetched directly from my portfolio Google Sheet:

## Summary (current holdings)
```
{summary_csv}
```

## Utilities (exchange rates)
```
{utilities_csv}
```

Use this data as the source of truth for all holdings, values, and exchange rates.
Then search for current news relevant to the portfolio.

IMPORTANT: You must complete ALL of the following sections before finishing — do not stop early:
1. Portfolio Overview
2. ETF Portfolio
3. Individual Stocks
4. Romania Portfolio
5. Romanian Tax Notes
6. Global News (search for real current news)
7. Stock-Specific News (search for each holding)
8. Romania News
9. Watchlist & Alerts

Return a complete, polished HTML report with the title "portfolio-analysis-{TODAY}".
The HTML must be fully self-contained (inline CSS, no external dependencies except Google Fonts if needed).
Make it visually professional — use a dark financial dashboard aesthetic."""

# ── CALL ANTHROPIC API ────────────────────────────────────────────────────────
def run_analysis() -> str:
    print(f"[{TODAY}] Starting portfolio analysis...")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 29900,
        "system": SYSTEM_PROMPT,
        "tools": [
            {
                "type": "web_search_20250305",
                "name": "web_search"
            }
        ],
        "messages": [
            {"role": "user", "content": USER_PROMPT}
        ]
    }

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=300  # 5 min timeout — analysis can take a while
    )

    if response.status_code != 200:
        raise RuntimeError(f"Anthropic API error {response.status_code}: {response.text}")

    data = response.json()

    # Extract all text blocks from the response
    html_report = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            html_report += block["text"]

    if not html_report.strip():
        raise RuntimeError("Empty response from Anthropic API")

    print(f"[{TODAY}] Analysis complete. Report length: {len(html_report)} characters.")
    return html_report


# ── SAVE HTML LOCALLY ─────────────────────────────────────────────────────────
def save_report(html: str) -> str:
    filename = f"portfolio-analysis-{TODAY}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[{TODAY}] Report saved to {filename}")
    return filename


# ── SEND EMAIL ────────────────────────────────────────────────────────────────
def send_email(html: str, filename: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Portfolio Analysis — {TODAY}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL

    # Plain text fallback
    text_part = MIMEText(
        f"Your weekly portfolio analysis is ready.\n\nDate: {TODAY}\n\n"
        "Open the attached HTML file or enable HTML email to view the full report.",
        "plain"
    )

    # HTML body (inline in email)
    html_part = MIMEText(html, "html")

    msg.attach(text_part)
    msg.attach(html_part)

    # Also attach as a downloadable file
    attachment = MIMEText(html, "html")
    attachment.add_header(
        "Content-Disposition", "attachment", filename=filename
    )
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
    print(f"[{TODAY}] ✅ Done!")
