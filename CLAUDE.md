# Portfolio Analysis System

**Overall Purpose:** Multi-component system combining weekly AI-driven portfolio analysis with daily interactive dashboards.

This repo contains the **weekly analysis script**. It runs Mondays 10 AM, analyzes holdings + news, sends email report.

**External component:** Google Apps Script web app (separate) records daily snapshots and displays interactive charts. Dashboard link is included in the email report.

---

## This Repo: Weekly Analysis Script

**Purpose:** Fetches holdings from Google Sheets, analyzes with Claude, sends email report.

## Files

| File | Purpose |
|------|---------|
| `portfolio_analysis.py` | Main script: fetch data → analyze → render HTML → send email |
| `SKILL.md` | Investor profile, portfolio rules, tax rules |
| `.github/workflows/portfolio_analysis.yml` | GitHub Actions cron: runs Mondays 08:00 UTC |
| `seen_articles.db` | SQLite cache of article URLs (prevents duplicates across weekly runs) |
| `parse_broker_csv.py` | Parses broker CSV exports (XTB, TradeVille, ING) and stores transactions in SQLite. **Not currently wired into the report** — see Investment Income below |
| `clasp/` | Google Apps Script source files, managed with clasp CLI |
| `clasp/automation.js` | Daily portfolio snapshot recording (ETF, Stocks, NetWorth history sheets) |
| `clasp/chart.js` | Server-side Apps Script exposing data to the web dashboard |
| `clasp/chart_page.html` | Interactive web dashboard frontend (Chart.js, dark theme, zoom/pan) + Library tab |
| `clasp/reports.js` | Weekly Analysis Library: Gmail→Drive importer + dashboard read API (listReports/getReportHtml) |
| `utils/taxes/<year>/` | Per-year broker CSV exports and `investment_income.db` SQLite database. Stalled at 2026 Q1 |

## API Cost Target

**Goal: keep Claude API cost below $0.30 per portfolio analysis run.**
When suggesting changes that affect API usage (prompt size, number of calls, model choice), always evaluate the cost impact and prefer approaches that stay within this budget.

## How It Works

1. **Fetch:** Google Sheets (CSV API) → Summary, Utilities, Tranzactii sheets
2. **Compute:** FIFO tax table from transaction history
3. **Scrape:** RSS feeds (ticker-specific + macro news) + S&P 500 weekly performance via Yahoo Finance
4. **Newsletters:** Pull subscribed newsletters from iCloud Mail (IMAP, by sender), dedup against
   the article cache, then Haiku-distill each into ~5 portfolio-relevant bullets. Folded into the
   Global News, per-stock Section 2 rationale, and Watchlist sections — no separate report section. Optional: skipped silently
   if iCloud creds are absent. See `NEWSLETTER_SENDERS` / `fetch_newsletters`.
5. **Analyze:** Claude Sonnet (portfolio + news + newsletter context, includes weekly ETF vs S&P 500 comparison)
6. **Render:** Claude Haiku converts analysis to HTML
7. **Distribute:** Email report + GitHub artifact

## Report Sections

The report is **6 sections**, pinned to `report_template.html`: 1. Portfolio Overview,
2. Individual Stocks, 3. Global News, 4. Romania News, 5. Crypto / Bitcoin,
6. Watchlist & Action Items. The count is asserted in three places that must stay in
sync: both `analysis_scope` prompts, the Haiku "Keep the same N sections" rule, and the
template's `<h2>` numbering.

### Investment Income (removed 2026-07-26)

A 7th section, "Investment Income YTD", was dropped because the XTB / TradeVille / ING
CSV exports feeding `investment_income.db` are no longer being added, leaving the YTD
figures stale at 2026 Q1. `parse_broker_csv.py`, `utils/taxes/` and
`load_income_summary()` are all kept intact — restoring the section means re-importing
the CSVs and re-wiring the call sites listed in the comment above
`load_income_summary()`. Note this is unrelated to the **FIFO tax table**, which reads
the Google Sheets `TX_SHEETS` tabs and is still live.

## Mode Switching

- **FULL mode:** Holdings changed → full analysis of portfolio sections
- **INCREMENTAL mode:** Holdings unchanged → skip holdings, focus on news & opportunities

## Environment Variables

```
ANTHROPIC_API_KEY           # Claude API
GMAIL_USER, GMAIL_APP_PASSWORD  # Gmail SMTP
RECIPIENT_EMAIL             # Report recipient
DASHBOARD_URL               # Link to interactive dashboard
ICLOUD_EMAIL, ICLOUD_APP_PASSWORD  # iCloud IMAP for newsletters (optional; app-specific password). Needs imap-tools.
```

## Google Sheets

**Sheet ID:** `1qbb0x_kNtIUp4cq-_O9uFi6stbcSPwTeTnXOd1DbzOo`

- **Summary** (gid=1633571629) — Current holdings
- **Utilities** (gid=2066207814) — FX rates
- **Transaction tabs** — clean per-portfolio buy/sell ledgers feeding the FIFO tax table.
  Header on row 1: `Date | Ticker | Price | Transaction | Shares | Amount`; dates are US M/D/Y.
  Configured in `TX_SHEETS` (tab name → gid), unioned together. Currently: `TXs_USD`
  (Stocks, gid=1053431702), `TXs_ETF` (ETF, gid=1595916700), and `TXs_RON`
  (TradeVille, gid=903718253).
  Replaces the old multi-block `Tranzactii` dashboard tab, which was unparseable (headers
  on row 6, duplicated side-by-side blocks).

## Run Manually

```bash
export ANTHROPIC_API_KEY=sk-...
export GMAIL_USER=...
export GMAIL_APP_PASSWORD=...
export RECIPIENT_EMAIL=...
export DASHBOARD_URL=...
python portfolio_analysis.py
```

## Key Logic

- **Change detection:** Hashes ticker:shares pairs only (ignores daily price/FX moves)
- **FIFO tax:** Matches sells against oldest buy lots; outputs long/short share splits
- **Article dedup:** Skips URLs seen in last 14 days
- **RSS feeds:** Static (MarketWatch, CNBC, NYT Business/Economy/Technology/US/World, CoinDesk, Decrypt, Profit.ro, GNews-RO) + per-ticker Yahoo Finance. NYT feeds use the `/services/xml/rss/nyt/` path (the old `/nf/` path was retired and 404s).
