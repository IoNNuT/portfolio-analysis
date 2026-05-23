function debugETFRaw() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("ETF History");
  const lastRow = sheet.getLastRow();
  const data = sheet.getRange(2, 1, lastRow - 1, 5).getValues();
  
  data.forEach((row, i) => {
    Logger.log(`Row ${i+1}: date=${new Date(row[0]).toISOString().split('T')[0]} | mv=${row[1]} | invested=${row[2]} | pnl=${row[3]} | pnlPct=${row[4]}`);
  });
}

function debugDates() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("ETF History");
  const data  = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getValues();
  
  data.forEach((row, i) => {
    const d = new Date(row[0]);
    Logger.log(`Row ${i+1}: raw="${row[0]}" | getDate=${d.getDate()} | getMonth=${d.getMonth()+1} | toLocal=${toLocalDate(row[0])} | toISO=${d.toISOString()}`);
  });
}