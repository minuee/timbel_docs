const fs = require('fs');
const path = require('path');
const { getDb } = require('../db/db');
const recordingsRepo = require('../db/recordings');
const jobsRepo = require('../db/jobs');

function safeFileExists(filePath) {
  try {
    if (!filePath || typeof filePath !== 'string') return false;
    return fs.existsSync(filePath);
  } catch (_) {
    return false;
  }
}

// 앱 시작 시 1회 호출: recordings에는 존재하지만 jobs에는 없는 항목을 스캔
// - 파일이 없으면 recordings 삭제
// - 파일이 있으면 jobs에 자동 enqueue
// 반환: { queued: Array<{recordingId, filePath, fileName}>, deleted: number[] }
function scanAndAutoQueue() {
  const db = getDb();
  const queued = [];
  const deleted = [];

  // 후보 조회: jobs가 하나도 없는 recordings
  const candidates = db.prepare(`
    SELECT r.id AS recording_id, r.file_name, r.file_path
    FROM recordings r
    LEFT JOIN jobs j ON j.recording_id = r.id
    WHERE r.is_deleted = FALSE AND j.job_id IS NULL
  `).all();

  if (!Array.isArray(candidates) || candidates.length === 0) {
    return { queued, deleted };
  }

  for (const row of candidates) {
    const recordingId = row.recording_id;
    const filePath = row.file_path;
    const fileName = row.file_name;

    const exists = safeFileExists(filePath);
    if (!exists) {
      try {
        recordingsRepo.deleteRecordingById(recordingId);
        deleted.push(recordingId);
      } catch (_) {
        // 무시하고 다음 항목 진행
      }
      continue;
    }

    // 파일이 존재하면 업로드 잡 자동 생성(멱등성: 현재 쿼리 자체가 jobs 없음인 항목만 대상)
    try {
      const jobId = jobsRepo.enqueueUpload(recordingId);
      queued.push({ recordingId, jobId, filePath, fileName });
    } catch (_) {
      // 실패 시 건너뛰기 (로그는 상위에서 처리)
    }
  }

  return { queued, deleted };
}

module.exports = {
  scanAndAutoQueue,
};


