# Deploying Google Apps Script with clasp

Goal: push local changes to Google Apps Script directly instead of copy-pasting.

**Status:** Setup complete. All Apps Script files live in `clasp/` and are linked to the remote project via `clasp/.clasp.json`.

## One-time setup (already done)

```bash
npm install -g @google/clasp
clasp login   # opens browser for Google auth
```

The `clasp/` directory is already cloned and linked. The script ID in `clasp/.clasp.json` points to the live Google Apps Script project.

## Daily workflow

```bash
cd clasp/
clasp push   # upload local files to Apps Script
clasp pull   # download remote changes to local
```

## Files in clasp/

| File | Purpose |
|------|---------|
| `automation.js` | Daily snapshot recording (ETF, Stocks, NetWorth) |
| `chart.js` | Server-side data functions for the web dashboard |
| `chart_page.html` | Interactive dashboard frontend |
| `Code.js` | Entry-point / utility functions |
| `debug.js` | Debug helpers |
| `appsscript.json` | Apps Script manifest |
| `.clasp.json` | Links local dir to remote script project |

## Notes

- After pushing `.gs`/`.js` files, deploy a **new Web App version** in the Apps Script editor to bust Google's cache
- HTML file changes are picked up on browser reload without redeployment
- `clasp push` overwrites the remote with local files — always pull before editing if remote changes were made in the browser
