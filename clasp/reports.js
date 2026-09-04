// ── Weekly Analysis Library ───────────────────────────────────────────────────
// Imports the weekly portfolio-analysis email reports into a Drive folder and
// exposes them to the dashboard's "Library" tab.
//
// Setup (one-time):
//   1. Create a Drive folder (e.g. "Portfolio Analysis Reports").
//   2. Project Settings → Script Properties → add REPORTS_FOLDER_ID = <folder id>.
//   3. Run ensureDailyReportImportTrigger() once to install the import trigger.
//      (Do not set this up weekly by hand — see the note on that function.)
//
// The read functions (listReports/getReportHtml) run as the deploying user, so
// reports never leave Apps Script — nothing is published publicly.

function getReportsFolderId_() {
  let id = PropertiesService.getScriptProperties().getProperty('REPORTS_FOLDER_ID');
  if (!id) throw new Error('Script Property REPORTS_FOLDER_ID is not set');
  id = id.trim();
  // Accept a pasted folder URL too: extract the part after /folders/ (or ?id=).
  const m = id.match(/\/folders\/([^/?#]+)/) || id.match(/[?&]id=([^&]+)/);
  if (m) id = m[1];
  return id;
}

// Installs the daily import trigger, replacing any existing trigger for
// importReportsFromGmail. Run once from the editor; safe to re-run.
//
// This must NOT be weekly. The GitHub Actions job that sends the report is
// scheduled for 02:00 UTC, but Actions delays scheduled runs under load and the
// delay is highly variable — across the first fourteen reports the email landed
// anywhere from 05:55 to 10:52 Europe/Bucharest. A weekly Monday trigger
// therefore races the email: 2026-08-31 arrived at 10:52, after that Monday's
// import had already run, and would have sat unimported until 09-07.
//
// Daily removes the race. The function is idempotent and writes nothing when
// there is no new report, so the cost of the extra runs is one Gmail search.
// Worst case a late report is picked up 24h later instead of 7 days later.
function ensureDailyReportImportTrigger() {
  let removed = 0;
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'importReportsFromGmail') {
      ScriptApp.deleteTrigger(t);
      removed++;
    }
  });

  // 12:00–13:00 local, comfortably clear of the latest observed arrival (10:52).
  ScriptApp.newTrigger('importReportsFromGmail')
    .timeBased()
    .everyDays(1)
    .atHour(12)
    .create();

  Logger.log('ensureDailyReportImportTrigger: removed %s old trigger(s), installed daily ~12:00 %s',
    removed, Session.getScriptTimeZone());
}

// Runs daily via ensureDailyReportImportTrigger().
// Idempotent: only reports not already in the folder are added.
function importReportsFromGmail() {
  const folder = DriveApp.getFolderById(getReportsFolderId_());
  const threads = GmailApp.search('subject:"Portfolio Analysis" has:attachment newer_than:1y');
  // Matches "Portfolio Analysis (Full) — 2026-05-30" (em dash or hyphen).
  const subjectRe = /Portfolio Analysis \((Full|Incremental)\)\s*[—-]\s*(\d{4}-\d{2}-\d{2})/;
  let imported = 0;

  threads.forEach(function (thread) {
    thread.getMessages().forEach(function (msg) {
      const m = subjectRe.exec(msg.getSubject());
      if (!m) return;
      const mode = m[1];
      const date = m[2];
      const name = 'portfolio-analysis-' + date + '-' + mode + '.html';
      if (folder.getFilesByName(name).hasNext()) return; // already imported

      const att = msg.getAttachments().filter(function (a) {
        return /\.html?$/i.test(a.getName()) || a.getContentType() === 'text/html';
      })[0];
      if (!att) return;

      folder.createFile(name, att.getDataAsString(), MimeType.HTML);
      imported++;
    });
  });

  Logger.log('Imported %s new report(s)', imported);
  return imported;
}

// Called from the dashboard frontend. Returns [{id, date, mode}] newest-first.
function listReports() {
  const folder = DriveApp.getFolderById(getReportsFolderId_());
  const files = folder.getFiles();
  const nameRe = /^portfolio-analysis-(\d{4}-\d{2}-\d{2})-(Full|Incremental)\.html$/;
  const out = [];
  while (files.hasNext()) {
    const f = files.next();
    const m = nameRe.exec(f.getName());
    if (!m) continue;
    out.push({ id: f.getId(), date: m[1], mode: m[2] });
  }
  out.sort(function (a, b) { return b.date.localeCompare(a.date); });
  return out;
}

// Returns the HTML of a single report. Guards that the file lives in our folder.
function getReportHtml(id) {
  const folderId = getReportsFolderId_();
  const file = DriveApp.getFileById(id);
  const parents = file.getParents();
  let ok = false;
  while (parents.hasNext()) {
    if (parents.next().getId() === folderId) { ok = true; break; }
  }
  if (!ok) throw new Error('File is not in the reports folder');
  return file.getBlob().getDataAsString();
}
