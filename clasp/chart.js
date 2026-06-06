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

// Invested vs Total Return (incl. dividends) for the whole ETF portfolio, for
// the ETF tab's bar chart. Locates the ETFs table in the "Summary" sheet — the
// header row that has both "Invested" and "TTL Return (Abs)" but NO "Weekly
// Change" column (the latter marks the Stocks table, which shares those two
// headers). The table already carries a footer row with the column sums, so we
// read those directly rather than re-summing the holdings (which would also
// pick up the footer and double the totals). Returns { invested, ret } in €,
// or null if the table/footer isn't found.
function getEtfTotals() {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("Summary");
  if (!sheet) return null;

  const disp = sheet.getDataRange().getDisplayValues();
  const norm = c => String(c).replace(/\s+/g, " ").trim().toLowerCase();

  let headerRow = -1, idxInv = -1, idxRet = -1;
  for (let i = 0; i < disp.length; i++) {
    let inv = -1, ret = -1, weekly = false;
    disp[i].forEach((c, j) => {
      const n = norm(c);
      if (n === "invested")          inv = inv === -1 ? j : inv;
      if (n === "ttl return (abs)")  ret = ret === -1 ? j : ret;
      if (n === "weekly change")     weekly = true;
    });
    if (inv !== -1 && ret !== -1 && !weekly) {   // ETF table, not Stocks
      headerRow = i; idxInv = inv; idxRet = ret;
      break;
    }
  }
  if (headerRow === -1) return null;

  const num = v => {
    const n = parseFloat(String(v).replace(/[^0-9.\-]/g, ''));
    return isNaN(n) ? 0 : n;
  };

  // The footer is the first row after the header whose Ticker cell is empty
  // (or "Total") but whose Invested cell still carries a value — that's where
  // the sheet keeps the column sums.
  let idxTicker = -1;
  disp[headerRow].forEach((c, j) => { if (norm(c) === "ticker") idxTicker = j; });

  for (let i = headerRow + 1; i < disp.length; i++) {
    const ticker = idxTicker !== -1 ? (disp[i][idxTicker] || "").trim() : "";
    if (ticker && !/total/i.test(ticker)) continue;   // holding row — skip to footer
    const cell = (disp[i][idxInv] || "").trim();
    if (!cell) break;                                 // blank gap, no footer found
    return { invested: num(cell), ret: num(disp[i][idxRet]) };
  }

  return null;
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
      costBasis:    (disp[i][col["Cost Basis"]]    || "").trim(),
      shares:       (disp[i][col["Shares"]]        || "").trim(),
      mv:           (disp[i][col["MV"]]            || "").trim(),
      pnlAbs:       (disp[i][col["P&L (Abs)"]]     || "").trim(),
      pnlPct:       (disp[i][col["P&L (%)"]]       || "").trim(),
      dailyChange:  null
    });
  }

  const changes = _fetchPriceChanges_(holdings.map(h => h.ticker));
  holdings.forEach(h => { h.dailyChange = (changes[h.ticker] || {}).daily; });

  return holdings;
}

// Per-ticker ETF holdings for the dashboard table.
// Reads the ETF table from the "Summary" sheet — the header row with "Ticker"
// and "Cost Basis" but NO "Weekly Change" (the latter marks the Stocks table)
// and an "MV" column (distinguishes it from the bonds table further down). The
// ETF table sits at the top of the sheet, so the first match is the right one.
// The sheet stores neither a daily nor a weekly change for ETFs, so both are
// computed live from Yahoo Finance (these are all .DE-listed tickers).
function getEtfHoldings() {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("Summary");
  if (!sheet) return [];

  const disp = sheet.getDataRange().getDisplayValues();

  let headerRow = -1;
  const col = {};
  for (let i = 0; i < disp.length; i++) {
    const row = disp[i];
    const has = name => row.indexOf(name) !== -1;
    if (has("Ticker") && has("Cost Basis") && has("MV") && !has("Weekly Change")) {
      headerRow = i;
      row.forEach((h, j) => { const k = h.trim(); if (col[k] === undefined) col[k] = j; });
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
      price:        (disp[i][col["Price"]]      || "").trim(),
      costBasis:    (disp[i][col["Cost Basis"]] || "").trim(),
      shares:       (disp[i][col["Shares"]]     || "").trim(),
      mv:           (disp[i][col["MV"]]         || "").trim(),
      pnlAbs:       (disp[i][col["P&L (Abs)"]]  || "").trim(),
      pnlPct:       (disp[i][col["P&L (%)"]]    || "").trim(),
      dailyChange:  null,
      weeklyChange: null
    });
  }

  const changes = _fetchPriceChanges_(holdings.map(h => h.ticker));
  holdings.forEach(h => {
    const c = changes[h.ticker] || {};
    h.dailyChange  = c.daily  != null ? c.daily  : null;
    h.weeklyChange = c.weekly != null ? c.weekly : null;
  });

  return holdings;
}

// Romania portfolio for the dashboard's Romania page: the single-line BET ETF
// table and the government-bonds table, both read from the "Summary" sheet.
// Values are kept as the sheet's display strings (RON / € symbols preserved),
// like the other holdings tables — the BET holding is RON-denominated and the
// bonds are EUR-denominated, so no currency conversion is attempted.
//
// The BET table is the header row with "Ticker" + "Weighting" but no
// "Target Weight" / "Weekly Change" / "SCADENTA" (those mark the ETF, Stocks
// and bonds tables respectively). The bonds table is the header row carrying
// the Romanian "SCADENTA" (maturity) column; its "Cost Basis" header cell is
// wrapped in literal quote characters in the sheet, so column keys are stripped
// of surrounding quotes before matching. Returns { bet, bonds }.
function getRomaniaHoldings() {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("Summary");
  if (!sheet) return { bet: null, bonds: [] };

  const disp   = sheet.getDataRange().getDisplayValues();
  const has    = (row, name) => row.indexOf(name) !== -1;
  const keyOf  = h => h.trim().replace(/^"+|"+$/g, "");
  const colMap = row => {
    const col = {};
    row.forEach((h, j) => { const k = keyOf(h); if (col[k] === undefined) col[k] = j; });
    return col;
  };

  let bet = null;
  const bonds = [];

  // ── BET ETF table (single holding) ──
  for (let i = 0; i < disp.length; i++) {
    const row = disp[i];
    if (has(row, "Ticker") && has(row, "Weighting") &&
        !has(row, "Target Weight") && !has(row, "Weekly Change") && !has(row, "SCADENTA")) {
      const col = colMap(row);
      const t   = (disp[i + 1] && (disp[i + 1][col["Ticker"]] || "").trim()) || "";
      if (t) {
        const r = disp[i + 1];
        bet = {
          ticker:    t,
          price:     (r[col["Price"]]      || "").trim(),
          costBasis: (r[col["Cost Basis"]] || "").trim(),
          shares:    (r[col["Shares"]]     || "").trim(),
          mv:        (r[col["MV"]]         || "").trim(),
          invested:  (r[col["Invested"]]   || "").trim(),
          pnlAbs:    (r[col["P&L (Abs)"]]  || "").trim(),
          pnlPct:    (r[col["P&L"]]        || "").trim(),
          weighting: (r[col["Weighting"]]  || "").trim()
        };
      }
      break;
    }
  }

  // ── Government bonds table ──
  for (let i = 0; i < disp.length; i++) {
    if (has(disp[i], "Ticker") && has(disp[i], "SCADENTA")) {
      const col       = colMap(disp[i]);
      const idxTicker = col["Ticker"];
      for (let k = i + 1; k < disp.length; k++) {
        const ticker = (disp[k][idxTicker] || "").trim();
        if (!ticker) break;   // blank ticker = totals/footer row → table ends
        bonds.push({
          ticker:    ticker,
          price:     (disp[k][col["Price"]]          || "").trim(),
          costBasis: (disp[k][col["Cost Basis"]]     || "").trim(),
          shares:    (disp[k][col["Shares"]]         || "").trim(),
          invested:  (disp[k][col["Invested"]]       || "").trim(),
          returnPct: (disp[k][col["RETURN %"]]       || "").trim(),
          returnAbs: (disp[k][col["RETURN ABS"]]     || "").trim(),
          maturity:  (disp[k][col["SCADENTA"]]       || "").trim(),
          years:     (disp[k][col["PERIOADA (ANI)"]] || "").trim()
        });
      }
      break;
    }
  }

  return { bet: bet, bonds: bonds };
}

// Returns { ticker: { daily, weekly } } as fractions (e.g. 0.0394 → +3.94%),
// each null when unavailable. Daily = (latest − previous trading day's close) /
// previous close. Weekly = (latest − last close at or before 7 calendar days
// ago) / that close. One month of daily candles is fetched so the ~7-day-ago
// reference is always present.
function _fetchPriceChanges_(tickers) {
  const out = {};
  if (!tickers.length) return out;

  const requests = tickers.map(t => ({
    url: "https://query1.finance.yahoo.com/v8/finance/chart/" +
         encodeURIComponent(t) + "?interval=1d&range=1mo",
    headers: { "User-Agent": "Mozilla/5.0 (compatible; GAS/1.0)" },
    muteHttpExceptions: true
  }));

  let responses;
  try {
    responses = UrlFetchApp.fetchAll(requests);
  } catch (e) {
    Logger.log("_fetchPriceChanges_ error: " + e);
    return out;
  }

  responses.forEach((resp, i) => {
    const t = tickers[i];
    out[t] = { daily: null, weekly: null };
    try {
      if (resp.getResponseCode() !== 200) return;
      const result   = JSON.parse(resp.getContentText()).chart.result[0];
      const ts       = result.timestamp || [];
      const rawClose = result.indicators.quote[0].close || [];

      // Pair timestamps with their non-null closes, in chronological order.
      const series = [];
      for (let k = 0; k < rawClose.length; k++) {
        if (rawClose[k] != null && ts[k] != null) series.push({ t: ts[k], c: rawClose[k] });
      }
      if (!series.length) return;

      const last = result.meta.regularMarketPrice != null
        ? result.meta.regularMarketPrice
        : series[series.length - 1].c;
      const lastTs = result.meta.regularMarketTime != null
        ? result.meta.regularMarketTime
        : series[series.length - 1].t;

      // Daily: vs the previous trading day's close.
      const prev = series.length >= 2 ? series[series.length - 2].c : null;
      if (last != null && prev != null && prev !== 0) out[t].daily = (last - prev) / prev;

      // Weekly: vs the latest close at or before 7 calendar days ago; if the
      // history doesn't reach back that far, fall back to the earliest close.
      const weekAgo = lastTs - 7 * 86400;
      let ref = null;
      for (let k = series.length - 1; k >= 0; k--) {
        if (series[k].t <= weekAgo) { ref = series[k].c; break; }
      }
      if (ref == null) ref = series[0].c;
      if (last != null && ref != null && ref !== 0) out[t].weekly = (last - ref) / ref;
    } catch (e) {
      Logger.log("_fetchPriceChanges_ parse error for " + t + ": " + e);
    }
  });

  return out;
}

// Finds a sheet by its gid (sheet id), which survives tab renames — more robust
// than getSheetByName for the Overview's allocation tab.
function _sheetByGid_(ss, gid) {
  const sheets = ss.getSheets();
  for (let i = 0; i < sheets.length; i++) {
    if (sheets[i].getSheetId() === gid) return sheets[i];
  }
  return null;
}

// Reads the live "Portfolio Status" allocation tab (gid 1124476629) for the
// Overview page. Columns: Category | Value | Value EURO. The EURO column carries
// display strings with currency symbols ("€31,805.05"), so values are regex-
// stripped to numbers. The sheet's own "Total" row is returned as `total`; the
// breakdown `rows` excludes it. Zero-value rows (e.g. Crypto) are kept so they
// still appear in the table. Returns { rows: [{category, value}], total } in €.
function getPortfolioStatus() {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = _sheetByGid_(ss, 1124476629);
  if (!sheet) return { rows: [], total: 0 };

  const disp = sheet.getDataRange().getDisplayValues();
  if (disp.length < 2) return { rows: [], total: 0 };

  const norm = c => String(c).replace(/\s+/g, " ").trim().toLowerCase();
  const num  = v => {
    const n = parseFloat(String(v).replace(/[^0-9.\-]/g, ""));
    return isNaN(n) ? 0 : n;
  };

  const header = disp[0].map(norm);
  const idxCat = header.indexOf("category");
  let   idxEur = header.indexOf("value euro");
  if (idxEur === -1) idxEur = header.indexOf("value eur");
  if (idxCat === -1 || idxEur === -1) return { rows: [], total: 0 };

  const rows = [];
  let total = null;
  for (let i = 1; i < disp.length; i++) {
    const cat = (disp[i][idxCat] || "").trim();
    if (!cat) continue;
    const val = num(disp[i][idxEur]);
    if (/total/i.test(cat)) { total = val; continue; }
    rows.push({ category: cat, value: val });
  }
  if (total === null) total = rows.reduce((s, r) => s + r.value, 0);
  return { rows: rows, total: total };
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