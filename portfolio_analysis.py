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

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1qbb0x_kNtIUp4cq-_O9uFi6stbcSPwTeTnXOd1DbzOo/edit?usp=sharing"
TODAY = datetime.date.today().strftime("%Y-%m-%d")

# ── SYSTEM PROMPT ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a personal financial analyst assistant. You will perform a detailed 
portfolio analysis for a 29-year-old investor based in Bucharest, Romania.

Romanian Fiscal Code context:
- Dividends/gains must be declared in "Declaratia Unica" even if the broker pays taxes on behalf of the user.
- Tax on capital gains: 3% for positions held > 365 days, 6% for positions held < 365 days.
- The investor uses Romanian brokers or brokers with offices in Romania (XTB, TradeVille).

Portfolio structure:
1. ETFs portfolio (EUR, XTB broker): 30% S&P 500, 20% STOXX Europe 600, 15% Global REIT, 10% Canada, 10% EM, 10% Bonds, 5% Small Cap. Monthly investment of 1k-2k EUR. Long-term hold (10-15 years).
2. Individual stocks (USD, XTB broker): Wants to SELL PTC, OSPN, OTEX, LULU (after 365 days for tax reasons). Wants to HOLD/GROW AMZN, ADBE. Focus on growth, no dividends preferred.
3. Romania portfolio (RON, TradeVille): 250 RON/month in BET ETF. Romanian Government Bonds as inflation hedge.

Rules:
- Main currency is EURO. Pay close attention to EUR/USD/RON conversions.
- Individual stocks: focus on US market only.
- The portfolio Google Sheet has sheets: Summary, Tranzactii (transactions with dates), Utilities (exchange rates).
- Output must be a COMPLETE, SELF-CONTAINED HTML document.
- The HTML title must be: portfolio-analysis-""" + TODAY + """

Your analysis must include:
1. Portfolio overview with current holdings and total value in EUR
2. Tax considerations (which positions are >365 days, capital gains implications)
3. Global news summary affecting the portfolio (with links)
4. Stock-specific news for holdings
5. Romanian political/economic news
6. Forecast and recommendations
7. Watchlist: stocks to consider buying or warning about existing holdings

Use web search to find current news and prices. Be specific, data-driven, and actionable."""

# ── USER PROMPT ───────────────────────────────────────────────────────────────
USER_PROMPT = f"""Please perform a full portfolio analysis for today, {TODAY}.

The portfolio data is in this Google Sheet (publicly accessible, no login required):
{SPREADSHEET_URL}

Access the sheet directly to read:
- The "Summary" sheet for current holdings
- The "Tranzactii" sheet for transaction history and position dates
- The "Utilities" sheet for exchange rates

Then search for current news relevant to the portfolio. 

Return a complete, polished HTML report with the title "portfolio-analysis-{TODAY}".
The HTML must be fully self-contained (inline CSS, no external dependencies except Google Fonts if needed).
Make it visually professional — use a dark financial dashboard aesthetic."""

# ── CALL ANTHROPIC API ────────────────────────────────────────────────────────
def run_analysis() -> str:
    print(f"[{TODAY}] Starting portfolio analysis...")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "interleaved-thinking-2025-05-14",
        "content-type": "application/json",
    }

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 16000,
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
