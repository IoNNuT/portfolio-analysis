// ─────────────────────────────────────────────
// CONFIG — column header names used in your tables
// Only change these if you rename the columns.
// ─────────────────────────────────────────────
//test
const CONFIG = {
  MV_HEADER:         "MV",
  INVESTED_HEADER:   "Invested",
  TTL_RETURN_HEADER: "TTL Return (Abs)",  // price gain + dividends (footer)
};

// ─────────────────────────────────────────────
// IMPORTDATA retry config
// ─────────────────────────────────────────────
const RETRY_CONFIG = {
  MAX_RETRIES: 5,
  WAIT_MS:     4000,  // ms between attempts
};

// Returns true if a cell value is a formula error (e.g. #N/A, #VALUE!, #ERROR!).
function isErrorValue(value) {
  return value instanceof Error ||
         (typeof value === "string" && /^#/.test(value));
}

// Flushes recalculation and checks every cell in the sheet for errors.
// Retries up to MAX_RETRIES times, sleeping WAIT_MS between each.
// Returns true when the sheet is clean, false if errors persist after all retries.
function waitForSheetReady(sheet) {
  for (let attempt = 1; attempt <= RETRY_CONFIG.MAX_RETRIES; attempt++) {
    SpreadsheetApp.flush();
    const values = sheet.getDataRange().getValues();
    const hasError = values.some(row => row.some(cell => isErrorValue(cell)));
    if (!hasError) return true;
    Logger.log(
      "waitForSheetReady [%s] attempt %s/%s: formula errors detected, waiting %sms…",
      sheet.getName(), attempt, RETRY_CONFIG.MAX_RETRIES, RETRY_CONFIG.WAIT_MS
    );
    if (attempt < RETRY_CONFIG.MAX_RETRIES) Utilities.sleep(RETRY_CONFIG.WAIT_MS);
  }
  return false;
}

// ─────────────────────────────────────────────
// Helper: scans the Summary sheet for all tables
// that have an MV and Invested column, then reads
// the footer (last non-empty row) of the Nth one.
//
// tableIndex: 0 = ETFs (first table), 1 = Stocks (second table)
// ─────────────────────────────────────────────
function getTotalsFromTable(sheet, tableIndex) {
  const data = sheet.getDataRange().getValues();

  // Find every header row that contains both MV and Invested columns
  const tables = [];
  data.forEach((row, i) => {
    const mvIdx = row.indexOf(CONFIG.MV_HEADER);
    const investedIdx = row.indexOf(CONFIG.INVESTED_HEADER);
    if (mvIdx !== -1 && investedIdx !== -1) {
      tables.push({ headerRow: i, mvIdx, investedIdx, ttlReturnIdx: row.indexOf(CONFIG.TTL_RETURN_HEADER) });
    }
  });

  if (tableIndex >= tables.length) {
    throw new Error(
      `Table index ${tableIndex} not found — only ${tables.length} table(s) with` +
      ` "${CONFIG.MV_HEADER}" and "${CONFIG.INVESTED_HEADER}" columns detected.`
    );
  }

  const { headerRow, mvIdx, investedIdx, ttlReturnIdx } = tables[tableIndex];

  // The table ends just before the next table's header row (or end of data)
  const nextHeader = tableIndex + 1 < tables.length
    ? tables[tableIndex + 1].headerRow
    : data.length;

  // Walk backwards from the boundary to find the last row with an MV value (= footer)
  let footerRow = -1;
  for (let i = nextHeader - 1; i > headerRow; i--) {
    if (data[i][mvIdx] !== "" && data[i][mvIdx] !== null) {
      footerRow = i;
      break;
    }
  }

  if (footerRow === -1) {
    throw new Error(`Could not find footer row for table ${tableIndex}.`);
  }

  return {
    totalMV:         data[footerRow][mvIdx],
    totalInvested:   data[footerRow][investedIdx],
    totalTtlReturn:  ttlReturnIdx !== -1 ? data[footerRow][ttlReturnIdx] : null,
  };
}

// ─────────────────────────────────────────────
// Run this anytime to verify the script is
// reading the right values. Check the execution log.
// ─────────────────────────────────────────────
function verifyTotals() {
  const summary = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Summary");
  const etf    = getTotalsFromTable(summary, 0);
  const stocks = getTotalsFromTable(summary, 1);
  Logger.log("ETF    — MV: %s | Invested: %s", etf.totalMV,    etf.totalInvested);
  Logger.log("Stocks — MV: %s | Invested: %s", stocks.totalMV, stocks.totalInvested);
}

// ─────────────────────────────────────────────
// Daily snapshot functions (triggered automatically)
// ─────────────────────────────────────────────
// function recordPortfolioSnapshot_v1() {
//   const ss      = SpreadsheetApp.getActiveSpreadsheet();
//   const summary = ss.getSheetByName("Summary");
//   const { totalMV, totalInvested } = getTotalsFromTable(summary, 0);

//   let sheet = ss.getSheetByName("ETF History");
//   if (!sheet) sheet = ss.insertSheet("ETF History");
//   if (sheet.getLastRow() === 0) {
//     sheet.appendRow(["Date", "Total MV (€)", "Invested (€)", "P&L (€)", "P&L (%)"]);
//   }

//   const today  = new Date(); today.setHours(0, 0, 0, 0);
//   const pnl    = totalMV - totalInvested;
//   const pnlPct = pnl / totalInvested;
//   sheet.appendRow([today, totalMV, totalInvested, pnl, pnlPct]);
// }

// function recordStocksSnapshot_v1() {
//   const ss      = SpreadsheetApp.getActiveSpreadsheet();
//   const summary = ss.getSheetByName("Summary");
//   const { totalMV, totalInvested } = getTotalsFromTable(summary, 1);

//   let sheet = ss.getSheetByName("Stocks History");
//   if (!sheet) sheet = ss.insertSheet("Stocks History");
//   if (sheet.getLastRow() === 0) {
//     sheet.appendRow(["Date", "Total MV (€)", "Invested (€)", "P&L (€)", "P&L (%)"]);
//   }

//   const today  = new Date(); today.setHours(0, 0, 0, 0);
//   const pnl    = totalMV - totalInvested;
//   const pnlPct = pnl / totalInvested;
//   sheet.appendRow([today, totalMV, totalInvested, pnl, pnlPct]);
// }

function recordPortfolioSnapshot_v1() {
  const ss      = SpreadsheetApp.getActiveSpreadsheet();
  const summary = ss.getSheetByName("Summary");
  if (!waitForSheetReady(summary)) {
    Logger.log("recordPortfolioSnapshot_v1: skipped — formula errors persisted after %s retries.", RETRY_CONFIG.MAX_RETRIES);
    return;
  }
  const { totalMV, totalInvested, totalTtlReturn } = getTotalsFromTable(summary, 0);

  let sheet = ss.getSheetByName("ETF History");
  if (!sheet) sheet = ss.insertSheet("ETF History");
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["Date", "Total MV (€)", "Invested (€)", "P&L (€)", "P&L (%)", "S&P 500"]);
  } else if (!sheet.getRange(1, 6).getValue()) {
    sheet.getRange(1, 6).setValue("S&P 500");
  }

  const today  = new Date(); today.setHours(0, 0, 0, 0);
  // P&L includes dividends (TTL Return); MV stays holdings-only. Falls back to
  // price-only P&L if the TTL Return column isn't present.
  const pnl    = totalTtlReturn != null ? totalTtlReturn : totalMV - totalInvested;
  const pnlPct = pnl / totalInvested;

  // One row per day, keyed on the date — NOT on the values.
  //
  // The old guard skipped the append whenever all four values equalled the previous
  // row. US stock values jitter by cents even when the market is shut, so Stocks
  // History never hit it; the .DE ETF quotes are byte-identical whenever XETRA is
  // closed, so ETF History lost every Saturday (and any day the quotes hadn't moved)
  // between 2026-07-11 and 2026-09-03. A flat day is real information here, and the
  // dashboard drew a straight line across the holes as if it were one continuous move.
  const lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    const lastDate = new Date(sheet.getRange(lastRow, 1).getValue());
    lastDate.setHours(0, 0, 0, 0);
    if (lastDate.getTime() === today.getTime()) {
      Logger.log("recordPortfolioSnapshot_v1: skipped — %s is already recorded.", today.toDateString());
      return;
    }
    // Identical values are legitimate on a closed day, but on a trading day they mean
    // the GOOGLEFINANCE cells never refreshed (flush() recalculates, it does not refetch).
    // Record the row either way and leave a breadcrumb rather than silently dropping it.
    const last = sheet.getRange(lastRow, 2, 1, 4).getValues()[0];
    if (last[0] === totalMV && last[1] === totalInvested && last[2] === pnl && last[3] === pnlPct) {
      Logger.log("recordPortfolioSnapshot_v1: values identical to %s — recording anyway (market closed, or quotes stale).",
        lastDate.toDateString());
    }
  }

  const sp500Price = fetchCurrentSP500Price();
  sheet.appendRow([today, totalMV, totalInvested, pnl, pnlPct, sp500Price]);
}

function recordStocksSnapshot_v1() {
  const ss      = SpreadsheetApp.getActiveSpreadsheet();
  const summary = ss.getSheetByName("Summary");
  if (!waitForSheetReady(summary)) {
    Logger.log("recordStocksSnapshot_v1: skipped — formula errors persisted after %s retries.", RETRY_CONFIG.MAX_RETRIES);
    return;
  }
  const { totalMV, totalInvested } = getTotalsFromTable(summary, 1);

  let sheet = ss.getSheetByName("Stocks History");
  if (!sheet) sheet = ss.insertSheet("Stocks History");
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["Date", "Total MV (€)", "Invested (€)", "P&L (€)", "P&L (%)", "S&P 500"]);
  } else if (!sheet.getRange(1, 6).getValue()) {
    sheet.getRange(1, 6).setValue("S&P 500");
  }

  const today  = new Date(); today.setHours(0, 0, 0, 0);
  const pnl    = totalMV - totalInvested;
  const pnlPct = pnl / totalInvested;

  // One row per day, keyed on the date — same rule as recordPortfolioSnapshot_v1
  // (see the comment there). The old value-equality skip could silently drop a
  // day whenever the four totals happened to match the previous row.
  const lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    const lastDate = new Date(sheet.getRange(lastRow, 1).getValue());
    lastDate.setHours(0, 0, 0, 0);
    if (lastDate.getTime() === today.getTime()) {
      Logger.log("recordStocksSnapshot_v1: skipped — %s is already recorded.", today.toDateString());
      return;
    }
    const last = sheet.getRange(lastRow, 2, 1, 4).getValues()[0];
    if (last[0] === totalMV && last[1] === totalInvested && last[2] === pnl && last[3] === pnlPct) {
      Logger.log("recordStocksSnapshot_v1: values identical to %s — recording anyway (market closed, or quotes stale).",
        lastDate.toDateString());
    }
  }

  const sp500Price = fetchCurrentSP500Price();
  sheet.appendRow([today, totalMV, totalInvested, pnl, pnlPct, sp500Price]);
}

// ─────────────────────────────────────────────
// Net worth = Accounts tab (bank accounts, deposits, property) + the
// allocation tab total (ETFs, stocks, BET, RO bonds — live prices).
// Replaces the old hand-maintained "NetWorth" sheet.
//
// Accounts layout: header row 1 with "Account", "Type" and "EUR value"
// columns; rows end at the footer whose Account is "Total". Rows are bucketed
// by Type: Depozit/Deposit → deposits, Property/Proprietate → property (a
// blank Type falls back to the Account name, so "Proprietati" still counts as
// property), anything else → cash.
// ─────────────────────────────────────────────
const ACCOUNTS_SHEET = "Accounts";
const ALLOCATION_GID = 1124476629;
const DEPOSIT_RE     = /depozit|deposit/i;
const PROPERTY_RE    = /propr|property|real estate|imobil/i;

function _readAccountsTotals_(sheet) {
  const data   = sheet.getDataRange().getValues();
  const header = data[0].map(h => String(h).trim().toLowerCase());
  const idxAcc  = header.indexOf("account");
  const idxType = header.indexOf("type");
  const idxEur  = header.indexOf("eur value");
  if (idxAcc === -1 || idxType === -1 || idxEur === -1) {
    throw new Error('Accounts: header needs "Account", "Type" and "EUR value" columns');
  }

  const totals = { cash: 0, deposits: 0, property: 0 };
  for (let i = 1; i < data.length; i++) {
    const acc = String(data[i][idxAcc]).trim();
    if (/^total$/i.test(acc)) break;
    if (!acc) continue;

    const eur = data[i][idxEur];
    if (eur === "" || eur === null) continue;
    if (typeof eur !== "number") {
      throw new Error('Accounts row ' + (i + 1) + ' ("' + acc + '"): EUR value is not a number: ' + eur);
    }

    const type = String(data[i][idxType]).trim() || acc;
    if (DEPOSIT_RE.test(type))       totals.deposits += eur;
    else if (PROPERTY_RE.test(type)) totals.property += eur;
    else                             totals.cash     += eur;
  }
  return totals;
}

function recordNetWorthSnapshot() {
  const ss       = SpreadsheetApp.getActiveSpreadsheet();
  const accounts = ss.getSheetByName(ACCOUNTS_SHEET);
  const alloc    = _sheetByGid_(ss, ALLOCATION_GID);
  if (!accounts) throw new Error('recordNetWorthSnapshot: "' + ACCOUNTS_SHEET + '" sheet not found');
  if (!alloc)    throw new Error("recordNetWorthSnapshot: allocation tab (gid " + ALLOCATION_GID + ") not found");

  if (!waitForSheetReady(accounts) || !waitForSheetReady(alloc)) {
    Logger.log("recordNetWorthSnapshot: skipped — formula errors persisted after %s retries.", RETRY_CONFIG.MAX_RETRIES);
    return;
  }

  const acc         = _readAccountsTotals_(accounts);
  const investments = getPortfolioStatus().total;  // chart.js — allocation tab "Total" row
  const round2      = v => Math.round(v * 100) / 100;

  const newValues = [
    acc.cash + acc.deposits + acc.property + investments,
    acc.cash, acc.deposits, investments, acc.property,
  ].map(round2);

  let histSheet = ss.getSheetByName("NetWorth History");
  if (!histSheet) histSheet = ss.insertSheet("NetWorth History");

  // Rows recorded before 2026-10-11 only have Date + Net Worth; the breakdown
  // columns are added on first run and stay blank for those older rows.
  const headers = ["Date", "Net Worth (€)", "Cash (€)", "Deposits (€)", "Investments (€)", "Property (€)"];
  histSheet.getRange(1, 1, 1, headers.length).setValues([headers]);

  // Skip if nothing changed since the last recorded row (weekends, holidays)
  const lastRow = histSheet.getLastRow();
  if (lastRow > 1) {
    const last = histSheet.getRange(lastRow, 2, 1, newValues.length).getValues()[0];
    if (newValues.every((val, i) => val === last[i])) return;
  }

  const today = new Date(); today.setHours(0, 0, 0, 0);
  histSheet.appendRow([today, ...newValues]);
}

// Run manually from the editor to check the numbers before trusting the trigger.
function verifyNetWorth() {
  const ss  = SpreadsheetApp.getActiveSpreadsheet();
  const acc = _readAccountsTotals_(ss.getSheetByName(ACCOUNTS_SHEET));
  const inv = getPortfolioStatus().total;
  Logger.log("Cash %s | Deposits %s | Property %s | Investments %s | Net worth %s",
    acc.cash, acc.deposits, acc.property, inv, acc.cash + acc.deposits + acc.property + inv);
}

// ─────────────────────────────────────────────
// S&P 500 helpers
// ─────────────────────────────────────────────

function _fetchSP500PriceMap_(fromDate, toDate) {
  const period1 = Math.floor(fromDate.getTime() / 1000) - 86400;
  const period2 = Math.floor(toDate.getTime()   / 1000) + 86400;
  const url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=1d&period1=" + period1 + "&period2=" + period2;
  const resp = UrlFetchApp.fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0 (compatible; GAS/1.0)" },
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() !== 200) {
    throw new Error("Yahoo Finance HTTP " + resp.getResponseCode());
  }
  const result = JSON.parse(resp.getContentText());
  const chart  = result.chart.result[0];
  const ts     = chart.timestamp;
  const closes = chart.indicators.quote[0].close;
  const map    = new Map();
  ts.forEach(function(t, i) {
    if (closes[i] == null) return;
    // NYSE opens at 14:30 UTC — timestamp falls on the same UTC calendar day as the trading date
    map.set(new Date(t * 1000).toISOString().split("T")[0], closes[i]);
  });
  return map;
}

function _lookupSP500_(priceMap, dateStr) {
  if (priceMap.has(dateStr)) return priceMap.get(dateStr);
  // Fall back to last available trading day (weekends / holidays)
  const d = new Date(dateStr + "T12:00:00Z");
  for (let i = 1; i <= 5; i++) {
    d.setUTCDate(d.getUTCDate() - 1);
    const prev = d.toISOString().split("T")[0];
    if (priceMap.has(prev)) return priceMap.get(prev);
  }
  return null;
}

function fetchCurrentSP500Price() {
  try {
    const now  = new Date();
    const from = new Date(now.getTime() - 7 * 86400 * 1000);
    const map  = _fetchSP500PriceMap_(from, now);
    if (map.size === 0) return null;
    const sorted = Array.from(map.entries()).sort(function(a, b) { return a[0] > b[0] ? -1 : 1; });
    return sorted[0][1];
  } catch (e) {
    Logger.log("fetchCurrentSP500Price error: " + e);
    return null;
  }
}

// ─────────────────────────────────────────────
// One-time backfill: restores the nine ETF History rows that the old
// value-equality guard dropped between 2026-07-11 and 2026-09-03.
// Run once from the editor, then run backfillSP500() to fill column F.
//
// Provenance of each row — no value here is invented:
//   • The six Saturdays carry the preceding Friday's row forward verbatim. XETRA
//     was closed, so the portfolio value genuinely did not change; that is exactly
//     why the old guard suppressed them.
//   • 2026-08-19 and 2026-09-01 are recomputed from XETRA daily closes × the share
//     counts held on those dates. The same computation reproduces the seven
//     surviving rows from 08-18 onward to the cent (worst case €0.18 on 08-31),
//     which is what makes it trustworthy here.
//   • 2026-09-03 is the one soft figure: Yahoo has no daily bar for any of the
//     seven listings that day (though XETRA traded — the DAX and SAP.DE both have
//     one), so it comes from the last hourly bar instead. That method reproduces
//     09-02 to within €1.95 of €36,965.81, so treat 09-03 as ±€2, not exact.
//
// P&L carries the constant €125.58 of received ETF distributions, matching the
// "TTL Return (Abs)" offset on every surviving row in this window.
// ─────────────────────────────────────────────
const ETF_BACKFILL_ROWS = [
  // [date, Total MV (€), Invested (€), P&L (€)]
  ["2026-07-11", 34474.47, 29209.18, 5390.87],  // carry-forward from Fri 07-10
  ["2026-07-18", 34306.23, 29209.18, 5222.63],  // carry-forward from Fri 07-17
  ["2026-07-25", 35468.86, 30153.91, 5440.53],  // carry-forward from Fri 07-24
  ["2026-08-01", 35884.94, 30867.20, 5143.32],  // carry-forward from Fri 07-31
  ["2026-08-08", 36645.16, 30867.20, 5903.54],  // carry-forward from Fri 08-07
  ["2026-08-15", 36747.13, 30867.20, 6005.51],  // carry-forward from Fri 08-14
  ["2026-08-19", 37148.66, 31721.07, 5553.17],  // recomputed from daily closes
  ["2026-09-01", 36997.92, 31721.07, 5402.43],  // recomputed from daily closes
  ["2026-09-03", 37197.79, 31721.07, 5602.30],  // recomputed from hourly closes (±€2)
];

function backfillMissingETFSnapshots() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("ETF History");
  if (!sheet) throw new Error("backfillMissingETFSnapshots: \"ETF History\" not found");

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) throw new Error("backfillMissingETFSnapshots: sheet has no data rows");

  // Index the dates already present so the function is safe to run twice
  const present = {};
  sheet.getRange(2, 1, lastRow - 1, 1).getValues().forEach(function (r) {
    if (!r[0]) return;
    const d = new Date(r[0]); d.setHours(0, 0, 0, 0);
    present[d.getTime()] = true;
  });

  const toAdd = [];
  ETF_BACKFILL_ROWS.forEach(function (row) {
    const p = row[0].split("-");
    const d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    d.setHours(0, 0, 0, 0);
    if (present[d.getTime()]) {
      Logger.log("backfillMissingETFSnapshots: %s already present — skipping", row[0]);
      return;
    }
    toAdd.push([d, row[1], row[2], row[3], row[3] / row[2]]);
  });

  if (!toAdd.length) { Logger.log("backfillMissingETFSnapshots: nothing to add"); return; }

  // Append, then re-sort the whole block so the new rows land in date order
  sheet.getRange(sheet.getLastRow() + 1, 1, toAdd.length, 5).setValues(toAdd);
  sheet.getRange(2, 1, sheet.getLastRow() - 1, sheet.getLastColumn())
       .sort({ column: 1, ascending: true });

  Logger.log("backfillMissingETFSnapshots: added %s row(s). Now run backfillSP500() to fill column F.",
    toAdd.length);
}

// ─────────────────────────────────────────────
// One-time backfill: adds "S&P 500" column to all
// existing rows in ETF History and Stocks History.
// Run once manually from the Apps Script editor.
// ─────────────────────────────────────────────
function backfillSP500() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ["ETF History", "Stocks History"].forEach(function(name) { _backfillSheet_(ss, name); });
}

function _backfillSheet_(ss, sheetName) {
  const sheet = ss.getSheetByName(sheetName);
  if (!sheet) { Logger.log("_backfillSheet_: \"" + sheetName + "\" not found"); return; }

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) { Logger.log("_backfillSheet_: \"" + sheetName + "\" has no data rows"); return; }

  if (!sheet.getRange(1, 6).getValue()) sheet.getRange(1, 6).setValue("S&P 500");

  const dateVals  = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
  const sp500Vals = sheet.getRange(2, 6, lastRow - 1, 1).getValues();

  // Determine date range of rows that still need filling
  let minDate = null, maxDate = null;
  dateVals.forEach(function(row, i) {
    if (sp500Vals[i][0] !== "" && sp500Vals[i][0] !== null) return;
    const d = new Date(row[0]); d.setHours(0, 0, 0, 0);
    if (!minDate || d < minDate) minDate = new Date(d);
    if (!maxDate || d > maxDate) maxDate = new Date(d);
  });

  if (!minDate) { Logger.log("_backfillSheet_: \"" + sheetName + "\" already fully backfilled"); return; }

  Logger.log("_backfillSheet_: fetching S&P 500 for \"" + sheetName + "\" " +
    minDate.toISOString().split("T")[0] + " → " + maxDate.toISOString().split("T")[0]);

  const priceMap = _fetchSP500PriceMap_(minDate, maxDate);
  Logger.log("_backfillSheet_: " + priceMap.size + " trading days retrieved");

  let filled = 0, missing = 0;
  for (let i = 0; i < dateVals.length; i++) {
    if (sp500Vals[i][0] !== "" && sp500Vals[i][0] !== null) continue;
    const d = new Date(dateVals[i][0]);
    // Use local date (matches how Sheets stores dates in the spreadsheet timezone)
    const dateStr = d.getFullYear() + "-" +
      String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
    const price = _lookupSP500_(priceMap, dateStr);
    if (price !== null) { sp500Vals[i][0] = price; filled++; }
    else { missing++; Logger.log("_backfillSheet_: no price found for " + dateStr); }
  }

  sheet.getRange(2, 6, lastRow - 1, 1).setValues(sp500Vals);
  Logger.log("_backfillSheet_: \"" + sheetName + "\" done — filled=" + filled + " missing=" + missing);
}