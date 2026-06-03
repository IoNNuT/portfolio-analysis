function debugETFRaw() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("ETF History");
  const lastRow = sheet.getLastRow();
  const data = sheet.getRange(2, 1, lastRow - 1, 5).getValues();
  
  data.forEach((row, i) => {
    Logger.log(`Row ${i+1}: date=${new Date(row[0]).toISOString().split('T')[0]} | mv=${row[1]} | invested=${row[2]} | pnl=${row[3]} | pnlPct=${row[4]}`);
  });
}

// Run from the Apps Script editor, then View > Logs. Shows every Summary row
// that mentions "Invested" or "Return" so we can see the exact header text and
// the table layout (stacked vs side-by-side), and what getEtfTotals returns.
function debugEtfTotals() {
  const disp = SpreadsheetApp.getActiveSpreadsheet()
    .getSheetByName("Summary").getDataRange().getDisplayValues();

  disp.forEach((row, i) => {
    if (row.some(c => /invest|return/i.test(c))) {
      Logger.log(`Row ${i}: ${JSON.stringify(row.map(c => c.trim()).filter(c => c !== ""))}`);
    }
  });

  Logger.log("getEtfTotals() => " + JSON.stringify(getEtfTotals()));
}

function debugDates() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("ETF History");
  const data  = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getValues();
  
  data.forEach((row, i) => {
    const d = new Date(row[0]);
    Logger.log(`Row ${i+1}: raw="${row[0]}" | getDate=${d.getDate()} | getMonth=${d.getMonth()+1} | toLocal=${toLocalDate(row[0])} | toISO=${d.toISOString()}`);
  });
}