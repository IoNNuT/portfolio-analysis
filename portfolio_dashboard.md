# Portfolio Dashboard — What We Built

## Overview

A Google Apps Script system that automatically records daily snapshots of your investment portfolio and displays them in an interactive web dashboard. Built on top of an existing Google Sheets portfolio tracker.

---

## Part 1 — Snapshot Recording (Apps Script)

Three functions that run on a daily trigger and record the current state of each investment category into dedicated history sheets.

### Functions

#### `recordPortfolioSnapshot_v1`
Records the ETF portfolio state from the Summary sheet into **ETF History**.

#### `recordStocksSnapshot_v1`
Records the stocks portfolio state from the Summary sheet into **Stocks History**.

#### `recordNetWorthSnapshot`
Records the total net worth from the NetWorth sheet into **NetWorth History**.

### History Sheet Format

**ETF History / Stocks History**
| Date | Total MV (€) | Invested (€) | P&L (€) | P&L (%) |
|------|-------------|-------------|---------|---------|

**NetWorth History**
| Date | Net Worth (€) |
|------|--------------|

### Key Logic

- **Duplicate prevention** — before recording, each function compares all values against the last recorded row. If nothing has changed, it skips recording. This avoids redundant rows on weekends or market holidays.
- **Raw number storage** — values are stored as plain numbers, not formatted strings (e.g. `30341.48` not `€30,341.48`), so charts can read them directly.
- **Date handling** — dates are stored as Date objects with `setHours(0,0,0,0)` to normalize to midnight local time.

### Helper Function

```javascript
function toLocalDate(d) {
  const dt = new Date(d);
  return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
}
```
Used in the web app to convert Date objects to `YYYY-MM-DD` strings using local timezone, avoiding UTC offset issues (important for GMT+3 Eastern European Summer Time).

---

## Part 2 — Interactive Web Dashboard (Apps Script Web App)

A browser-based dashboard served from Apps Script that reads live data from the Google Sheet and renders interactive charts.

### Files

All Apps Script source files live in `clasp/` in this repo and are pushed to Google Apps Script via clasp CLI.

- **`clasp/chart.js`** — server-side Apps Script that exposes data to the frontend
- **`clasp/chart_page.html`** — the full frontend: HTML, CSS, and JavaScript in one file
- **`clasp/automation.js`** — daily snapshot recording functions
- **`clasp/Code.js`** — entry-point / utility functions
- **`clasp/.clasp.json`** — links the local directory to the remote Apps Script project

### Deployment

Deployed as a Google Apps Script **Web App**:
- Execute as: Me
- Who has access: Anyone (or restricted to yourself)
- Each code change requires deploying a **new version** to bust Google's cache

Push local changes to Apps Script:
```bash
cd clasp/
clasp push
```

To view updated data, simply **reload the browser tab** — no redeployment needed for data changes.

---

## Part 3 — Dashboard Features

### Tabs
Three tabs, one per investment category:
- **ETF** — reads from ETF History
- **Stocks** — reads from Stocks History
- **Net Worth** — reads from NetWorth History

### Stats Panels

**Latest Snapshot** (always shows most recent recorded values)
- Market Value, Invested, P&L, Return %

**Period Performance** (updates when range buttons are clicked)
- P&L Change, Return Change, and the date range of the selected period

### Range Buttons
| Button | Behaviour |
|--------|-----------|
| 1D | Last two recorded data points |
| 1W | Last 7 days of data |
| 1M | Last 30 days of data |
| 3M | Last 90 days of data |
| 6M | Last 180 days of data |
| 1Y | Last 365 days of data |
| ALL | Full history |

Range is calculated relative to the **last date in the data**, not today's date — so it works correctly regardless of whether dates are in the past or future.

### Chart Interactivity
- **Scroll** to zoom in/out on the X axis
- **Drag** to pan left/right
- **Double-click** to reset zoom
- **Hover** for tooltips showing exact values per day

### Chart Design
- Dark theme (`#0d0f14` background)
- ETF/Stocks: blue line (Market Value) + dashed grey line (Invested) with gradient fill
- Net Worth: purple line with gradient fill
- No data points rendered (cleaner with dense data)
- Smooth curves (`tension: 0.3`)
- Typography: Syne (headings) + DM Mono (labels, numbers)

### Libraries Used
- [Chart.js 4.4.1](https://www.chartjs.org/) — charting
- [chartjs-plugin-zoom 1.2.1](https://www.chartjs.org/chartjs-plugin-zoom/) — zoom and pan
- [Hammer.js 2.0.8](https://hammerjs.github.io/) — touch/pinch support for zoom plugin

---

## Part 4 — Weekly Analysis Library

A **Library** tab that archives every weekly analysis HTML report and lets you read past reports inside the dashboard. Everything stays private — reports live in your Drive and are served by Apps Script (which runs as you), never published publicly.

### How it works

1. **Import (`reports.js` → `importReportsFromGmail`)** — a weekly time-driven trigger searches Gmail for the analysis emails (`subject:"Portfolio Analysis"`), extracts the HTML attachment, and saves it to a Drive folder as `portfolio-analysis-{date}-{mode}.html`. Idempotent: reruns only add reports not already in the folder.
2. **List (`reports.js` → `listReports`)** — the Library tab calls this via `google.script.run`; it returns `[{id, date, mode}]` newest-first by parsing filenames in the folder.
3. **Read (`reports.js` → `getReportHtml`)** — clicking a report fetches its HTML (guarded to the reports folder) and renders it in a sandboxed `<iframe srcdoc>` in the dashboard.

### One-time setup

1. Create a Drive folder (e.g. "Portfolio Analysis Reports") and copy its ID.
2. Apps Script → **Project Settings → Script Properties** → add `REPORTS_FOLDER_ID = <folder id>`.
3. `cd clasp && clasp push`, then deploy a **new version** (adds Drive + Gmail OAuth scopes → you'll re-authorize).
4. Apps Script → **Triggers** → add a time-driven trigger for `importReportsFromGmail` running weekly on Monday (after the analysis email is sent).
5. (Optional) Run `importReportsFromGmail` once manually to backfill existing reports from the last year.

## Known Gotchas

- **Google caches Web App deployments aggressively** — always deploy a new version after changing `.gs` files. HTML changes are picked up on reload without redeployment.
- **Timezone offset** — dates stored with a time component (e.g. `18:12:54 GMT+0300`) convert incorrectly to UTC via `.toISOString()`, shifting the date back by one day. Fixed by using `toLocalDate()` which reads local date components directly.
- **Formatted strings break charts** — if values are stored as `€30,341.48` instead of `30341.48`, the chart cannot plot them. Always store raw numbers and apply sheet formatting separately.