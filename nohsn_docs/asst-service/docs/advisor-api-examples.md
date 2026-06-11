# Advisor API 사용 예시

## 공지사항 관리 API

### 1. 공지사항 생성

```bash
POST /api/asst/v1/notices
Content-Type: application/json

{
  "name": "시스템 점검 안내",
  "is_urgent": true,
  "content": "2024년 1월 15일 오전 2시부터 4시까지 시스템 점검이 예정되어 있습니다.",
  "remind_time": "2024-01-14T20:00:00Z",
  "creator_key": "admin_001",
  "target_key": "all_users",
  "send_socket": true
```

**주요 필드:**

- `send_socket`: 공지사항 생성 시 소켓 브로드캐스트 여부 (기본값: true)
  - `true`: 생성된 공지사항이 연결된 모든 소켓 클라이언트에게 즉시 브로드캐스트됩니다.
  - `false`: 소켓 브로드캐스트를 건너뜁니다.
    }

````

**주요 필드:**

- `send_socket`: true로 설정하면 생성된 공지사항이 연결된 모든 소켓 클라이언트에게 즉시 브로드캐스트됩니다.

### 2. 공지사항 목록 조회 (Pagination 지원)

```bash
# 기본 조회 (첫 번째 페이지, 10개 항목)
GET /api/asst/v1/notices

# 특정 페이지 조회
GET /api/asst/v1/notices?page=2&limit=20

# 첫 번째 페이지, 5개 항목
GET /api/asst/v1/notices?page=1&limit=5
````

**응답 형식:**

```json
{
  "data": [
    {
      "id": "notices_uuid",
      "name": "공지사항 제목",
      "is_urgent": false,
      "content": "공지사항 내용",
      "remind_time": null,
      "creator_key": "admin_001",
      "target_key": "all_users",
      "create_at": "2024-01-18T10:00:00Z",
      "update_at": "2024-01-18T10:00:00Z",
      "noticeReads": []
    }
  ],
  "total": 50,
  "page": 1,
  "limit": 10,
  "totalPages": 5,
  "hasNext": true,
  "hasPrev": false
}
```

### 3. 특정 공지사항 조회 (자동 읽음 처리)

```bash
# 기본 조회 (읽음 처리 없음)
GET /api/asst/v1/notices/notices_12345678-1234-1234-1234-123456789012

# user_key 제공 시 자동 읽음 처리
GET /api/asst/v1/notices/notices_12345678-1234-1234-1234-123456789012?user_key=user_001
```

### 4. 공지사항 수정

```bash
PATCH /api/asst/v1/notices/notices_12345678-1234-1234-1234-123456789012
Content-Type: application/json

{
  "name": "시스템 점검 안내 (수정)",
  "is_urgent": false,
  "content": "시스템 점검이 완료되었습니다."
}
```

### 5. 공지사항 삭제

```bash
DELETE /api/asst/v1/notices/notices_12345678-1234-1234-1234-123456789012
```

## 공지사항 읽음 처리 API

### 1. 공지사항 읽음 처리

```bash
POST /api/asst/v1/notices-reads
Content-Type: application/json

{
  "notices_id": "notices_12345678-1234-1234-1234-123456789012",
  "user_key": "user_001"
}
```

### 2. 특정 공지사항의 읽음 목록 조회

```bash
GET /api/asst/v1/notices/notices_12345678-1234-1234-1234-123456789012/reads
```

### 3. 사용자가 읽은 공지사항 목록 조회

```bash
GET /api/asst/v1/notices-reads/user/user_001
```

### 4. 사용자가 읽지 않은 공지사항 목록 조회

```bash
GET /api/asst/v1/notices/unread/user_001
```

## Swagger 문서

API 문서는 다음 URL에서 확인할 수 있습니다:

```
http://localhost:3000/api/asst/v1/doc
```

## 데이터베이스 스키마

### notices 테이블

- `id`: 공지사항 고유 ID (형식: "notices\_${uuid}")
- `name`: 공지사항 제목
- `is_urgent`: 긴급 여부
- `content`: 공지사항 내용
- `remind_time`: 알림 시간
- `creator_key`: 생성자 키
- `target_key`: 대상 키
- `create_at`: 생성일
- `update_at`: 수정일

### notices_reads 테이블

- `id`: 읽음 처리 고유 ID (형식: "notices*reads*${uuid}")
- `notices_id`: 공지사항 ID (FK)
- `user_key`: 사용자 키
- `create_at`: 생성일
- `update_at`: 수정일

## 마이그레이션 실행

데이터베이스 스키마를 생성하려면 다음 SQL 스크립트를 실행하세요:

```bash
psql -h localhost -U your_username -d your_database -f migrations/create_advisor_schema.sql
```

## Socket.IO 실시간 통신

### 연결 방법

```javascript
import { io } from 'socket.io-client';

const socket = io('http://localhost:3000');

socket.on('connect', () => {
  console.log('Connected to server:', socket.id);
});

socket.on('disconnect', () => {
  console.log('Disconnected from server');
});

// 서버에서 연결 확인 메시지 수신
socket.on('connection-confirmed', (data) => {
  console.log('Connection confirmed:', data);
  // data.message: 'Successfully connected to server'
  // data.clientId: socket ID
  // data.timestamp: 연결 시간
});
```

### 메시지 타입

```typescript
enum SocketMessageType {
  NOTICE = 'NOTICE', // 공지사항
}
```

### 공지사항 브로드캐스트 수신

```javascript
// 공지사항 브로드캐스트 수신
socket.on('notice-broadcast', (data) => {
  console.log('New notice received:', data);
  // data.type === 'NOTICE'
  // data.message contains notice details
});
```

### 일반 메시지 전송

```javascript
// 일반 메시지 전송 (NOTICE 타입만 지원)
socket.emit('message', {
  type: 'NOTICE',
  message: {
    /* notice data */
  },
});
```

## 메모 그룹 관리 API

### 1. 메모 그룹 생성

```bash
POST /api/asst/v1/memo-groups
Content-Type: application/json

{
  "name": "개발 메모",
  "user_key": "user_001"
}
```

### 2. 모든 메모 그룹 조회

```bash
GET /api/asst/v1/memo-groups
```

### 3. 사용자별 메모 그룹 조회

```bash
GET /api/asst/v1/memo-groups/user/user_001
```

### 4. 특정 메모 그룹 조회

```bash
GET /api/asst/v1/memo-groups/memo_groups_12345678-1234-1234-1234-123456789012
```

### 5. 메모 그룹 수정

```bash
PATCH /api/asst/v1/memo-groups/memo_groups_12345678-1234-1234-1234-123456789012
Content-Type: application/json

{
  "name": "수정된 메모 그룹명"
}
```

### 6. 메모 그룹 삭제

```bash
DELETE /api/asst/v1/memo-groups/memo_groups_12345678-1234-1234-1234-123456789012
```

## 메모 관리 API

### 1. 메모 생성

```bash
POST /api/asst/v1/memos
Content-Type: application/json

{
  "memo_groups_id": "memo_groups_12345678-1234-1234-1234-123456789012",
  "user_key": "user_001",
  "name": "중요한 메모",
  "content": "이것은 중요한 내용입니다."
}
```

### 2. 모든 메모 조회

```bash
GET /api/asst/v1/memos
```

### 3. 사용자별 메모 조회

```bash
GET /api/asst/v1/memos/user/user_001
```

### 4. 메모 그룹별 메모 조회

```bash
GET /api/asst/v1/memos/group/memo_groups_12345678-1234-1234-1234-123456789012
```

### 5. 특정 메모 조회

```bash
GET /api/asst/v1/memos/memos_12345678-1234-1234-1234-123456789012
```

### 6. 메모 수정

```bash
PATCH /api/asst/v1/memos/memos_12345678-1234-1234-1234-123456789012
Content-Type: application/json

{
  "name": "수정된 메모 제목",
  "content": "수정된 메모 내용"
}
```

### 7. 메모 삭제

```bash
DELETE /api/asst/v1/memos/memos_12345678-1234-1234-1234-123456789012
```

## 키워드 감지 관리 API

### 1. 키워드 감지 생성

```bash
POST /api/asst/v1/keyword-detects
Content-Type: application/json

{
  "keyword": "긴급",
  "type": "urgent",
  "creator_key": "admin_001"
}
```

### 2. 키워드 감지 목록 조회 (Pagination 지원)

```bash
# 기본 조회 (첫 번째 페이지, 10개 항목)
GET /api/asst/v1/keyword-detects

# 특정 페이지 조회
GET /api/asst/v1/keyword-detects?page=2&limit=20
```

### 3. 생성자별 키워드 감지 조회

```bash
GET /api/asst/v1/keyword-detects/creator/admin_001
```

### 4. 타입별 키워드 감지 조회

```bash
GET /api/asst/v1/keyword-detects/type/urgent
```

### 5. 키워드 검색

```bash
GET /api/asst/v1/keyword-detects/search?keyword=긴급
```

### 6. 특정 키워드 감지 조회

```bash
GET /api/asst/v1/keyword-detects/keyword_detects_12345678-1234-1234-1234-123456789012
```

### 7. 키워드 감지 수정

```bash
PATCH /api/asst/v1/keyword-detects/keyword_detects_12345678-1234-1234-1234-123456789012
Content-Type: application/json

{
  "keyword": "수정된 키워드",
  "type": "modified"
}
```

### 8. 키워드 감지 삭제

```bash
DELETE /api/asst/v1/keyword-detects/keyword_detects_12345678-1234-1234-1234-123456789012
```

## 환경설정 관리 API

### 1. 환경설정 생성

```bash
POST /api/asst/v1/configs
Content-Type: application/json

{
  "user_key": "user_001",
  "alias": "theme",
  "value": "dark"
}
```

### 2. 환경설정 목록 조회 (Pagination 지원)

```bash
# 기본 조회 (첫 번째 페이지, 10개 항목)
GET /api/asst/v1/configs

# 특정 페이지 조회
GET /api/asst/v1/configs?page=2&limit=20
```

### 3. 사용자별 환경설정 조회

```bash
GET /api/asst/v1/configs/user/user_001
```

### 4. 사용자별 특정 설정 조회

```bash
GET /api/asst/v1/configs/user/user_001/alias/theme
```

### 5. 특정 환경설정 조회

```bash
GET /api/asst/v1/configs/configs_12345678-1234-1234-1234-123456789012
```

### 6. 환경설정 수정

```bash
PATCH /api/asst/v1/configs/configs_12345678-1234-1234-1234-123456789012
Content-Type: application/json

{
  "alias": "theme",
  "value": "light"
}
```

### 7. 환경설정 삭제

```bash
DELETE /api/asst/v1/configs/configs_12345678-1234-1234-1234-123456789012
```

### 8. 환경설정 생성 또는 업데이트 (Upsert)

```bash
POST /api/asst/v1/configs/upsert
Content-Type: application/json

{
  "user_key": "user_001",
  "alias": "language",
  "value": "ko"
}
```

**Upsert 기능**: 같은 `user_key`와 `alias` 조합이 이미 존재하면 업데이트하고, 없으면 새로 생성합니다.

## Socket.IO 실시간 통신

### 연결 설정

```javascript
import { io } from 'socket.io-client';

const socket = io('http://localhost:3000');

socket.on('connect', () => {
  console.log('Connected to server');
});

socket.on('connection-confirmed', (data) => {
  console.log('Connection confirmed:', data);
});
```

### 공지사항 실시간 수신

```javascript
// 방법 1: 구체적인 이벤트명 사용
socket.on('notice-broadcast', (data) => {
  console.log('New notice received:', data.message);
  // data.message에는 공지사항 정보가 포함됩니다
});

// 방법 2: 간단한 이벤트명 사용
socket.on('notice', (data) => {
  console.log('New notice received:', data.message);
  // data.message에는 공지사항 정보가 포함됩니다
});

// 공지사항 상세 정보 활용 예시
socket.on('notice-broadcast', (data) => {
  const { message } = data;
  console.log('📢 새로운 공지사항:', {
    id: message.id,
    title: message.name,
    content: message.content,
    isUrgent: message.is_urgent,
    creator: message.creator_key,
    target: message.target_key,
    timestamp: message.create_at,
  });

  if (message.is_urgent) {
    console.log('🚨 긴급 공지사항입니다!');
  }
});
```

````

### Socket.IO 이벤트 구조

#### 서버에서 클라이언트로 전송되는 이벤트:

- `notice-broadcast`: 공지사항 브로드캐스트
- `notice`: 공지사항 브로드캐스트 (간단한 이벤트명)

#### 클라이언트에서 서버로 전송되는 이벤트:

- `notice`: 공지사항 메시지

#### 서버 응답 이벤트:

- `notice-response`: 공지사항 메시지 응답

### 클라이언트 테스트 예제

```javascript
// Socket.IO 클라이언트 테스트
import { io } from 'socket.io-client';

const socket = io('http://localhost:3000');

// 연결 확인
socket.on('connect', () => {
  console.log('✅ Socket.IO 연결 성공');
});

socket.on('connection-confirmed', (data) => {
  console.log('✅ 서버 연결 확인됨:', data);
});

// 공지사항 메시지 수신
socket.on('notice-broadcast', (data) => {
  console.log('📢 공지사항 메시지 수신:', data);

  const { message } = data;
  console.log('📢 새로운 공지사항:', {
    id: message.id,
    title: message.name,
    content: message.content,
    isUrgent: message.is_urgent,
    creator: message.creator_key,
    target: message.target_key,
    timestamp: message.create_at,
  });

  if (message.is_urgent) {
    console.log('🚨 긴급 공지사항입니다!');
  }
});

// 에러 처리
socket.on('error', (error) => {
  console.error('❌ Socket.IO 에러:', error);
});

socket.on('disconnect', (reason) => {
  console.log('🔌 Socket.IO 연결 해제:', reason);
});
```
````
