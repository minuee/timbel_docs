const { getDb } = require('./db');

function insertRecording({ fileName, filePath }) {
  const db = getDb();
  const insert = db.prepare(`
    INSERT INTO recordings (file_name, file_path)
    VALUES (?, ?)
  `);
  insert.run(fileName, filePath);
  return db.prepare('SELECT id FROM recordings WHERE id = last_insert_rowid()').get().id;
}

function upsertRecording({ fileName, filePath, recordingId }) {
  const db = getDb();
  const upsert = db.prepare(`
    INSERT INTO recordings (file_name, file_path)
    VALUES (@fileName, @filePath)
    ON CONFLICT(file_path) DO UPDATE SET
      file_name = excluded.file_name,
      file_path = excluded.file_path,
      updated_at = datetime('now','localtime'),
      is_deleted = FALSE
  `);
  upsert.run({ fileName, filePath});
  return db.prepare('SELECT id FROM recordings WHERE file_path=?').get(filePath)?.id;
}

// 업로드 팝업에서 제목을 넣으면 업로드 리스트에도 그 제목으로 보이게 한다.
function renameRecording(id, fileName) {
  const db = getDb();
  db.prepare("UPDATE recordings SET file_name=?, updated_at=datetime('now','localtime') WHERE id=?").run(fileName, id);
}

function deleteRecordingById(id) {
  const db = getDb();
  db.prepare('DELETE FROM recordings WHERE id=?').run(id);
}

function deleteRecordingByFilePath(filePath) {
  const db = getDb();
  db.prepare('DELETE FROM recordings WHERE file_path=?').run(filePath);
}

function markDeletedById(id) {
  const db = getDb();
  db.prepare("UPDATE recordings SET is_deleted=TRUE, updated_at=datetime('now','localtime') WHERE id=?").run(id);
}

function listRecordings() {
  const db = getDb();
  return db.prepare('SELECT * FROM recordings ORDER BY id DESC').all();
}

module.exports = { insertRecording, upsertRecording, renameRecording, deleteRecordingById, deleteRecordingByFilePath, markDeletedById, listRecordings };