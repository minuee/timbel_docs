# SQL 쿼리 로깅 가이드

## 개요

`get_filtered_doc` API에서 실제로 실행되는 SQL 쿼리를 확인하여 성능 튜닝을 수행할 수 있도록 합니다.

## 방법 1: SQLAlchemy echo 옵션 사용 (개발 환경)

### 1-1. database_manager.py 수정

```python
# managers/database_manager.py의 get_engine_by_url 메서드 수정

def get_engine_by_url(self, db_url):
    tenant_id = make_url(db_url).database
    engine = self.engine_cache.get(tenant_id=tenant_id)
    if not engine:
        # SQL 로깅 활성화 (개발 환경에서만)
        echo_sql = settings.DEBUG  # 또는 환경 변수로 제어

        engine = create_engine(
            db_url,
            echo=echo_sql,  # True로 설정하면 모든 SQL이 로그에 출력됨
            pool_size=20,
            max_overflow=30,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
        )
        self.engine_cache.set(tenant_id=tenant_id, engine=engine)

    return engine
```

### 1-2. 환경 변수로 제어 (권장)

```python
# core/config.py에 추가
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() == "true"

# managers/database_manager.py
def get_engine_by_url(self, db_url):
    tenant_id = make_url(db_url).database
    engine = self.engine_cache.get(tenant_id=tenant_id)
    if not engine:
        from core.config import settings
        echo_sql = settings.SQL_ECHO

        engine = create_engine(
            db_url,
            echo=echo_sql,
            # ... 나머지 설정
        )
        self.engine_cache.set(tenant_id=tenant_id, engine=engine)

    return engine
```

실행 시:

```bash
SQL_ECHO=true python main.py
```

## 방법 2: 이벤트 리스너 사용 (프로덕션 환경 권장)

### 2-1. SQL 로깅 유틸리티 생성

```python
# utils/sql_logger.py
from sqlalchemy import event
from sqlalchemy.engine import Engine
import time
from core.config import settings

if settings.DEBUG:
    from loguru import logger
else:
    import logging as logger

# 쿼리 실행 시간 측정
@event.listens_for(Engine, "before_cursor_execute")
def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault('query_start_time', []).append(time.time())

@event.listens_for(Engine, "after_cursor_execute")
def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total = time.time() - conn.info['query_start_time'].pop(-1)

    # 느린 쿼리만 로깅 (예: 1초 이상)
    if total > 1.0:
        logger.warning(f"Slow Query ({total:.2f}s): {statement[:200]}")
        logger.debug(f"Parameters: {parameters}")

    # 모든 쿼리 로깅 (디버그 모드)
    if settings.DEBUG:
        logger.debug(f"SQL ({total:.3f}s): {statement}")
        if parameters:
            logger.debug(f"Parameters: {parameters}")
```

### 2-2. database_manager.py에 적용

```python
# managers/database_manager.py
from utils.sql_logger import receive_before_cursor_execute, receive_after_cursor_execute
from sqlalchemy import event

def get_engine_by_url(self, db_url):
    tenant_id = make_url(db_url).database
    engine = self.engine_cache.get(tenant_id=tenant_id)
    if not engine:
        engine = create_engine(
            db_url,
            echo=False,
            # ... 나머지 설정
        )

        # 이벤트 리스너 등록
        event.listen(engine, "before_cursor_execute", receive_before_cursor_execute)
        event.listen(engine, "after_cursor_execute", receive_after_cursor_execute)

        self.engine_cache.set(tenant_id=tenant_id, engine=engine)

    return engine
```

## 방법 3: PostgreSQL 로그 확인

### 3-1. PostgreSQL 설정 확인

```sql
-- 현재 로깅 설정 확인
SHOW log_statement;
SHOW log_duration;
SHOW log_min_duration_statement;

-- 모든 쿼리 로깅 활성화 (개발 환경)
SET log_statement = 'all';
SET log_duration = on;

-- 느린 쿼리만 로깅 (프로덕션 권장)
SET log_min_duration_statement = 1000;  -- 1초 이상인 쿼리만 로깅
```

### 3-2. postgresql.conf 설정

```conf
# postgresql.conf
log_statement = 'all'  # 또는 'mod' (DDL, DML만)
log_duration = on
log_min_duration_statement = 1000  # 1초 이상인 쿼리만 로깅
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_checkpoints = on
log_connections = on
log_disconnections = on
```

## 방법 4: 쿼리 실행 계획 확인

### 4-1. EXPLAIN ANALYZE 사용

실제 쿼리를 복사하여 PostgreSQL에서 직접 실행:

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
-- 여기에 실제 SQL 쿼리 붙여넣기
SELECT ...
FROM aicm.aicm_documents
WHERE ...
```

### 4-2. Python에서 실행 계획 확인

```python
# db/repositories/document/document_repository.py에 추가

def get_filtered_documents(self, ...):
    query = self.db.query(DocumentsModel)
    # ... 쿼리 구성 ...

    # 실행 계획 확인 (디버그 모드에서만)
    if settings.DEBUG:
        from sqlalchemy.dialects import postgresql
        compiled = query.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True}
        )
        logger.debug(f"SQL: {compiled}")

        # EXPLAIN ANALYZE 실행
        explain_query = text(f"EXPLAIN (ANALYZE, BUFFERS) {str(compiled)}")
        result = self.db.execute(explain_query)
        logger.debug("Execution Plan:")
        for row in result:
            logger.debug(row[0])

    return query.all()
```

## 권장 사항

1. **개발 환경**: `echo=True` 또는 이벤트 리스너 사용
2. **프로덕션 환경**: 느린 쿼리만 로깅 (1초 이상)
3. **성능 분석**: PostgreSQL의 `pg_stat_statements` 확장 사용
4. **모니터링**: APM 도구 (예: Datadog, New Relic) 사용

## 참고

- SQLAlchemy 공식 문서: https://docs.sqlalchemy.org/en/14/core/events.html
- PostgreSQL 로깅: https://www.postgresql.org/docs/current/runtime-config-logging.html
