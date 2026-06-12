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

  // Skip if all values match the last recorded row
  const lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    const last = sheet.getRange(lastRow, 2, 1, 4).getValues()[0];
    if (last[0] === totalMV && last[1] === totalInvested && last[2] === pnl && last[3] === pnlPct) return;
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

  // Skip if all values match the last recorded row
  const lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    const last = sheet.getRange(lastRow, 2, 1, 4).getValues()[0];
    if (last[0] === totalMV && last[1] === totalInvested && last[2] === pnl && last[3] === pnlPct) return;
  }

  const sp500Price = fetchCurrentSP500Price();
  sheet.appendRow([today, totalMV, totalInvested, pnl, pnlPct, sp500Price]);
}

function recordNetWorthSnapshot() {
  const ss      = SpreadsheetApp.getActiveSpreadsheet();
  const nwSheet = ss.getSheetByName("NetWorth");
  if (!waitForSheetReady(nwSheet)) {
    Logger.log("recordNetWorthSnapshot: skipped — formula errors persisted after %s retries.", RETRY_CONFIG.MAX_RETRIES);
    return;
  }

  // ── Adjust these to match your NetWorth sheet layout ──────────────────
  const TOTAL_NET_WORTH_CELL   = "B2";
  const TOTAL_ASSETS_CELL      = "B3";   // or set to null to skip
  const TOTAL_LIABILITIES_CELL = "B4";   // or set to null to skip
  // ──────────────────────────────────────────────────────────────────────

  const totalNetWorth    = nwSheet.getRange(TOTAL_NET_WORTH_CELL).getValue();
  const totalAssets      = TOTAL_ASSETS_CELL      ? nwSheet.getRange(TOTAL_ASSETS_CELL).getValue()      : null;
  const totalLiabilities = TOTAL_LIABILITIES_CELL ? nwSheet.getRange(TOTAL_LIABILITIES_CELL).getValue() : null;

  let histSheet = ss.getSheetByName("NetWorth History");
  if (!histSheet) histSheet = ss.insertSheet("NetWorth History");

  if (histSheet.getLastRow() === 0) {
    const headers = ["Date", "Net Worth (€)"];
    if (totalAssets !== null)      headers.push("Assets (€)");
    if (totalLiabilities !== null) headers.push("Liabilities (€)");
    histSheet.appendRow(headers);
  }

  const today = new Date(); today.setHours(0, 0, 0, 0);

  // Build new row values (excluding date) and compare against last recorded
  const newValues = [totalNetWorth];
  if (totalAssets !== null)      newValues.push(totalAssets);
  if (totalLiabilities !== null) newValues.push(totalLiabilities);

  const lastRow = histSheet.getLastRow();
  if (lastRow > 1) {
    const last = histSheet.getRange(lastRow, 2, 1, newValues.length).getValues()[0];
    if (newValues.every((val, i) => val === last[i])) return;
  }

  histSheet.appendRow([today, ...newValues]);
}

function recordNetWorthSnapshot() {
  const ss       = SpreadsheetApp.getActiveSpreadsheet();
  const nwSheet  = ss.getSheetByName("NetWorth");
  if (!waitForSheetReady(nwSheet)) {
    Logger.log("recordNetWorthSnapshot: skipped — formula errors persisted after %s retries.", RETRY_CONFIG.MAX_RETRIES);
    return;
  }

  // ── Adjust these to match your NetWorth sheet layout ──────────────────
  const TOTAL_NET_WORTH_CELL = "C9";   // cell that holds your total net worth (€)
  const TOTAL_ASSETS_CELL    = "";   // cell that holds total assets — or set to null to skip
  const TOTAL_LIABILITIES_CELL = ""; // cell that holds total liabilities — or set to null to skip
  // ──────────────────────────────────────────────────────────────────────

  const totalNetWorth   = nwSheet.getRange(TOTAL_NET_WORTH_CELL).getValue();
  const totalAssets     = TOTAL_ASSETS_CELL     ? nwSheet.getRange(TOTAL_ASSETS_CELL).getValue()     : null;
  const totalLiabilities = TOTAL_LIABILITIES_CELL ? nwSheet.getRange(TOTAL_LIABILITIES_CELL).getValue() : null;

  let histSheet = ss.getSheetByName("NetWorth History");
  if (!histSheet) histSheet = ss.insertSheet("NetWorth History");

  if (histSheet.getLastRow() === 0) {
    const headers = ["Date", "Net Worth (€)"];
    if (totalAssets !== null)      headers.push("Assets (€)");
    if (totalLiabilities !== null) headers.push("Liabilities (€)");
    histSheet.appendRow(headers);
  }

  // ── Skip if net worth hasn't changed since the last recorded row ───────
  const lastRow = histSheet.getLastRow();
  if (lastRow > 1) {
    const lastNetWorth = histSheet.getRange(lastRow, 2).getValue();
    if (lastNetWorth === totalNetWorth) return;
  }
  // ──────────────────────────────────────────────────────────────────────

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const row = [today, totalNetWorth];
  if (totalAssets !== null)      row.push(totalAssets);
  if (totalLiabilities !== null) row.push(totalLiabilities);

  histSheet.appendRow(row);
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