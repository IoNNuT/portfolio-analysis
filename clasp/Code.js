function recordPortfolioSnapshot() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // Read current total MV from your Summary sheet (adjust cell if needed)
  const summary = ss.getSheetByName("Summary");
  const totalMV = summary.getRange("E9").getValue();     // Total MV cell
  const totalInvested = summary.getRange("F9").getValue(); // Total Invested cell

  // Append to ETF History sheet
  const history = ss.getSheetByName("ETF History");
  if (!history) {
    ss.insertSheet("ETF History");
  }
  
  const sheet = ss.getSheetByName("ETF History");
  
  // Add header if sheet is empty
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["Date", "Total MV (€)", "Invested (€)", "P&L (€)", "P&L (%)"]);
  }
  
  const today = new Date();
  const pnl = totalMV - totalInvested;
  const pnlPct = (pnl / totalInvested);
  
  sheet.appendRow([today, totalMV, totalInvested, pnl, pnlPct]);
}

function recordStocksSnapshot() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  const summary = ss.getSheetByName("Summary");
  const totalMV = summary.getRange("E29").getValue();
  const totalInvested = summary.getRange("F29").getValue();

  let sheet = ss.getSheetByName("Stocks History");
  if (!sheet) {
    sheet = ss.insertSheet("Stocks History");
  }
  
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["Date", "Total MV (€)", "Invested (€)", "P&L (€)", "P&L (%)"]);
  }
  
  const today = new Date();
  const pnl = totalMV - totalInvested;
  const pnlPct = (pnl / totalInvested);
  
  sheet.appendRow([today, totalMV, totalInvested, pnl, pnlPct]);
}