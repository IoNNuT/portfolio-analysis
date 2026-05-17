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

## API Cost Target

**Goal: keep Claude API cost below $0.30 per portfolio analysis run.**
When suggesting changes that affect API usage (prompt size, number of calls, model choice), always evaluate the cost impact and prefer approaches that stay within this budget.

## How It Works

1. **Fetch:** Google Sheets (CSV API) → Summary, Utilities, Tranzactii sheets
2. **Compute:** FIFO tax table from transaction history
3. **Scrape:** RSS feeds (ticker-specific + macro news)
4. **Analyze:** Claude Sonnet (portfolio + news context)
5. **Render:** Claude Haiku converts analysis to HTML
6. **Distribute:** Email report + GitHub artifact

## Mode Switching

- **FULL mode:** Holdings changed → full analysis of portfolio sections
- **INCREMENTAL mode:** Holdings unchanged → skip holdings, focus on news & opportunities

## Environment Variables

```
ANTHROPIC_API_KEY           # Claude API
GMAIL_USER, GMAIL_APP_PASSWORD  # Gmail SMTP
RECIPIENT_EMAIL             # Report recipient
DASHBOARD_URL               # Link to interactive dashboard
```

## Google Sheets

**Sheet ID:** `1qbb0x_kNtIUp4cq-_O9uFi6stbcSPwTeTnXOd1DbzOo`

- **Summary** (gid=1633571629) — Current holdings
- **Utilities** (gid=2066207814) — FX rates
- **Tranzactii** (gid=1445112517) — Buy/sell history

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
- **RSS feeds:** Static (MarketWatch, CNBC, CoinDesk, Decrypt, Profit.ro) + per-ticker Yahoo Finance
