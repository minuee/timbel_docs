# 데이터베이스 설정 가이드

> ⚠️ **[ARCHIVED]** 최신 문서는 다음을 참조하세요:
> - [adv_docs/operations/local-setup.md](../adv_docs/operations/local-setup.md) — 로컬 DB 셋업 (PG/Redis 도커)
> - [adv_docs/operations/migrations.md](../adv_docs/operations/migrations.md) — 마이그레이션 운영
> - [adv_docs/architecture/01-multi-tenant-db.md](../adv_docs/architecture/01-multi-tenant-db.md) — 멀티테넌트 DB 동작

---

## 방법 1: 수동 SQL 실행 (권장)

PostgreSQL에 연결하여 다음 SQL을 실행하세요:

```sql
-- 1. advisor 스키마 생성
CREATE SCHEMA IF NOT EXISTS advisor;

-- 2. notices 테이블 생성
CREATE TABLE IF NOT EXISTS advisor.notices (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    is_urgent BOOLEAN DEFAULT FALSE,
    content TEXT NOT NULL,
    remind_time TIMESTAMP,
    creator_key VARCHAR(100) NOT NULL,
    target_key VARCHAR(100) NOT NULL,
    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. notices_reads 테이블 생성
CREATE TABLE IF NOT EXISTS advisor.notices_reads (
    id VARCHAR(50) PRIMARY KEY,
    notices_id VARCHAR(50) NOT NULL,
    user_key VARCHAR(100) NOT NULL,
    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (notices_id) REFERENCES advisor.notices(id) ON DELETE CASCADE
);

-- 4. 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_notices_creator_key ON advisor.notices(creator_key);
CREATE INDEX IF NOT EXISTS idx_notices_target_key ON advisor.notices(target_key);
CREATE INDEX IF NOT EXISTS idx_notices_create_at ON advisor.notices(create_at);
CREATE INDEX IF NOT EXISTS idx_notices_reads_notices_id ON advisor.notices_reads(notices_id);
CREATE INDEX IF NOT EXISTS idx_notices_reads_user_key ON advisor.notices_reads(user_key);
CREATE INDEX IF NOT EXISTS idx_notices_reads_create_at ON advisor.notices_reads(create_at);

-- 5. 중복 읽음 방지를 위한 유니크 제약조건
CREATE UNIQUE INDEX IF NOT EXISTS idx_notices_reads_unique
ON advisor.notices_reads(notices_id, user_key);
```

## 방법 2: psql 명령어 사용

터미널에서 다음 명령어를 실행하세요:

```bash
# 기존 마이그레이션 파일 사용
psql -h localhost -U your_username -d your_database -f migrations/create_advisor_schema.sql

# 또는 직접 SQL 실행
psql -h localhost -U your_username -d your_database -c "
CREATE SCHEMA IF NOT EXISTS advisor;
CREATE TABLE IF NOT EXISTS advisor.notices (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    is_urgent BOOLEAN DEFAULT FALSE,
    content TEXT NOT NULL,
    remind_time TIMESTAMP,
    creator_key VARCHAR(100) NOT NULL,
    target_key VARCHAR(100) NOT NULL,
    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- ... 나머지 테이블 및 인덱스 생성
"
```

## 방법 3: 환경 변수 설정 후 애플리케이션 실행

1. `.env.local` 파일을 생성하고 다음 내용을 입력하세요:

```env
DB_TYPE=postgres
DB_HOST=localhost
DB_PORT=5432
DB_USERNAME=your_username
DB_PASSWORD=your_password
DB_DATABASE=your_database
NODE_ENV=local
```

2. 애플리케이션을 실행하면 마이그레이션이 자동으로 실행됩니다:

```bash
npm run start:dev
```

## 확인 방법

스키마와 테이블이 정상적으로 생성되었는지 확인하려면:

```sql
-- 스키마 확인
SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'advisor';

-- 테이블 확인
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'advisor';

-- 테이블 구조 확인
\d advisor.notices
\d advisor.notices_reads
```

