// ─────────────────────────────────────────────
// CONFIG — column header names used in your tables
// Only change these if you rename the columns.
// ─────────────────────────────────────────────
const CONFIG = {
  MV_HEADER:       "MV",
  INVESTED_HEADER: "Invested",
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
      tables.push({ headerRow: i, mvIdx, investedIdx });
    }
  });

  if (tableIndex >= tables.length) {
    throw new Error(
      `Table index ${tableIndex} not found — only ${tables.length} table(s) with` +
      ` "${CONFIG.MV_HEADER}" and "${CONFIG.INVESTED_HEADER}" columns detected.`
    );
  }

  const { headerRow, mvIdx, investedIdx } = tables[tableIndex];

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
    totalMV:       data[footerRow][mvIdx],
    totalInvested: data[footerRow][investedIdx],
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
  const { totalMV, totalInvested } = getTotalsFromTable(summary, 0);

  let sheet = ss.getSheetByName("ETF History");
  if (!sheet) sheet = ss.insertSheet("ETF History");
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["Date", "Total MV (€)", "Invested (€)", "P&L (€)", "P&L (%)"]);
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

  sheet.appendRow([today, totalMV, totalInvested, pnl, pnlPct]);
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
    sheet.appendRow(["Date", "Total MV (€)", "Invested (€)", "P&L (€)", "P&L (%)"]);
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

  sheet.appendRow([today, totalMV, totalInvested, pnl, pnlPct]);
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