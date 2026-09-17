-- =============================================================================
-- statistics-backfill-simple.sql
--   statistics-backfill.sql 의 무-트랜잭션 · 무-변수 버전.
--   트랜잭션이 안 먹는 환경(테이블 엔진이 MyISAM 등)이나
--   한 문장씩 손으로 실행하고 싶을 때 쓴다.
--
--   [1] 과 [2] 를 순서대로 실행하면 된다. 결과는 backfill.sql 과 동일하다.
--   날짜는 두 문장 모두에 직접 박혀 있으니 한쪽만 바꾸지 않도록 주의.
--
-- 기간: 2026-09-10 (포함) ~ 2026-09-17 (제외)
--   ※ 바꿀 때는 이 파일 안의 날짜 4군데를 전부 수정한다
--     - [1] DELETE 의 2군데
--     - [2] INSERT 의 2군데
--
-- 실행:
--   docker exec -i <container> mysql -u<user> -p<pass> <db> < docs/statistics-backfill-simple.sql
--   또는 [1] 실행 → 결과 확인 → [2] 실행
--
-- ★ [1] 을 돌리고 [2] 를 안 돌리면 해당 기간 통계가 비어 있는 상태로 남는다.
--   트랜잭션이 없으니 자동 롤백이 안 된다. 반드시 [2] 까지 실행할 것.
--   실행 전 백업을 권장한다:
--     docker exec <container> mysqldump -u<user> -p<pass> <db> Statistics \
--       --where="dateKst >= '2026-09-10'" > statistics-backup.sql
-- =============================================================================


-- -----------------------------------------------------------------------------
-- [1] 대상 기간 기존 행 삭제
-- -----------------------------------------------------------------------------
DELETE FROM `Statistics`
WHERE dateKst >= '2026-09-10'
  AND dateKst <  '2026-09-17';


-- -----------------------------------------------------------------------------
-- [2] Content 에서 재집계해 삽입
-- -----------------------------------------------------------------------------
INSERT INTO `Statistics` (
    yearKst, monthKst, dayKst, weekNumber, dateKst,
    workspaceId, creatorId,
    totalContentCount, totalSeconds, mobileContentCount, mobileSeconds,
    transcribeDoneCount, transcribeErrorCount, transcribeOtherCount,
    duration0_1Min, duration1_30Min, duration30_60Min,
    duration60_120Min, duration120_180Min, durationOver180Min,
    createAt, updateAt
)
SELECT
    YEAR(g.dateKst),
    MONTH(g.dateKst),
    DAY(g.dateKst),
    WEEK(g.dateKst, 1),
    DATE_FORMAT(g.dateKst, '%Y-%m-%d'),
    g.workspaceId,
    g.creatorId,
    g.totalContentCount,
    g.totalSeconds,
    g.mobileContentCount,
    g.mobileSeconds,
    g.transcribeDoneCount,
    g.transcribeErrorCount,
    g.transcribeOtherCount,
    g.duration0_1Min,
    g.duration1_30Min,
    g.duration30_60Min,
    g.duration60_120Min,
    g.duration120_180Min,
    g.durationOver180Min,
    NOW(),
    NOW()
FROM (
    SELECT
        DATE(CONVERT_TZ(c.createAt, '+00:00', '+09:00'))         AS dateKst,
        c.workspaceId,
        c.creatorId,
        COUNT(*)                                                 AS totalContentCount,
        ROUND(SUM(c.duration) / 1000)                            AS totalSeconds,
        SUM(c.isMobile = 1)                                      AS mobileContentCount,
        ROUND(SUM(IF(c.isMobile = 1, c.duration, 0)) / 1000)     AS mobileSeconds,
        SUM(c.transcribeStatus = 'DONE')                         AS transcribeDoneCount,
        SUM(c.transcribeStatus = 'ERROR')                        AS transcribeErrorCount,
        SUM(c.transcribeStatus NOT IN ('DONE', 'ERROR'))         AS transcribeOtherCount,
        SUM(c.duration <     60000)                              AS duration0_1Min,
        SUM(c.duration >=    60000 AND c.duration <  1800000)    AS duration1_30Min,
        SUM(c.duration >=  1800000 AND c.duration <  3600000)    AS duration30_60Min,
        SUM(c.duration >=  3600000 AND c.duration <  7200000)    AS duration60_120Min,
        SUM(c.duration >=  7200000 AND c.duration < 10800000)    AS duration120_180Min,
        SUM(c.duration >= 10800000)                              AS durationOver180Min
    FROM `Content` c
    JOIN `Workspace` w ON w.id = c.workspaceId
    WHERE w.domain <> 'global'
      AND c.isDeleted = 0
      AND c.isRecycle = 0
      AND c.createAt >= CONVERT_TZ('2026-09-10 00:00:00', '+09:00', '+00:00')
      AND c.createAt <  CONVERT_TZ('2026-09-17 00:00:00', '+09:00', '+00:00')
    GROUP BY 1, 2, 3
) g;


-- -----------------------------------------------------------------------------
-- [3] 결과 확인
-- -----------------------------------------------------------------------------
SELECT
    dateKst,
    COUNT(*)                AS rows_inserted,
    SUM(totalContentCount)  AS totalContentCount,
    SUM(totalSeconds)       AS totalSeconds
FROM `Statistics`
WHERE dateKst >= '2026-09-10'
  AND dateKst <  '2026-09-17'
GROUP BY dateKst
ORDER BY dateKst;
