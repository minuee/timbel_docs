const path = require('path');
const { app } = require('electron');
const Database = require('better-sqlite3');

let db;
function getDb() {
  if (db) return db;
  const dbPath = path.join(app.getPath('userData'), 'app.db');
  db = new Database(dbPath);
  db.pragma('journal_mode = WAL');

  db.exec(`
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS recordings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      file_name TEXT NOT NULL,
      file_path TEXT UNIQUE,
      created_by INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
      updated_by INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      updated_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    );

    CREATE TABLE IF NOT EXISTS memos (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
      t_ms INTEGER NOT NULL,
      text TEXT NOT NULL,
      created_by INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
      updated_by INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      updated_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    );

    CREATE TABLE IF NOT EXISTS tags (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      record_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      created_by INTEGER NULL REFERENCES users(user_id) ON DELETE CASCADE,
      updated_by INTEGER NULL REFERENCES users(user_id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      updated_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
      UNIQUE(record_id, name)
    );

    CREATE TABLE IF NOT EXISTS users (
      user_id INTEGER PRIMARY KEY,
      created_by INTEGER NULL REFERENCES users(user_id) ON DELETE CASCADE,
      updated_by INTEGER NULL REFERENCES users(user_id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      updated_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    );

    CREATE TABLE IF NOT EXISTS jobs (
      job_id INTEGER PRIMARY KEY AUTOINCREMENT,
      recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
      is_uploading BOOLEAN NOT NULL DEFAULT TRUE,
      created_by INTEGER NULL REFERENCES users(user_id) ON DELETE CASCADE,
      updated_by INTEGER NULL REFERENCES users(user_id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      updated_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    );
    
    CREATE TABLE IF NOT EXISTS summaries (
      summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
      recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
      lang TEXT NOT NULL,
      attendee_num TEXT NOT NULL,
      created_by INTEGER NULL REFERENCES users(user_id) ON DELETE CASCADE,
      updated_by INTEGER NULL REFERENCES users(user_id) ON DELETE CASCADE,
      created_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      updated_at INTEGER NOT NULL DEFAULT (datetime('now','localtime')),
      is_deleted BOOLEAN NOT NULL DEFAULT FALSE
    );
    
  `);
  migrate(db);
  return db;
}

// 이미 만들어진 DB 에 나중에 생긴 칸을 붙인다. 기존 데이터는 그대로 둔다.
function migrate(database) {
  const addColumn = (table, column, type) => {
    const cols = database.prepare(`PRAGMA table_info(${table})`).all().map((c) => c.name);
    if (!cols.includes(column)) database.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${type}`);
  };
  // 업로드 제목·템플릿 (업로드 리스트에서 재시도할 때도 같은 값으로 보내기 위해 저장)
  addColumn('summaries', 'title', 'TEXT');
  addColumn('summaries', 'template_id', 'TEXT');
  // 서버로 보내는 업로드 파일명(A.Biz_pcapp_rec_YYYYMMDD_HHmmss). 녹음 시작 시각 기준, 재업로드에도 같은 값
  addColumn('recordings', 'upload_name', 'TEXT');
}

module.exports = { getDb };