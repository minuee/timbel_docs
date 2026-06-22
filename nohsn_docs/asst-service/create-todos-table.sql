-- advisor 스키마에 todos 테이블 생성
CREATE TABLE IF NOT EXISTS advisor.todos (
    id VARCHAR(64) NOT NULL,
    user_key VARCHAR(64) NOT NULL,
    callstats_id VARCHAR(64) NOT NULL,
    title VARCHAR(256) NOT NULL,
    state INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id)
);

-- 인덱스 생성 (성능 최적화)
CREATE INDEX IF NOT EXISTS idx_todos_user_key ON advisor.todos(user_key);
CREATE INDEX IF NOT EXISTS idx_todos_callstats_id ON advisor.todos(callstats_id);
CREATE INDEX IF NOT EXISTS idx_todos_state ON advisor.todos(state);
CREATE INDEX IF NOT EXISTS idx_todos_created_at ON advisor.todos(created_at);

-- 테이블 생성 확인
SELECT 
    table_schema, 
    table_name, 
    column_name, 
    data_type, 
    is_nullable, 
    column_default
FROM information_schema.columns 
WHERE table_schema = 'advisor' 
  AND table_name = 'todos'
ORDER BY ordinal_position;
