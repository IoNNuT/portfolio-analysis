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