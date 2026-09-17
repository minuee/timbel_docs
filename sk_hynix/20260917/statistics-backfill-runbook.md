# Statistics 통계 데이터 백필 작업 문서

작성일: 2026-09-17

Content 테이블을 재집계해서 `Statistics` 테이블에 일별 통계를 채우는 작업이다.
도커 MariaDB에 SQL 파일을 그대로 흘려넣는 방식이며, 소스 수정은 필요 없다.

관련 파일

| 파일 | 역할 |
|---|---|
| `docs/statistics-select.sql` | 읽기 전용. 집계 조회 · 타임존 검증 · 중복 확인 |
| `docs/statistics-backfill.sql` | 쓰기. 대상 기간 DELETE 후 재집계 INSERT (트랜잭션) |
| `docs/statistics-backfill-simple.sql` | 위의 무-트랜잭션 · 무-변수 버전. 날짜가 쿼리에 직접 박혀 있다 |

---

## 1. 배경

### 집계 단위

`dateKst`(일자) / `workspaceId`(워크스페이스) / `creatorId`(등록자) 세 개로 묶는다.
bo-api 배치가 쓰는 키와 같다 (`contentStatisticsFormat()`의 `${creatorId}_${workspaceId}_${dateKst}`).

### 현재 운영 상태

- bo-api의 BullMQ 잡 `daily-statistics`가 **매일 02:00 KST**에 돌면서 전날 데이터를 쌓는다 (cron은 `BATCH_STATISTICS_CRON`, 기본 `0 2 * * *`)
- 2026-09-10부터 데이터가 일부 쌓여 있다
- 배치는 upsert가 아니다. 해당 날짜 데이터가 하나라도 있으면 `HttpError(2109)`를 던지고 **그날치 전체를 건너뛴다** (`statistics.service.js:295-299`). 그래서 재실행으로는 메울 수 없고 이 백필이 필요하다

### 집계 규칙 (배치와 동일하게 맞춤)

- 대상: `workspace.domain <> 'global'`, `isDeleted = 0`, `isRecycle = 0`
- `Content.duration`은 **밀리초** 저장 → 1000으로 나눠 초로 환산
- `transcribeStatus`: `DONE` / `ERROR` / 그 외 전부 Other
- `isMobile = 1`인 건은 mobile 카운트·초에도 가산
- `weekNumber`는 `WEEK(dateKst, 1)` — `date.util.js`의 `getWeekNumber()`가 MariaDB `WEEK(date,1)` 호환이라고 명시돼 있다

---

## 2. 실행 전에 알아야 할 것 3가지

### (1) UPSERT가 아니라 DELETE + INSERT다

`Statistics` 테이블에는 유니크 제약이 없다. PK가 `id` autoincrement 하나뿐이라
`ON DUPLICATE KEY UPDATE`도 `REPLACE INTO`도 중복을 판정할 키가 없다.
(`statistics.prisma`에 보이는 `@@unique([createDate, memberId])`는 다른 테이블인 `DailyStats` 것이다)

그래서 **대상 기간을 통째로 지우고 다시 넣는다.** 한 트랜잭션으로 묶여 있다.
결과는 upsert와 같고, 그 사이 삭제·휴지통 이동된 Content까지 정확히 반영된다.
대신 `@fromKst` / `@toKst` 범위를 잘못 주면 그 기간이 날아가므로 실행 전 반드시 확인한다.

### (2) 타임존 전제

`dateKst`를 `CONVERT_TZ(c.createAt, '+00:00', '+09:00')`로 계산한다.
**DB에 UTC 저장 + 배치 서버 TZ가 KST**라는 전제다.

근거: `date.util.js:148-154`의 `formatDate()`가 KST 자정을 `.utc().toISOString()`으로 바꿔 조회 범위를 만들고,
집계할 때는 `dayjs(createAt).format('YYYY-MM-DD')`로 로컬(KST) 날짜를 쓴다.

이 전제는 **아래 3단계의 [B] 검증으로 실제 데이터에서 확인**한다. 추측으로 넘어가지 않는다.

### (3) duration 버킷 기준이 배치와 다르다

배치 코드(`statistics.service.js:275-287`)의 경계값이 필드명과 어긋나 있다.

| 필드 | 배치의 실제 경계 | 필드명이 뜻하는 것 | 이 SQL이 쓰는 값 |
|---|---|---|---|
| duration0_1Min | < 1분 | 0~1분 | < 60000 |
| duration1_30Min | < **3분** | 1~30분 | < 1800000 |
| duration30_60Min | < **6분** | 30~60분 | < 3600000 |
| duration60_120Min | < **12분** | 60~120분 | < 7200000 |
| duration120_180Min | < **18분** | 120~180분 | < 10800000 |
| durationOver180Min | 18분 초과 | 180분 초과 | >= 10800000 |

30분(1800000ms)을 넣어야 할 자리에 3분(180000ms)이 들어가 있다. 0 하나가 빠진 형태다.
현재 배치로는 18분 넘는 콘텐츠가 전부 "180분 초과"로 잡힌다.

**이 SQL은 필드명대로(1/30/60/120/180분) 넣는다.**
소스는 건드리지 않기로 했으므로, 백필한 구간과 이후 배치가 쌓는 행은 버킷 기준이 서로 다르다.
`duration*` 컬럼을 그래프로 쓸 때 이 점을 감안해야 한다. 나머지 컬럼은 전부 동일하다.

---

## 3. 실행 순서

`<container>` `<user>` `<pass>` `<db>`는 환경에 맞게 바꾼다.

### 0단계 — 엔진 확인 + 백업

`statistics-backfill.sql`은 `START TRANSACTION` ~ `COMMIT`으로 묶여 있다.
MariaDB에서 트랜잭션은 **InnoDB에서만** 동작하고, MyISAM이면 에러 없이 조용히 무시된다.

```sql
SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('Statistics', 'Content', 'Workspace');
```

- 셋 다 `InnoDB` → `statistics-backfill.sql` 사용
- 아니거나 트랜잭션을 안 쓰고 싶다 → `statistics-backfill-simple.sql` 사용
  (DELETE 1문장 + INSERT 1문장. 날짜가 쿼리에 직접 박혀 있어 한 문장씩 손으로 실행하기 좋다.
  대신 자동 롤백이 없으니 **DELETE만 하고 멈추면 그 기간이 비어 있는 상태로 남는다.** 백업 필수)

나머지 문법(`SET @x`, `CONVERT_TZ`, `SUM(조건식)`, `IF()`, `WEEK(date,1)`)은 모두 MariaDB 표준 지원이라 문제없다.
`CONVERT_TZ`는 `'+09:00'` 같은 오프셋 형식이라 `mysql.time_zone` 테이블이 로드돼 있지 않아도 동작한다.

#### 백업 (권장)

DELETE가 들어가므로 대상 기간을 먼저 떠둔다.

```bash
docker exec <container> mysqldump -u<user> -p<pass> <db> Statistics \
  --where="dateKst >= '2026-09-10'" > statistics-backup-$(date +%Y%m%d).sql
```

### 1단계 — 기간 설정

두 SQL 파일 **모두** 상단의 변수를 같은 값으로 맞춘다.

```sql
SET @fromKst = '2026-09-10';   -- 포함
SET @toKst   = '2026-09-17';   -- 제외
```

`@toKst`는 **제외**다. 어제까지만 채우려면 오늘 날짜를 넣는다.
배치가 02시에 도니 그 시간대를 피하고, `@toKst`를 오늘로 두면 배치 영역과 겹치지 않는다.

### 2단계 — 조회·검증 (읽기 전용)

```bash
docker exec -i <container> mysql -u<user> -p<pass> <db> < docs/statistics-select.sql
```

세 개 결과가 순서대로 나온다.

- **[A] 집계 결과** — 들어갈 데이터를 미리 눈으로 확인한다
- **[B] 타임존 검증** — ⭐ **0건이어야 한다.** 기존에 쌓인 행과 재집계 값을 대조한다
  - 0건 → 전제가 맞다. 그대로 진행
  - 날짜가 하루씩 밀려 나온다 → 두 SQL 파일에서 `CONVERT_TZ(c.createAt, '+00:00', '+09:00')`를 `c.createAt`으로 바꾸고 다시 확인
- **[C] 중복 확인** — 배치가 같은 날 두 번 돌아 중복이 남았는지 본다. 백필이 어차피 정리하지만 규모는 미리 알아두는 게 좋다

### 3단계 — 백필 실행

[B]가 0건인 것을 확인한 뒤에 돌린다.

```bash
docker exec -i <container> mysql -u<user> -p<pass> <db> < docs/statistics-backfill.sql
```

DELETE → INSERT → COMMIT 후, 날짜별 행 수와 합계가 출력된다.

### 4단계 — 결과 확인

3단계 끝의 출력으로 대부분 확인되지만, 다시 보려면 `statistics-select.sql`의 [B]를 한 번 더 돌린다.
이번에도 0건이면 정상이다 (duration 버킷은 비교 대상에서 빠져 있다).

---

## 4. 테스트하는 법

운영 데이터를 건드리기 전에 좁은 범위로 먼저 돌려볼 수 있다.

**하루만 돌려보기**

```sql
SET @fromKst = '2026-09-10';
SET @toKst   = '2026-09-11';
```

이 상태로 select → backfill → select 순으로 돌리면 하루치만 영향을 받는다.
문제없으면 범위를 넓혀서 다시 실행한다. DELETE + INSERT라 **같은 구간을 몇 번 돌려도 결과가 같다.**

**아직 데이터가 없는 미래 구간으로 확인하기**

`Statistics`에 행이 없는 날짜를 잡으면 DELETE가 아무것도 지우지 않으므로 INSERT 동작만 따로 볼 수 있다.

---

## 5. 문제가 생기면

**중간에 실패했을 때** — `statistics-backfill.sql`은 `START TRANSACTION` ~ `COMMIT`으로 묶여 있어 자동 롤백된다. DELETE만 되고 INSERT가 안 되는 일은 없다.
`mysql < file.sql` 파이프 실행은 에러가 나면 거기서 멈추므로 COMMIT까지 못 가고 연결 종료 시 롤백된다. (`--force` 옵션은 에러를 무시하고 계속 진행하니 쓰지 말 것)

`statistics-backfill-simple.sql`은 트랜잭션이 없다. DELETE 후 INSERT가 실패하면 그 기간이 **비어 있는 채로 남는다.** 이때는 INSERT만 다시 실행하면 된다 (지울 행이 이미 없으므로 DELETE는 건너뛰어도 된다).

**COMMIT까지 됐는데 결과가 이상할 때** — 0단계 백업으로 복구한다.

```bash
# 잘못 들어간 구간 제거 후
docker exec -i <container> mysql -u<user> -p<pass> <db> < statistics-backup-YYYYMMDD.sql
```

**[B] 검증이 계속 안 맞을 때** — 차이가 나는 행의 `dateKst`를 보고 판단한다.
- 날짜가 하루씩 밀린다 → 타임존 문제. `CONVERT_TZ` 제거
- 특정 워크스페이스만 안 맞는다 → `domain = 'global'` 필터나 `isDeleted` / `isRecycle` 상태가 집계 시점 이후 바뀐 경우일 수 있다. 이건 정상이며 백필 값이 더 정확하다
- 건수는 맞는데 `totalSeconds`만 다르다 → 반올림 차이. 배치는 행마다 누적 후 마지막에 `Math.round`, SQL은 `ROUND(SUM(...)/1000)`으로 동일하게 맞췄으므로 1초 이상 차이는 나지 않아야 한다

---

## 6. 남은 일 (이번 작업 범위 밖)

- `statistics.service.js:275-287`의 duration 버킷 경계값 수정. 고치고 나면 그 전에 쌓인 구간은 이 SQL로 다시 백필해야 기준이 통일된다
- `Statistics`에 `(dateKst, workspaceId, creatorId)` 유니크 인덱스 추가. 있으면 진짜 upsert가 가능해지고 배치의 "이미 있으면 통째로 건너뛰기" 로직도 걷어낼 수 있다. 단 `workspaceId` / `creatorId`가 nullable이라(`onDelete: SetNull`) NULL 행은 MySQL 유니크가 중복을 막지 못한다는 점은 따로 봐야 한다
