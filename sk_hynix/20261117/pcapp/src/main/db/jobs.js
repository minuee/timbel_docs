const { getDb } = require('./db');

function enqueueUpload(recordingId) {
  const db = getDb();
  const insert = db.prepare(`
    INSERT INTO jobs (recording_id, is_uploading)
    VALUES (?, FALSE)
  `);
  const info = insert.run(recordingId);
  return info.lastInsertRowid;
}

function listPendingUploads() {
  const db = getDb();
  // recordings 메타와 조인하여 업로드에 필요한 파일 정보 제공
  const rows = db.prepare(`
    SELECT j.job_id, j.recording_id, j.is_uploading,
          r.file_name, r.file_path, r.created_at AS recording_created_at
    FROM jobs j
    JOIN recordings r ON r.id = j.recording_id
    WHERE j.is_uploading = FALSE AND r.is_deleted = FALSE
    ORDER BY j.job_id ASC
  `).all();
  return rows;
}

function markUploaded(jobId) {
  const db = getDb();
  db.prepare(`
    UPDATE jobs
    SET is_uploading = TRUE,
        updated_at = datetime('now','localtime')
    WHERE job_id = ?
  `).run(jobId);
}

function markUploadFailed(jobId) {
  const db = getDb();
  db.prepare(`
    UPDATE jobs 
    SET is_uploading = FALSE, 
        updated_at = datetime('now','localtime') 
    WHERE job_id = ?
  `).run(jobId);
}

function removeJob(jobId) {
  const db = getDb();
  db.prepare('DELETE FROM jobs WHERE job_id = ?').run(jobId);
}

function listJobs() {
  const db = getDb();
  return db.prepare(`
    SELECT j.job_id, j.recording_id, j.is_uploading,
      r.file_name, r.file_path, r.created_at AS recording_created_at
    FROM jobs j
    JOIN recordings r ON r.id = j.recording_id
    WHERE j.is_deleted = FALSE
    ORDER BY r.created_at DESC
  `).all();
}

module.exports = {
  enqueueUpload,
  listPendingUploads,
  markUploaded,
  removeJob,
  listJobs,
  markUploadFailed,
};


