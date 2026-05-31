// ── Weekly Analysis Library ───────────────────────────────────────────────────
// Imports the weekly portfolio-analysis email reports into a Drive folder and
// exposes them to the dashboard's "Library" tab.
//
// Setup (one-time):
//   1. Create a Drive folder (e.g. "Portfolio Analysis Reports").
//   2. Project Settings → Script Properties → add REPORTS_FOLDER_ID = <folder id>.
//   3. Triggers → add a time-driven trigger running importReportsFromGmail()
//      weekly on Monday (after the analysis email is sent).
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

// Trigger this weekly. Idempotent: only reports not already in the folder are added.
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
