# DBeaver 로 앱 DB(SQLite) 보기 — 망분리 PC

앱 DB 는 SQLite 파일 하나다. 서버·계정·비밀번호 없음.

| 무엇 | 위치 |
|---|---|
| DB 파일 | `C:\Users\<사용자>\AppData\Roaming\timbloRecApp\app.db` (탐색기 주소창에 `%APPDATA%\timbloRecApp`) |
| 드라이버 | 이 폴더의 `sqlite-jdbc-3.53.4.0.jar` (Maven Central 원본, SHA-1 확인, Windows x64 dll 포함) |

## 1. 드라이버 jar 놓기
`sqlite-jdbc-3.53.4.0.jar` 를 회사 PC 의 아무 고정 폴더에 둔다. 예: `C:\dbeaver-drivers\`

## 2. DBeaver 에 드라이버 지정 (최초 1회)
1. 메뉴 **데이터베이스(Database) → 드라이버 관리자(Driver Manager)**
2. 목록에서 **SQLite** 선택 → **편집(Edit)**
3. **라이브러리(Libraries)** 탭
   - 기존 항목(인터넷에서 받으려는 `org.xerial:sqlite-jdbc` 등)은 선택 → **삭제(Delete)**
   - **파일 추가(Add File)** → 1번의 jar 선택
4. **클래스 찾기(Find Class)** → `org.sqlite.JDBC` 선택 → **확인(OK)**

> 처음 연결 때 "드라이버 파일 다운로드" 창이 뜨면 취소하고 위 순서대로 하면 된다.

## 3. 연결 만들기
1. **새 연결(플러그 아이콘)** → **SQLite** → 다음
2. **Path**: `C:\Users\<사용자>\AppData\Roaming\timbloRecApp\app.db`
3. (권장) **연결 설정 → 일반(General)** 에서 **읽기 전용 연결(Read-only connection)** 체크
4. **완료** → 왼쪽 트리에서 `Tables` 펼치기

## 4. 자주 쓰는 조회
```sql
-- 업로드 리스트(오른쪽 위 버튼)와 같은 내용
SELECT j.job_id, r.file_name, r.file_path, r.created_at
FROM jobs j JOIN recordings r ON r.id = j.recording_id
WHERE j.is_deleted = 0
ORDER BY r.created_at DESC;

-- 녹음 전체 + 업로드 설정(언어·발화자·제목·템플릿)
SELECT r.id, r.file_name, r.file_path, r.created_at, s.lang, s.attendee_num, s.title, s.template_id
FROM recordings r LEFT JOIN summaries s ON s.recording_id = r.id
ORDER BY r.id DESC;
```

## 주의
- **수정·삭제는 앱을 끄고** 한다. 앱이 쓰는 중이면 잠금 충돌이 날 수 있다. 조회만이면 읽기 전용으로.
- 다른 곳으로 **복사해서 볼 때는 3개 파일을 함께**: `app.db`, `app.db-wal`, `app.db-shm`
  (최근 변경은 `-wal` 에 먼저 쌓인다. `app.db` 하나만 복사하면 최근 데이터가 빠질 수 있다)
- 날짜(`created_at`)는 `2025-10-31 17:47:20` 같은 글자로 저장되어 있다.
- `app.db` 의 **만든 날짜**를 보면 이 PC 에서 언제부터 쓰인 DB 인지 알 수 있다(작년 데이터가 보이는 이유 확인용).
