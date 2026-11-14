const { getDb } = require('./db');

function addTags(recordingId, tags) {
  const db = getDb();
  const tagList = Array.isArray(tags)
    ? tags
    : (typeof tags === 'string' ? [tags] : []);
  const cleaned = tagList
    .map(t => (typeof t === 'string' ? t.trim() : ''))
    .filter(t => t.length > 0);
  if (cleaned.length === 0) return;

  const insert = db.prepare(`
    INSERT INTO tags (record_id, name)
    VALUES (?, ?)
    ON CONFLICT(record_id, name) DO NOTHING
  `);
  const tx = db.transaction(() => {
    for (const t of cleaned) insert.run(recordingId, t);
  });
  tx();
}

function replaceTags(recordingId, tags) {
  const db = getDb();
  const del = db.prepare('DELETE FROM tags WHERE record_id=?');
  const insert = db.prepare('INSERT INTO tags (record_id, name) VALUES (?, ?)');
  const tx = db.transaction(() => {
    del.run(recordingId);
    for (const t of tags) insert.run(recordingId, t);
  });
  tx();
}

function getTags(recordingId) {
  const db = getDb();
  return db.prepare(`
    SELECT 
      name 
    FROM 
      tags 
    WHERE record_id=?
  `).all(recordingId);
}

module.exports = { addTags, replaceTags, getTags };