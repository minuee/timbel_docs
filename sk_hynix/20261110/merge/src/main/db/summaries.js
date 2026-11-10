const { getDb } = require('./db');

function insertSummary({ recordingId, lang, attendeeNum, title, templateId }) {
  const db = getDb();
  const insert = db.prepare(`
    INSERT INTO summaries (recording_id, lang, attendee_num, title, template_id)
    VALUES (?, ?, ?, ?, ?)
  `);
  insert.run(recordingId, lang, attendeeNum, title || null, templateId || null);
  return db.prepare('SELECT summary_id FROM summaries WHERE summary_id = last_insert_rowid()').get().summary_id;
};

function getSummary(recordingId) {
  const db = getDb();
  return db.prepare('SELECT lang, attendee_num, title, template_id FROM summaries WHERE recording_id = ? ORDER BY summary_id DESC').get(recordingId);
};

module.exports = { insertSummary, getSummary };