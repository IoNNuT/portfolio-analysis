# Deploying Google Apps Script with clasp

Goal: push local changes to Google Apps Script directly instead of copy-pasting.

## One-time setup

```bash
npm install -g @google/clasp
clasp login   # opens browser for Google auth
```

Link to the existing Apps Script project from the external_scripts/ directory:

```bash
cd external_scripts/
clasp clone <your-script-id>   # creates .clasp.json + pulls current remote files
```

Get the script ID from the Apps Script editor URL:
`https://script.google.com/d/<SCRIPT_ID>/edit`

## Daily workflow

```bash
clasp push   # upload local .gs files to Apps Script
clasp pull   # download remote changes to local
```

## Caveats before first run

- Back up the current snapshots.gs before running `clasp clone`
- `clasp clone` pulls remote files and generates an appsscript.json manifest — reconcile any differences with the local version
- After cloning, `clasp push` will overwrite the remote with whatever is in external_scripts/
