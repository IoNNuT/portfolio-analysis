function toLocalDate(d) {
  const dt = new Date(d);
  return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
}

function doGet() {
  return HtmlService.createHtmlOutputFromFile('chart_page')
    .setTitle('ETF Portfolio Chart')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function getChartData() {
  const ss      = SpreadsheetApp.getActiveSpreadsheet();
  const sheet   = ss.getSheetByName("ETF History");
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];

  const numCols = Math.min(sheet.getLastColumn(), 6);
  return sheet.getRange(2, 1, lastRow - 1, numCols).getValues().map(row => ({
    date:     toLocalDate(row[0]),
    mv:       row[1],
    invested: row[2],
    pnl:      row[3],
    pnlPct:   row[4],
    sp500:    numCols >= 6 ? (row[5] || null) : null
  }));
}

// Aggregate Invested vs Total Return (incl. dividends) across the whole ETF
// portfolio, for the ETF tab's bar chart. Reads the ETFs table from the
// "Summary" sheet — located by the header row containing both "Invested" and
// "TTL Return ABS (with dividends)" — and sums those two columns over the
// holding rows, stopping at the first blank or "Total" row so a footer total
// isn't double-counted. Returns { invested, ret } in €, or null if not found.
function getEtfTotals() {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("Summary");
  if (!sheet) return null;

  const disp = sheet.getDataRange().getDisplayValues();

  let headerRow = -1, idxInv = -1, idxRet = -1;
  for (let i = 0; i < disp.length; i++) {
    const inv = disp[i].indexOf("Invested");
    const ret = disp[i].indexOf("TTL Return ABS (with dividends)");
    if (inv !== -1 && ret !== -1) {
      headerRow = i; idxInv = inv; idxRet = ret;
      break;
    }
  }
  if (headerRow === -1) return null;

  const num = v => {
    const n = parseFloat(String(v).replace(/[^0-9.\-]/g, ''));
    return isNaN(n) ? 0 : n;
  };

  let invested = 0, ret = 0;
  for (let i = headerRow + 1; i < disp.length; i++) {
    if (!(disp[i][idxInv] || "").trim()) break;        // blank Invested = table end
    if (disp[i].some(c => /total/i.test(c))) break;    // footer total row
    invested += num(disp[i][idxInv]);
    ret      += num(disp[i][idxRet]);
  }

  return { invested: invested, ret: ret };
}

function getStocksData() {
  const ss      = SpreadsheetApp.getActiveSpreadsheet();
  const sheet   = ss.getSheetByName("Stocks History");
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];

  const numCols = Math.min(sheet.getLastColumn(), 6);
  return sheet.getRange(2, 1, lastRow - 1, numCols).getValues().map(row => ({
    date:     toLocalDate(row[0]),
    mv:       row[1],
    invested: row[2],
    pnl:      row[3],
    pnlPct:   row[4],
    sp500:    numCols >= 6 ? (row[5] || null) : null
  }));
}

// Per-ticker Stocks holdings for the dashboard table.
// Reads the Stocks table from the "Summary" sheet (the header row containing
// both "Ticker" and "Weekly Change"), preserving the sheet's display strings
// so currency symbols / % signs survive. The daily % change is not stored in
// the sheet, so it's fetched live from Yahoo Finance.
function getStockHoldings() {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("Summary");
  if (!sheet) return [];

  const disp = sheet.getDataRange().getDisplayValues();

  // Locate the Stocks table header (ETF table lacks a "Weekly Change" column).
  let headerRow = -1;
  const col = {};
  for (let i = 0; i < disp.length; i++) {
    const row = disp[i];
    if (row.indexOf("Ticker") !== -1 && row.indexOf("Weekly Change") !== -1) {
      headerRow = i;
      row.forEach((h, j) => { col[h.trim()] = j; });
      break;
    }
  }
  if (headerRow === -1) return [];

  const idxTicker = col["Ticker"];
  const holdings = [];
  for (let i = headerRow + 1; i < disp.length; i++) {
    const ticker = (disp[i][idxTicker] || "").trim();
    if (!ticker) break;  // blank ticker = footer/total row → table ends
    holdings.push({
      ticker:       ticker,
      price:        (disp[i][col["Price"]]         || "").trim(),
      weeklyChange: (disp[i][col["Weekly Change"]] || "").trim(),
      shares:       (disp[i][col["Shares"]]        || "").trim(),
      mv:           (disp[i][col["MV"]]            || "").trim(),
      pnlAbs:       (disp[i][col["P&L (Abs)"]]     || "").trim(),
      pnlPct:       (disp[i][col["P&L (%)"]]       || "").trim(),
      dailyChange:  null
    });
  }

  const dailyMap = _fetchDailyChanges_(holdings.map(h => h.ticker));
  holdings.forEach(h => { h.dailyChange = dailyMap[h.ticker]; });

  return holdings;
}

// Returns { ticker: dailyChangeFraction|null }, e.g. { PTCT: 0.0394 }.
// Computed as (latest price − previous trading day's close) / previous close.
function _fetchDailyChanges_(tickers) {
  const out = {};
  if (!tickers.length) return out;

  const requests = tickers.map(t => ({
    url: "https://query1.finance.yahoo.com/v8/finance/chart/" +
         encodeURIComponent(t) + "?interval=1d&range=5d",
    headers: { "User-Agent": "Mozilla/5.0 (compatible; GAS/1.0)" },
    muteHttpExceptions: true
  }));

  let responses;
  try {
    responses = UrlFetchApp.fetchAll(requests);
  } catch (e) {
    Logger.log("_fetchDailyChanges_ error: " + e);
    return out;
  }

  responses.forEach((resp, i) => {
    const t = tickers[i];
    out[t] = null;
    try {
      if (resp.getResponseCode() !== 200) return;
      const result = JSON.parse(resp.getContentText()).chart.result[0];
      const closes = (result.indicators.quote[0].close || []).filter(c => c != null);
      const last   = result.meta.regularMarketPrice != null
        ? result.meta.regularMarketPrice
        : closes[closes.length - 1];
      const prev   = closes[closes.length - 2];
      if (last != null && prev != null && prev !== 0) {
        out[t] = (last - prev) / prev;
      }
    } catch (e) {
      Logger.log("_fetchDailyChanges_ parse error for " + t + ": " + e);
    }
  });

  return out;
}

function getNetWorthData() {
  const ss      = SpreadsheetApp.getActiveSpreadsheet();
  const sheet   = ss.getSheetByName("NetWorth History");
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];

  return sheet.getRange(2, 1, lastRow - 1, 2).getValues().map(row => {
    const raw = row[1];
    const nw  = typeof raw === 'string' ? parseFloat(raw.replace(/[€,]/g, '')) : raw;
    return {
      date:     toLocalDate(row[0]),
      netWorth: nw
    };
  });
}