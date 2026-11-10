const { getDb } = require('./db');

// uploadName: 서버로 보내는 fileName(A.Biz_pcapp_rec_YYYYMMDD_HHmmss). 녹음 시작 때 정해져 바뀌지 않는다.
function insertRecording({ fileName, filePath, uploadName }) {
  const db = getDb();
  const insert = db.prepare(`
    INSERT INTO recordings (file_name, file_path, upload_name)
    VALUES (?, ?, ?)
  `);
  insert.run(fileName, filePath, uploadName || null);
  return db.prepare('SELECT id FROM recordings WHERE id = last_insert_rowid()').get().id;
}

function upsertRecording({ fileName, filePath, recordingId, uploadName }) {
  const db = getDb();
  // 녹음 시작 때 만든 행(recordingId)이 있으면 그 행을 고친다.
  // 저장 폴더가 실제 위치로 바뀌어도(recording.js handleSegmentReady) 새 행이 생기지 않게 하기 위함.
  if (recordingId && db.prepare('SELECT 1 FROM recordings WHERE id=?').get(recordingId)) {
    db.prepare(`
      UPDATE recordings
      SET file_name=?, file_path=?, updated_at=datetime('now','localtime'), is_deleted=FALSE
      WHERE id=?
    `).run(fileName, filePath, recordingId);
    return recordingId;
  }
  const upsert = db.prepare(`
    INSERT INTO recordings (file_name, file_path, upload_name)
    VALUES (@fileName, @filePath, @uploadName)
    ON CONFLICT(file_path) DO UPDATE SET
      file_name = excluded.file_name,
      file_path = excluded.file_path,
      updated_at = datetime('now','localtime'),
      is_deleted = FALSE
  `);
  upsert.run({ fileName, filePath, uploadName: uploadName || null });
  return db.prepare('SELECT id FROM recordings WHERE file_path=?').get(filePath)?.id;
}

// 업로드 팝업에서 제목을 넣으면 업로드 리스트에도 그 제목으로 보이게 한다.
function renameRecording(id, fileName) {
  const db = getDb();
  db.prepare("UPDATE recordings SET file_name=?, updated_at=datetime('now','localtime') WHERE id=?").run(fileName, id);
}

function getUploadName(id) {
  if (!id) return null;
  const db = getDb();
  const row = db.prepare('SELECT upload_name FROM recordings WHERE id=?').get(id);
  return (row && row.upload_name) || null;
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

module.exports = { insertRecording, upsertRecording, renameRecording, getUploadName, deleteRecordingById, deleteRecordingByFilePath, markDeletedById, listRecordings };