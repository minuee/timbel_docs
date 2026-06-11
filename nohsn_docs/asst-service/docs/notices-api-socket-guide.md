# 공지사항(Notices) API 및 Socket.IO 연동 가이드

## 📋 목차

1. [개요](#개요)
2. [인증](#인증)
3. [API 기본 정보](#api-기본-정보)
4. [공지사항 API](#공지사항-api)
5. [읽음 처리 API](#읽음-처리-api)
6. [Socket.IO 실시간 연동](#socketio-실시간-연동)
7. [에러 처리](#에러-처리)
8. [전체 예제 코드](#전체-예제-코드)

---

## 개요

공지사항 기능은 공지사항을 생성, 조회, 수정, 삭제할 수 있으며, Socket.IO를 통해 실시간으로 모든 클라이언트에게 공지사항을 브로드캐스트합니다.

### 주요 기능

- ✅ 공지사항 CRUD 기능
- ✅ 페이지네이션 지원
- ✅ 읽음 처리 기능
- ✅ 읽지 않은 공지사항 조회
- ✅ Socket.IO 실시간 브로드캐스트
- ✅ 긴급 공지사항 지원

---

## 인증

모든 API 요청에는 인증 토큰이 필요합니다. `x-auth-token` 헤더에 Bearer 토큰을 포함해야 합니다.

### 헤더 형식

```http
x-auth-token: Bearer {your_token_here}
Content-Type: application/json
```

### 예시

```http
x-auth-token: Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyXzEyMyIsImlhdCI6MTY0MDk2ODAwMH0...
```

---

## API 기본 정보

### Base URL

```
http://localhost:3000/api/asst/v1
```

### 환경별 Base URL

- **개발 환경**: `http://localhost:3000/api/asst/v1`
- **프로덕션 환경**: `https://your-domain.com/api/asst/v1`

### 공통 헤더

모든 요청에 다음 헤더를 포함해야 합니다:

```http
x-auth-token: Bearer {token}
Content-Type: application/json
```

---

## 공지사항 API

### 1. 공지사항 생성

새로운 공지사항을 생성합니다. `send_socket` 옵션을 통해 Socket.IO 브로드캐스트 여부를 제어할 수 있습니다.

**엔드포인트**: `POST /notices`

**요청 본문**:

```json
{
  "name": "시스템 점검 안내",
  "is_urgent": true,
  "content": "2024년 1월 15일 오전 2시부터 4시까지 시스템 점검이 예정되어 있습니다.",
  "remind_time": "2024-01-14T20:00:00Z",
  "creator_key": "admin_001",
  "target_key": "all_users",
  "send_socket": true
}
```

**요청 예시**:

```bash
curl -X POST "http://localhost:3000/api/asst/v1/notices" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "시스템 점검 안내",
    "is_urgent": true,
    "content": "2024년 1월 15일 오전 2시부터 4시까지 시스템 점검이 예정되어 있습니다.",
    "creator_key": "admin_001",
    "target_key": "all_users",
    "send_socket": true
  }'
```

**응답 예시** (201 Created):

```json
{
  "id": "notices_550e8400-e29b-41d4-a716-446655440000",
  "name": "시스템 점검 안내",
  "is_urgent": true,
  "content": "2024년 1월 15일 오전 2시부터 4시까지 시스템 점검이 예정되어 있습니다.",
  "remind_time": "2024-01-14T20:00:00.000Z",
  "creator_key": "admin_001",
  "target_key": "all_users",
  "create_at": "2024-01-14T10:00:00.000Z",
  "update_at": "2024-01-14T10:00:00.000Z"
}
```

**필드 설명**:

| 필드        | 타입    | 필수 | 설명                                       |
| ----------- | ------- | ---- | ------------------------------------------ |
| name        | string  | ✅   | 공지사항 제목                              |
| content     | string  | ✅   | 공지사항 내용                              |
| creator_key | string  | ✅   | 생성자 키                                  |
| target_key  | string  | ✅   | 대상 키 (예: "all_users", 특정 사용자 키)  |
| is_urgent   | boolean | ❌   | 긴급 여부 (기본값: false)                  |
| remind_time | string  | ❌   | 알림 시간 (ISO 8601 형식)                  |
| send_socket | boolean | ❌   | Socket.IO 브로드캐스트 여부 (기본값: true) |

**Socket.IO 브로드캐스트**:

`send_socket`이 `true`인 경우, 공지사항 생성 시 연결된 모든 Socket.IO 클라이언트에게 즉시 브로드캐스트됩니다.

---

### 2. 공지사항 목록 조회 (페이지네이션)

공지사항 목록을 페이지네이션과 함께 조회합니다.

**엔드포인트**: `GET /notices`

**쿼리 파라미터**:

| 파라미터 | 타입   | 필수 | 기본값 | 설명                     |
| -------- | ------ | ---- | ------ | ------------------------ |
| page     | number | ❌   | 1      | 페이지 번호 (1부터 시작) |
| limit    | number | ❌   | 10     | 페이지당 항목 수         |

**요청 예시**:

```bash
# 기본 조회 (첫 번째 페이지, 10개 항목)
curl -X GET "http://localhost:3000/api/asst/v1/notices" \
  -H "x-auth-token: Bearer YOUR_TOKEN"

# 특정 페이지 조회
curl -X GET "http://localhost:3000/api/asst/v1/notices?page=2&limit=20" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
{
  "data": [
    {
      "id": "notices_550e8400-e29b-41d4-a716-446655440000",
      "name": "시스템 점검 안내",
      "is_urgent": true,
      "content": "2024년 1월 15일 오전 2시부터 4시까지 시스템 점검이 예정되어 있습니다.",
      "remind_time": "2024-01-14T20:00:00.000Z",
      "creator_key": "admin_001",
      "target_key": "all_users",
      "create_at": "2024-01-14T10:00:00.000Z",
      "update_at": "2024-01-14T10:00:00.000Z",
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

**응답 필드 설명**:

| 필드       | 타입     | 설명                  |
| ---------- | -------- | --------------------- |
| data       | Notice[] | 공지사항 목록         |
| total      | number   | 전체 항목 수          |
| page       | number   | 현재 페이지           |
| limit      | number   | 페이지당 항목 수      |
| totalPages | number   | 전체 페이지 수        |
| hasNext    | boolean  | 다음 페이지 존재 여부 |
| hasPrev    | boolean  | 이전 페이지 존재 여부 |

---

### 3. 공지사항 단건 조회 (자동 읽음 처리)

ID로 특정 공지사항을 조회합니다. `user_key` 쿼리 파라미터를 제공하면 자동으로 읽음 처리가 됩니다.

**엔드포인트**: `GET /notices/:id`

**쿼리 파라미터**:

| 파라미터 | 타입   | 필수 | 설명                               |
| -------- | ------ | ---- | ---------------------------------- |
| user_key | string | ❌   | 사용자 키 (제공 시 자동 읽음 처리) |

**요청 예시**:

```bash
# 기본 조회 (읽음 처리 없음)
curl -X GET "http://localhost:3000/api/asst/v1/notices/notices_550e8400-e29b-41d4-a716-446655440000" \
  -H "x-auth-token: Bearer YOUR_TOKEN"

# 자동 읽음 처리 포함
curl -X GET "http://localhost:3000/api/asst/v1/notices/notices_550e8400-e29b-41d4-a716-446655440000?user_key=user_123" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
{
  "id": "notices_550e8400-e29b-41d4-a716-446655440000",
  "name": "시스템 점검 안내",
  "is_urgent": true,
  "content": "2024년 1월 15일 오전 2시부터 4시까지 시스템 점검이 예정되어 있습니다.",
  "remind_time": "2024-01-14T20:00:00.000Z",
  "creator_key": "admin_001",
  "target_key": "all_users",
  "create_at": "2024-01-14T10:00:00.000Z",
  "update_at": "2024-01-14T10:00:00.000Z",
  "noticeReads": [
    {
      "id": "read_123",
      "notices_id": "notices_550e8400-e29b-41d4-a716-446655440000",
      "user_key": "user_123",
      "create_at": "2024-01-14T10:05:00.000Z"
    }
  ]
}
```

---

### 4. 공지사항 수정

공지사항 정보를 수정합니다.

**엔드포인트**: `PATCH /notices/:id`

**요청 본문**:

```json
{
  "name": "시스템 점검 안내 (수정)",
  "is_urgent": false,
  "content": "수정된 내용입니다."
}
```

**요청 예시**:

```bash
curl -X PATCH "http://localhost:3000/api/asst/v1/notices/notices_550e8400-e29b-41d4-a716-446655440000" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "시스템 점검 안내 (수정)",
    "content": "수정된 내용입니다."
  }'
```

**응답 예시** (200 OK):

```json
{
  "id": "notices_550e8400-e29b-41d4-a716-446655440000",
  "name": "시스템 점검 안내 (수정)",
  "is_urgent": false,
  "content": "수정된 내용입니다.",
  "remind_time": "2024-01-14T20:00:00.000Z",
  "creator_key": "admin_001",
  "target_key": "all_users",
  "create_at": "2024-01-14T10:00:00.000Z",
  "update_at": "2024-01-14T11:00:00.000Z"
}
```

---

### 5. 공지사항 삭제

공지사항을 삭제합니다.

**엔드포인트**: `DELETE /notices/:id`

**요청 예시**:

```bash
curl -X DELETE "http://localhost:3000/api/asst/v1/notices/notices_550e8400-e29b-41d4-a716-446655440000" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
{
  "message": "공지사항이 성공적으로 삭제되었습니다."
}
```

---

## 읽음 처리 API

### 1. 공지사항 읽음 처리

공지사항을 읽음 처리합니다.

**엔드포인트**: `POST /notices/reads`

**요청 본문**:

```json
{
  "notices_id": "notices_550e8400-e29b-41d4-a716-446655440000",
  "user_key": "user_123"
}
```

**요청 예시**:

```bash
curl -X POST "http://localhost:3000/api/asst/v1/notices/reads" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "notices_id": "notices_550e8400-e29b-41d4-a716-446655440000",
    "user_key": "user_123"
  }'
```

**응답 예시** (201 Created):

```json
{
  "id": "read_123",
  "notices_id": "notices_550e8400-e29b-41d4-a716-446655440000",
  "user_key": "user_123",
  "create_at": "2024-01-14T10:05:00.000Z",
  "update_at": "2024-01-14T10:05:00.000Z"
}
```

---

### 2. 특정 공지사항의 읽음 목록 조회

특정 공지사항을 읽은 사용자 목록을 조회합니다.

**엔드포인트**: `GET /notices/:id/reads`

**요청 예시**:

```bash
curl -X GET "http://localhost:3000/api/asst/v1/notices/notices_550e8400-e29b-41d4-a716-446655440000/reads" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
[
  {
    "id": "read_123",
    "notices_id": "notices_550e8400-e29b-41d4-a716-446655440000",
    "user_key": "user_123",
    "create_at": "2024-01-14T10:05:00.000Z",
    "update_at": "2024-01-14T10:05:00.000Z"
  },
  {
    "id": "read_456",
    "notices_id": "notices_550e8400-e29b-41d4-a716-446655440000",
    "user_key": "user_456",
    "create_at": "2024-01-14T10:10:00.000Z",
    "update_at": "2024-01-14T10:10:00.000Z"
  }
]
```

---

### 3. 사용자가 읽은 공지사항 목록 조회

특정 사용자가 읽은 공지사항 목록을 조회합니다.

**엔드포인트**: `GET /notices/reads/user/:userKey`

**요청 예시**:

```bash
curl -X GET "http://localhost:3000/api/asst/v1/notices/reads/user/user_123" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
[
  {
    "id": "read_123",
    "notices_id": "notices_550e8400-e29b-41d4-a716-446655440000",
    "user_key": "user_123",
    "create_at": "2024-01-14T10:05:00.000Z",
    "update_at": "2024-01-14T10:05:00.000Z"
  }
]
```

---

### 4. 사용자가 읽지 않은 공지사항 목록 조회

특정 사용자가 읽지 않은 공지사항 목록을 조회합니다.

**엔드포인트**: `GET /notices/unread/:userKey`

**요청 예시**:

```bash
curl -X GET "http://localhost:3000/api/asst/v1/notices/unread/user_123" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
[
  {
    "id": "notices_550e8400-e29b-41d4-a716-446655440000",
    "name": "시스템 점검 안내",
    "is_urgent": true,
    "content": "2024년 1월 15일 오전 2시부터 4시까지 시스템 점검이 예정되어 있습니다.",
    "remind_time": "2024-01-14T20:00:00.000Z",
    "creator_key": "admin_001",
    "target_key": "all_users",
    "create_at": "2024-01-14T10:00:00.000Z",
    "update_at": "2024-01-14T10:00:00.000Z"
  }
]
```

---

## Socket.IO 실시간 연동

### 개요

공지사항이 생성될 때 (`send_socket: true`), Socket.IO를 통해 `notices` room에 참여한 클라이언트들에게 실시간으로 브로드캐스트됩니다.

### Socket.IO 연결 설정

```javascript
import { io } from 'socket.io-client';

const socket = io('http://localhost:3000', {
  transports: ['websocket', 'polling'],
  reconnection: true,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
  reconnectionAttempts: Infinity,
});

socket.on('connect', () => {
  console.log('Socket.IO 연결됨:', socket.id);

  // notices room 참여
  socket.emit('join-room', 'notices');
});

socket.on('connection-confirmed', (data) => {
  console.log('서버 연결 확인:', data);
});
```

### Notices Room 참여

공지사항을 수신하려면 `notices` room에 참여해야 합니다.

```javascript
socket.on('connect', () => {
  console.log('Socket.IO 연결됨');

  // notices room 참여
  socket.emit('join-room', 'notices');

  socket.on('join-room-success', (data) => {
    console.log('Room 참여 성공:', data);
    // data: { room: 'notices', message: '...', clientCount: 1 }
  });

  socket.on('join-room-error', (error) => {
    console.error('Room 참여 실패:', error);
  });
});

// 재연결 시 room 다시 참여
socket.on('reconnect', (attemptNumber) => {
  console.log('Socket.IO 재연결:', attemptNumber);
  socket.emit('join-room', 'notices');
});
```

### 공지사항 수신

공지사항은 두 가지 이벤트명으로 브로드캐스트됩니다:

1. **`notice-broadcast`** - 구체적인 이벤트명
2. **`notice`** - 간단한 이벤트명

**이벤트 수신 예시**:

```javascript
// 방법 1: notice-broadcast 이벤트 사용 (권장)
socket.on('notice-broadcast', (data) => {
  console.log('새 공지사항 수신:', data);

  const notice = data.message;
  console.log('공지사항 정보:', {
    id: notice.id,
    title: notice.name,
    content: notice.content,
    isUrgent: notice.is_urgent,
    creator: notice.creator_key,
    target: notice.target_key,
    timestamp: notice.create_at,
  });

  if (notice.is_urgent) {
    console.log('🚨 긴급 공지사항입니다!');
    // 긴급 공지사항 처리 로직
  }
});

// 방법 2: notice 이벤트 사용
socket.on('notice', (data) => {
  console.log('새 공지사항 수신:', data.message);
});
```

### 메시지 구조

Socket.IO로 전송되는 메시지 구조:

```typescript
interface SocketMessage {
  type: 'NOTICE';
  message: {
    id: string;
    name: string;
    is_urgent: boolean;
    content: string;
    remind_time: Date | null;
    creator_key: string;
    target_key: string;
    create_at: Date;
  };
}
```

**실제 메시지 예시**:

```json
{
  "type": "NOTICE",
  "message": {
    "id": "notices_550e8400-e29b-41d4-a716-446655440000",
    "name": "시스템 점검 안내",
    "is_urgent": true,
    "content": "2024년 1월 15일 오전 2시부터 4시까지 시스템 점검이 예정되어 있습니다.",
    "remind_time": "2024-01-14T20:00:00.000Z",
    "creator_key": "admin_001",
    "target_key": "all_users",
    "create_at": "2024-01-14T10:00:00.000Z"
  }
}
```

### 브로드캐스트 동작

- 공지사항 생성 시 `send_socket: true`인 경우, **`notices` room에 참여한 클라이언트**에게만 브로드캐스트됩니다.
- Room 기반 브로드캐스트이므로, 클라이언트는 **반드시 `notices` room에 참여**해야 공지사항을 수신할 수 있습니다.
- 재연결 시 room을 다시 참여해야 계속 공지사항을 수신할 수 있습니다.

---

## 에러 처리

### 공통 에러 응답 형식

모든 API는 다음 형식의 에러 응답을 반환할 수 있습니다:

```json
{
  "statusCode": 400,
  "message": "에러 메시지",
  "error": "Bad Request"
}
```

### HTTP 상태 코드

| 코드 | 설명                  |
| ---- | --------------------- |
| 200  | 성공                  |
| 201  | 생성 성공             |
| 400  | 잘못된 요청           |
| 401  | 인증 실패             |
| 404  | 리소스를 찾을 수 없음 |
| 500  | 서버 내부 오류        |

### 에러 예시

**404 Not Found**:

```json
{
  "statusCode": 404,
  "message": "공지사항을 찾을 수 없습니다.",
  "error": "Not Found"
}
```

**400 Bad Request**:

```json
{
  "statusCode": 400,
  "message": ["name should not be empty", "content should not be empty"],
  "error": "Bad Request"
}
```

---

## 전체 예제 코드

### JavaScript/TypeScript (Axios + Socket.IO)

```typescript
import axios from 'axios';
import { io, Socket } from 'socket.io-client';

const API_BASE_URL = 'http://localhost:3000/api/asst/v1';
const SOCKET_URL = 'http://localhost:3000';
const AUTH_TOKEN = 'Bearer YOUR_TOKEN';

// API 클라이언트 설정
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'x-auth-token': AUTH_TOKEN,
    'Content-Type': 'application/json',
  },
});

// Socket.IO 클라이언트 설정
const socket: Socket = io(SOCKET_URL, {
  transports: ['websocket', 'polling'],
  reconnection: true,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
  reconnectionAttempts: Infinity,
});

// Socket.IO 연결 이벤트
socket.on('connect', () => {
  console.log('Socket.IO 연결됨:', socket.id);

  // notices room 참여
  socket.emit('join-room', 'notices');
});

socket.on('connection-confirmed', (data) => {
  console.log('서버 연결 확인:', data);
});

socket.on('join-room-success', (data) => {
  console.log('notices room 참여 성공:', data);
});

socket.on('reconnect', () => {
  console.log('Socket.IO 재연결');
  // 재연결 시 room 다시 참여
  socket.emit('join-room', 'notices');
});

// 공지사항 수신
socket.on('notice-broadcast', (data) => {
  const notice = data.message;
  console.log('📢 새로운 공지사항:', {
    id: notice.id,
    title: notice.name,
    content: notice.content,
    isUrgent: notice.is_urgent,
  });

  if (notice.is_urgent) {
    alert(`🚨 긴급 공지사항: ${notice.name}`);
  }
});

// 공지사항 생성
async function createNotice() {
  try {
    const response = await apiClient.post('/notices', {
      name: '시스템 점검 안내',
      is_urgent: true,
      content:
        '2024년 1월 15일 오전 2시부터 4시까지 시스템 점검이 예정되어 있습니다.',
      creator_key: 'admin_001',
      target_key: 'all_users',
      send_socket: true, // Socket.IO 브로드캐스트 활성화
    });
    console.log('공지사항 생성 성공:', response.data);
  } catch (error) {
    console.error('공지사항 생성 실패:', error.response?.data);
  }
}

// 공지사항 목록 조회
async function getNotices(page = 1, limit = 10) {
  try {
    const response = await apiClient.get('/notices', {
      params: { page, limit },
    });
    console.log('공지사항 목록:', response.data);
    return response.data;
  } catch (error) {
    console.error('공지사항 조회 실패:', error.response?.data);
  }
}

// 공지사항 읽음 처리
async function markAsRead(noticeId: string, userKey: string) {
  try {
    const response = await apiClient.post('/notices/reads', {
      notices_id: noticeId,
      user_key: userKey,
    });
    console.log('읽음 처리 성공:', response.data);
  } catch (error) {
    console.error('읽음 처리 실패:', error.response?.data);
  }
}

// 읽지 않은 공지사항 조회
async function getUnreadNotices(userKey: string) {
  try {
    const response = await apiClient.get(`/notices/unread/${userKey}`);
    console.log('읽지 않은 공지사항:', response.data);
    return response.data;
  } catch (error) {
    console.error('읽지 않은 공지사항 조회 실패:', error.response?.data);
  }
}
```

### Vue.js (Composition API)

```vue
<template>
  <div>
    <h2>공지사항</h2>

    <!-- 공지사항 목록 -->
    <div v-for="notice in notices" :key="notice.id" class="notice-item">
      <h3 :class="{ urgent: notice.is_urgent }">
        {{ notice.name }}
        <span v-if="notice.is_urgent">🚨 긴급</span>
      </h3>
      <p>{{ notice.content }}</p>
      <small>{{ formatDate(notice.create_at) }}</small>
      <button @click="markAsRead(notice.id)">읽음 처리</button>
    </div>

    <!-- 페이지네이션 -->
    <div class="pagination">
      <button @click="loadPage(currentPage - 1)" :disabled="!hasPrev">
        이전
      </button>
      <span>페이지 {{ currentPage }} / {{ totalPages }}</span>
      <button @click="loadPage(currentPage + 1)" :disabled="!hasNext">
        다음
      </button>
    </div>

    <!-- 새 공지사항 알림 -->
    <div v-if="newNotice" class="new-notice-alert">
      <h3>📢 새로운 공지사항</h3>
      <p>{{ newNotice.name }}</p>
      <button @click="newNotice = null">닫기</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import axios from 'axios';
import { io } from 'socket.io-client';

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:3000/api/asst/v1';
const SOCKET_URL = import.meta.env.VITE_SOCKET_URL || 'http://localhost:3000';
const AUTH_TOKEN = 'Bearer YOUR_TOKEN';
const USER_KEY = 'user_123';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'x-auth-token': AUTH_TOKEN,
    'Content-Type': 'application/json',
  },
});

const socket = io(SOCKET_URL, {
  transports: ['websocket', 'polling'],
  reconnection: true,
});

const notices = ref([]);
const newNotice = ref(null);
const currentPage = ref(1);
const totalPages = ref(1);
const hasNext = ref(false);
const hasPrev = ref(false);

// Socket.IO 이벤트 핸들러
socket.on('connect', () => {
  console.log('Socket.IO 연결됨');

  // notices room 참여
  socket.emit('join-room', 'notices');
});

socket.on('join-room-success', (data) => {
  console.log('notices room 참여 성공:', data);
});

socket.on('reconnect', () => {
  console.log('Socket.IO 재연결');
  // 재연결 시 room 다시 참여
  socket.emit('join-room', 'notices');
});

socket.on('notice-broadcast', (data) => {
  const notice = data.message;
  console.log('새 공지사항 수신:', notice);

  newNotice.value = notice;

  // 긴급 공지사항인 경우 알림 표시
  if (notice.is_urgent) {
    alert(`🚨 긴급 공지사항: ${notice.name}`);
  }

  // 목록 새로고침
  loadNotices(currentPage.value);
});

// 공지사항 목록 로드
const loadNotices = async (page = 1) => {
  try {
    const response = await apiClient.get('/notices', {
      params: { page, limit: 10 },
    });

    notices.value = response.data.data;
    currentPage.value = response.data.page;
    totalPages.value = response.data.totalPages;
    hasNext.value = response.data.hasNext;
    hasPrev.value = response.data.hasPrev;
  } catch (error) {
    console.error('공지사항 조회 실패:', error);
  }
};

// 페이지 로드
const loadPage = (page) => {
  if (page >= 1 && page <= totalPages.value) {
    loadNotices(page);
  }
};

// 읽음 처리
const markAsRead = async (noticeId) => {
  try {
    await apiClient.post('/notices/reads', {
      notices_id: noticeId,
      user_key: USER_KEY,
    });

    // 목록 새로고침
    loadNotices(currentPage.value);
  } catch (error) {
    console.error('읽음 처리 실패:', error);
  }
};

// 날짜 포맷팅
const formatDate = (dateString) => {
  return new Date(dateString).toLocaleString('ko-KR');
};

onMounted(() => {
  loadNotices();
});

onUnmounted(() => {
  socket.disconnect();
});
</script>

<style scoped>
.notice-item {
  border: 1px solid #ddd;
  padding: 1rem;
  margin-bottom: 1rem;
}

.notice-item h3.urgent {
  color: red;
}

.new-notice-alert {
  position: fixed;
  top: 20px;
  right: 20px;
  background: #fff;
  border: 2px solid #007bff;
  padding: 1rem;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}
</style>
```

### React (Hooks)

```tsx
import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { io, Socket } from 'socket.io-client';

const API_BASE_URL = 'http://localhost:3000/api/asst/v1';
const SOCKET_URL = 'http://localhost:3000';
const AUTH_TOKEN = 'Bearer YOUR_TOKEN';
const USER_KEY = 'user_123';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'x-auth-token': AUTH_TOKEN,
    'Content-Type': 'application/json',
  },
});

interface Notice {
  id: string;
  name: string;
  is_urgent: boolean;
  content: string;
  creator_key: string;
  target_key: string;
  create_at: string;
}

function NoticeList() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [newNotice, setNewNotice] = useState<Notice | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [hasPrev, setHasPrev] = useState(false);

  useEffect(() => {
    // Socket.IO 연결
    const socket: Socket = io(SOCKET_URL, {
      transports: ['websocket', 'polling'],
      reconnection: true,
    });

    socket.on('connect', () => {
      console.log('Socket.IO 연결됨');

      // notices room 참여
      socket.emit('join-room', 'notices');
    });

    socket.on('join-room-success', (data: any) => {
      console.log('notices room 참여 성공:', data);
    });

    socket.on('reconnect', () => {
      console.log('Socket.IO 재연결');
      // 재연결 시 room 다시 참여
      socket.emit('join-room', 'notices');
    });

    socket.on('notice-broadcast', (data: any) => {
      const notice = data.message;
      console.log('새 공지사항 수신:', notice);

      setNewNotice(notice);

      if (notice.is_urgent) {
        alert(`🚨 긴급 공지사항: ${notice.name}`);
      }

      // 목록 새로고침
      loadNotices(currentPage);
    });

    // 공지사항 목록 로드
    loadNotices(1);

    return () => {
      socket.disconnect();
    };
  }, []);

  const loadNotices = async (page: number) => {
    try {
      const response = await apiClient.get('/notices', {
        params: { page, limit: 10 },
      });

      setNotices(response.data.data);
      setCurrentPage(response.data.page);
      setTotalPages(response.data.totalPages);
      setHasNext(response.data.hasNext);
      setHasPrev(response.data.hasPrev);
    } catch (error) {
      console.error('공지사항 조회 실패:', error);
    }
  };

  const markAsRead = async (noticeId: string) => {
    try {
      await apiClient.post('/notices/reads', {
        notices_id: noticeId,
        user_key: USER_KEY,
      });

      loadNotices(currentPage);
    } catch (error) {
      console.error('읽음 처리 실패:', error);
    }
  };

  return (
    <div>
      <h2>공지사항</h2>

      {notices.map((notice) => (
        <div key={notice.id} className="notice-item">
          <h3 className={notice.is_urgent ? 'urgent' : ''}>
            {notice.name}
            {notice.is_urgent && ' 🚨 긴급'}
          </h3>
          <p>{notice.content}</p>
          <small>{new Date(notice.create_at).toLocaleString('ko-KR')}</small>
          <button onClick={() => markAsRead(notice.id)}>읽음 처리</button>
        </div>
      ))}

      <div className="pagination">
        <button
          onClick={() => loadNotices(currentPage - 1)}
          disabled={!hasPrev}
        >
          이전
        </button>
        <span>
          페이지 {currentPage} / {totalPages}
        </span>
        <button
          onClick={() => loadNotices(currentPage + 1)}
          disabled={!hasNext}
        >
          다음
        </button>
      </div>

      {newNotice && (
        <div className="new-notice-alert">
          <h3>📢 새로운 공지사항</h3>
          <p>{newNotice.name}</p>
          <button onClick={() => setNewNotice(null)}>닫기</button>
        </div>
      )}
    </div>
  );
}

export default NoticeList;
```

---

## 참고 문서

- [상담사 및 그룹 관리 API 가이드](./agents-groups-api-guide.md)
- [상담사 상태 공유 기능 가이드](./agent-status-socket-guide.md)
- [Swagger API 문서](http://localhost:3000/api/asst/v1/doc)

---

## 문의

API 관련 문의사항이 있으시면 개발팀에 문의해주세요.
