-- =============================================================================
-- statistics-select.sql
--   Content -> Statistics 일별 집계 조회 (읽기 전용, 데이터 변경 없음)
--   그룹 기준: dateKst(일자) / workspaceId(워크스페이스) / creatorId(등록자)
--
-- 실행:
--   docker exec -i <mariadb-container> mysql -u<user> -p<pass> <db> < docs/statistics-select.sql
--
-- 집계 규칙은 bo-api 배치와 동일하게 맞췄다
--   (bo-api-2-release-src/src/services/statistics.service.js  contentStatisticsFormat)
--   - 대상: workspace.domain <> 'global', isDeleted = 0, isRecycle = 0
--   - Content.duration 단위는 ms -> 초로 환산해서 저장
--   - transcribeStatus: DONE / ERROR / 그 외 전부 Other
--   - dateKst: createAt(UTC 저장) 을 KST 로 변환한 날짜
--   ※ duration 구간 버킷만 배치와 다르다. 배치 코드는 경계가 3/6/12/18분으로
--     필드명과 어긋나 있어, 여기서는 필드명대로 1/30/60/120/180분을 쓴다.
-- =============================================================================

SET @fromKst = '2026-09-10';   -- 조회 시작일 (포함)
SET @toKst   = '2026-09-17';   -- 조회 종료일 (제외)


-- -----------------------------------------------------------------------------
-- [A] 일자 / 워크스페이스 / 등록자별 집계
-- -----------------------------------------------------------------------------
SELECT
    DATE(CONVERT_TZ(c.createAt, '+00:00', '+09:00'))            AS dateKst,
    c.workspaceId,
    c.creatorId,
    COUNT(*)                                                    AS totalContentCount,
    ROUND(SUM(c.duration) / 1000)                               AS totalSeconds,
    SUM(c.isMobile = 1)                                         AS mobileContentCount,
    ROUND(SUM(IF(c.isMobile = 1, c.duration, 0)) / 1000)        AS mobileSeconds,
    SUM(c.transcribeStatus = 'DONE')                            AS transcribeDoneCount,
    SUM(c.transcribeStatus = 'ERROR')                           AS transcribeErrorCount,
    SUM(c.transcribeStatus NOT IN ('DONE', 'ERROR'))            AS transcribeOtherCount,
    SUM(c.duration <     60000)                                 AS duration0_1Min,
    SUM(c.duration >=    60000 AND c.duration <  1800000)       AS duration1_30Min,
    SUM(c.duration >=  1800000 AND c.duration <  3600000)       AS duration30_60Min,
    SUM(c.duration >=  3600000 AND c.duration <  7200000)       AS duration60_120Min,
    SUM(c.duration >=  7200000 AND c.duration < 10800000)       AS duration120_180Min,
    SUM(c.duration >= 10800000)                                 AS durationOver180Min
FROM `Content` c
JOIN `Workspace` w ON w.id = c.workspaceId
WHERE w.domain <> 'global'
  AND c.isDeleted = 0
  AND c.isRecycle = 0
  AND c.createAt >= CONVERT_TZ(CONCAT(@fromKst, ' 00:00:00'), '+09:00', '+00:00')
  AND c.createAt <  CONVERT_TZ(CONCAT(@toKst,   ' 00:00:00'), '+09:00', '+00:00')
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;


-- -----------------------------------------------------------------------------
-- [B] 타임존 전제 검증 — 이미 쌓인 Statistics 행과 대조
--
--     dateKst 를 CONVERT_TZ(createAt, '+00:00', '+09:00') 로 계산한 것은
--     "DB 에 UTC 저장 + 배치 서버 TZ 가 KST" 라는 전제다.
--     (근거: date.util.js formatDate() 가 KST 자정을 .utc().toISOString() 으로
--      바꿔 조회하고, 집계 시엔 dayjs(createAt).format('YYYY-MM-DD') 로 로컬 날짜를 쓴다)
--
--     결과가 0건이면 전제가 맞다.
--     날짜가 하루씩 밀려 나오면 이 파일과 backfill 쪽의 CONVERT_TZ 를 걷어내고
--     DATE(c.createAt) 로 바꿔야 한다.
--
--     duration 버킷은 기준을 바꿨으므로 비교 대상에서 뺐다.
-- -----------------------------------------------------------------------------
SELECT
    s.dateKst,
    s.workspaceId,
    s.creatorId,
    s.totalContentCount     AS old_totalContentCount,
    g.totalContentCount     AS new_totalContentCount,
    s.totalSeconds          AS old_totalSeconds,
    g.totalSeconds          AS new_totalSeconds,
    s.transcribeDoneCount   AS old_doneCount,
    g.transcribeDoneCount   AS new_doneCount
FROM `Statistics` s
LEFT JOIN (
    SELECT
        DATE_FORMAT(DATE(CONVERT_TZ(c.createAt, '+00:00', '+09:00')), '%Y-%m-%d') AS dateKst,
        c.workspaceId,
        c.creatorId,
        COUNT(*)                                         AS totalContentCount,
        ROUND(SUM(c.duration) / 1000)                    AS totalSeconds,
        SUM(c.transcribeStatus = 'DONE')                 AS transcribeDoneCount
    FROM `Content` c
    JOIN `Workspace` w ON w.id = c.workspaceId
    WHERE w.domain <> 'global'
      AND c.isDeleted = 0
      AND c.isRecycle = 0
      AND c.createAt >= CONVERT_TZ(CONCAT(@fromKst, ' 00:00:00'), '+09:00', '+00:00')
      AND c.createAt <  CONVERT_TZ(CONCAT(@toKst,   ' 00:00:00'), '+09:00', '+00:00')
    GROUP BY 1, 2, 3
) g
  ON  g.dateKst     = s.dateKst
  AND g.workspaceId = s.workspaceId
  AND g.creatorId   = s.creatorId
WHERE s.dateKst >= @fromKst
  AND s.dateKst <  @toKst
  AND (g.totalContentCount IS NULL
       OR s.totalContentCount   <> g.totalContentCount
       OR s.totalSeconds        <> g.totalSeconds
       OR s.transcribeDoneCount <> g.transcribeDoneCount)
ORDER BY 1, 2, 3;


-- -----------------------------------------------------------------------------
-- [C] 중복 행 확인
--
--     Statistics 에는 유니크 제약이 없다(PK 는 id autoincrement 뿐).
--     배치가 같은 날 두 번 돌았다면 중복이 남아 있을 수 있다.
--     backfill 스크립트가 DELETE 로 정리하지만, 미리 규모를 보려면 이걸 먼저 돌린다.
-- -----------------------------------------------------------------------------
SELECT
    dateKst,
    workspaceId,
    creatorId,
    COUNT(*) AS cnt
FROM `Statistics`
WHERE dateKst >= @fromKst
  AND dateKst <  @toKst
GROUP BY 1, 2, 3
HAVING cnt > 1
ORDER BY cnt DESC, 1, 2, 3;
