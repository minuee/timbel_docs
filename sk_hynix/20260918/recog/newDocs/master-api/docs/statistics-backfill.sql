-- =============================================================================
-- statistics-backfill.sql
--   Content -> Statistics 일별 통계 백필 (쓰기)
--   그룹 기준: dateKst(일자) / workspaceId(워크스페이스) / creatorId(등록자)
--
-- 실행:
--   docker exec -i <mariadb-container> mysql -u<user> -p<pass> <db> < docs/statistics-backfill.sql
--
-- ★ 먼저 docs/statistics-select.sql 의 [B] 검증을 돌려 타임존 전제를 확인할 것.
--
-- ★ UPSERT 가 아니라 DELETE + INSERT 다.
--   Statistics 에는 유니크 제약이 없다 — PK 가 id(autoincrement) 하나뿐이라
--   ON DUPLICATE KEY UPDATE / REPLACE INTO 가 중복을 판정할 키가 없다.
--   (statistics.prisma 의 @@unique 는 다른 테이블인 DailyStats 것이다)
--   따라서 대상 기간을 지우고 다시 넣는다. 한 트랜잭션으로 묶여 있고,
--   결과는 upsert 와 같으며 그 사이 삭제·휴지통 이동된 Content 까지 정확히 반영된다.
--
-- ★ 배치와 겹치지 않게 실행할 것.
--   bo-api 의 daily-statistics 잡이 매일 02:00 KST 에 돈다(BATCH_STATISTICS_CRON).
--   @toKst 를 오늘 날짜로 두면 어제까지만 건드린다.
--
-- ★ duration 구간 버킷 기준이 배치와 다르다.
--   배치 코드(statistics.service.js:275-287)는 경계가 3/6/12/18분으로 필드명과
--   어긋나 있다. 여기서는 필드명대로 1/30/60/120/180분을 쓴다.
--   배치 코드도 같이 고쳐야 이후 쌓이는 행과 일관된다.
-- =============================================================================

SET @fromKst = '2026-09-10';   -- 백필 시작일 (포함)
SET @toKst   = '2026-09-17';   -- 백필 종료일 (제외)

START TRANSACTION;

-- -----------------------------------------------------------------------------
-- 1) 대상 기간 기존 행 제거
--    dateKst 는 'YYYY-MM-DD' 문자열이라 사전순 = 날짜순이다.
-- -----------------------------------------------------------------------------
DELETE FROM `Statistics`
WHERE dateKst >= @fromKst
  AND dateKst <  @toKst;

-- -----------------------------------------------------------------------------
-- 2) Content 에서 재집계해 삽입
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
    WEEK(g.dateKst, 1),                        -- date.util.js getWeekNumber() 가 WEEK(date,1) 호환이라 명시돼 있다
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
      AND c.createAt >= CONVERT_TZ(CONCAT(@fromKst, ' 00:00:00'), '+09:00', '+00:00')
      AND c.createAt <  CONVERT_TZ(CONCAT(@toKst,   ' 00:00:00'), '+09:00', '+00:00')
    GROUP BY 1, 2, 3
) g;

COMMIT;

-- -----------------------------------------------------------------------------
-- 3) 결과 확인
-- -----------------------------------------------------------------------------
SELECT
    dateKst,
    COUNT(*)                    AS rows_inserted,
    SUM(totalContentCount)      AS totalContentCount,
    SUM(totalSeconds)           AS totalSeconds
FROM `Statistics`
WHERE dateKst >= @fromKst
  AND dateKst <  @toKst
GROUP BY dateKst
ORDER BY dateKst;
