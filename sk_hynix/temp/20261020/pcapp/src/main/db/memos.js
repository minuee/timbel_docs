const { getDb } = require('./db');

function saveMemosBatch(recordingId, memo) {
  const db = getDb();
  const insertMemo = db.prepare(`
    INSERT INTO memos (recording_id, t_ms, text)
    VALUES (?, ?, ?)
  `);
  insertMemo.run(recordingId, memo.t_ms, memo.text);
  return selectMemoByRecordingId(insertMemo.recordingId);
}

function updateMemo(id, text) {
  const db = getDb();
  db.prepare("UPDATE memos SET text=?, updated_at=datetime('now','localtime') WHERE id=?").run(text, id);
}

function deleteMemo(id) {
  const db = getDb();
  db.prepare('DELETE FROM memos WHERE id=?').run(id);
}

function selectMemoByRecordingId(recordingId) {
  const db = getDb();
  return db.prepare('SELECT * FROM memos WHERE recording_id=?').get(recordingId);
}

function getMemos(recordingId) {
  const db = getDb();
  return db.prepare(`
    SELECT 
      text, 
      t_ms as time 
    FROM 
      memos 
    WHERE 
      recording_id=?
    ORDER BY
      t_ms ASC
  `).all(recordingId);
}

module.exports = { saveMemosBatch, updateMemo, deleteMemo, getMemos };