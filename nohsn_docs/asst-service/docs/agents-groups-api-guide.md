# 상담사 및 그룹 관리 API 연동 가이드

## 📋 목차

1. [개요](#개요)
2. [인증](#인증)
3. [API 기본 정보](#api-기본-정보)
4. [상담사(Agents) API](#상담사agents-api)
5. [그룹(Groups) API](#그룹groups-api)
6. [상담사 상태 관리 API](#상담사-상태-관리-api)
7. [에러 처리](#에러-처리)
8. [전체 예제 코드](#전체-예제-코드)

---

## 개요

이 문서는 상담사(Agents)와 그룹(Groups) 관리 API의 사용 방법을 설명합니다.

### 주요 기능

- ✅ 상담사 CRUD 기능
- ✅ 그룹 CRUD 기능
- ✅ 그룹에 상담사 배치 기능
- ✅ 상담사 상태 관리 및 실시간 공유 (Socket.IO)

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

## 상담사(Agents) API

### 1. 상담사 생성

새로운 상담사를 생성합니다.

**엔드포인트**: `POST /agents`

**요청 본문**:

```json
{
  "id": "agent_123",
  "workspace_id": "workspace_123",
  "group_id": "group_123",
  "status": "UNKNOWN",
  "name": "홍길동",
  "extension": "1234",
  "email": "agent@example.com"
}
```

**요청 예시**:

```bash
curl -X POST "http://localhost:3000/api/asst/v1/agents" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "agent_123",
    "name": "홍길동",
    "email": "agent@example.com",
    "status": "UNKNOWN"
  }'
```

**응답 예시** (201 Created):

```json
{
  "id": "agent_123",
  "workspace_id": "workspace_123",
  "group_id": "group_123",
  "status": "UNKNOWN",
  "name": "홍길동",
  "extension": "1234",
  "email": "agent@example.com",
  "created_at": "2024-01-01T00:00:00.000Z",
  "updated_at": "2024-01-01T00:00:00.000Z"
}
```

**필드 설명**:

| 필드         | 타입   | 필수 | 설명                                  |
| ------------ | ------ | ---- | ------------------------------------- |
| id           | string | ✅   | 상담사 ID (다른 테이블에서 가져온 값) |
| workspace_id | string | ❌   | 워크스페이스 ID                       |
| group_id     | string | ❌   | 그룹 ID                               |
| status       | string | ❌   | 상태 (기본값: "UNKNOWN")              |
| name         | string | ❌   | 이름                                  |
| extension    | string | ❌   | 내선번호                              |
| email        | string | ❌   | 이메일                                |

---

### 2. 상담사 전체 조회

모든 상담사 목록을 조회합니다. 페이지네이션 없이 전체 목록을 반환합니다.

**엔드포인트**: `GET /agents`

**요청 예시**:

```bash
curl -X GET "http://localhost:3000/api/asst/v1/agents" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
[
  {
    "id": "agent_123",
    "workspace_id": "workspace_123",
    "group_id": "group_123",
    "status": "ACTIVE",
    "name": "홍길동",
    "extension": "1234",
    "email": "agent@example.com",
    "created_at": "2024-01-01T00:00:00.000Z",
    "updated_at": "2024-01-01T00:00:00.000Z"
  },
  {
    "id": "agent_456",
    "workspace_id": "workspace_123",
    "group_id": null,
    "status": "INACTIVE",
    "name": "김철수",
    "extension": "5678",
    "email": "kim@example.com",
    "created_at": "2024-01-02T00:00:00.000Z",
    "updated_at": "2024-01-02T00:00:00.000Z"
  }
]
```

---

### 3. 상담사 수정

상담사 정보를 수정합니다. 요청한 필드만 업데이트됩니다.

**⚠️ 주의**: `status` 필드는 이 엔드포인트에서 수정할 수 없습니다. 상태 수정은 `PUT /agents/status` 엔드포인트를 사용하세요.

**엔드포인트**: `PUT /agents/:id`

**요청 본문**:

```json
{
  "name": "홍길동 (수정)",
  "extension": "9999",
  "email": "updated@example.com",
  "workspace_id": "workspace_456",
  "group_id": "group_456"
}
```

**요청 예시**:

```bash
curl -X PUT "http://localhost:3000/api/asst/v1/agents/agent_123" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "홍길동 (수정)",
    "extension": "9999"
  }'
```

**응답 예시** (200 OK):

```json
{
  "id": "agent_123",
  "workspace_id": "workspace_123",
  "group_id": "group_123",
  "status": "ACTIVE",
  "name": "홍길동 (수정)",
  "extension": "9999",
  "email": "updated@example.com",
  "created_at": "2024-01-01T00:00:00.000Z",
  "updated_at": "2024-01-01T01:00:00.000Z"
}
```

**수정 가능한 필드**:

- `workspace_id`
- `group_id`
- `name`
- `extension`
- `email`

**수정 불가능한 필드**:

- `id` (기본키)
- `status` (별도 엔드포인트 사용)

---

### 4. 상담사 삭제

상담사를 삭제합니다.

**엔드포인트**: `DELETE /agents/:id`

**요청 예시**:

```bash
curl -X DELETE "http://localhost:3000/api/asst/v1/agents/agent_123" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (204 No Content):

응답 본문 없음

---

## 그룹(Groups) API

### 1. 그룹 생성

새로운 그룹을 생성합니다.

**엔드포인트**: `POST /groups`

**요청 본문**:

```json
{
  "name": "고객센터 1팀",
  "description": "고객센터 1팀 그룹입니다.",
  "workspace_id": "workspace_123",
  "manager_agent_id": "agent_123",
  "sub_manager_1_agent_id": "agent_456",
  "sub_manager_2_agent_id": "agent_789",
  "sub_manager_3_agent_id": "agent_012"
}
```

**요청 예시**:

```bash
curl -X POST "http://localhost:3000/api/asst/v1/groups" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "고객센터 1팀",
    "description": "고객센터 1팀 그룹입니다."
  }'
```

**응답 예시** (201 Created):

```json
{
  "id": "group_550e8400-e29b-41d4-a716-446655440000",
  "name": "고객센터 1팀",
  "description": "고객센터 1팀 그룹입니다.",
  "workspace_id": "workspace_123",
  "manager_agent_id": "agent_123",
  "sub_manager_1_agent_id": "agent_456",
  "sub_manager_2_agent_id": "agent_789",
  "sub_manager_3_agent_id": "agent_012",
  "created_at": "2024-01-01T00:00:00.000Z",
  "updated_at": "2024-01-01T00:00:00.000Z"
}
```

**필드 설명**:

| 필드                   | 타입   | 필수 | 설명                    |
| ---------------------- | ------ | ---- | ----------------------- |
| name                   | string | ✅   | 그룹 이름               |
| description            | string | ❌   | 설명                    |
| workspace_id           | string | ❌   | 워크스페이스 ID         |
| manager_agent_id       | string | ❌   | 매니저 상담사 ID        |
| sub_manager_1_agent_id | string | ❌   | 서브 매니저 1 상담사 ID |
| sub_manager_2_agent_id | string | ❌   | 서브 매니저 2 상담사 ID |
| sub_manager_3_agent_id | string | ❌   | 서브 매니저 3 상담사 ID |

**참고**: 그룹 ID는 자동으로 `group_{uuid_v4}` 형식으로 생성됩니다.

---

### 2. 그룹 전체 조회

모든 그룹 목록을 조회합니다. 페이지네이션 없이 전체 목록을 반환합니다.

**엔드포인트**: `GET /groups`

**요청 예시**:

```bash
curl -X GET "http://localhost:3000/api/asst/v1/groups" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
[
  {
    "id": "group_550e8400-e29b-41d4-a716-446655440000",
    "name": "고객센터 1팀",
    "description": "고객센터 1팀 그룹입니다.",
    "workspace_id": "workspace_123",
    "manager_agent_id": "agent_123",
    "sub_manager_1_agent_id": "agent_456",
    "sub_manager_2_agent_id": "agent_789",
    "sub_manager_3_agent_id": "agent_012",
    "created_at": "2024-01-01T00:00:00.000Z",
    "updated_at": "2024-01-01T00:00:00.000Z"
  }
]
```

---

### 3. 그룹 단건 조회

ID로 특정 그룹을 조회합니다.

**엔드포인트**: `GET /groups/:id`

**요청 예시**:

```bash
curl -X GET "http://localhost:3000/api/asst/v1/groups/group_550e8400-e29b-41d4-a716-446655440000" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
{
  "id": "group_550e8400-e29b-41d4-a716-446655440000",
  "name": "고객센터 1팀",
  "description": "고객센터 1팀 그룹입니다.",
  "workspace_id": "workspace_123",
  "manager_agent_id": "agent_123",
  "sub_manager_1_agent_id": "agent_456",
  "sub_manager_2_agent_id": "agent_789",
  "sub_manager_3_agent_id": "agent_012",
  "created_at": "2024-01-01T00:00:00.000Z",
  "updated_at": "2024-01-01T00:00:00.000Z"
}
```

---

### 4. 그룹 수정

그룹 정보를 수정합니다. 요청한 필드만 업데이트됩니다.

**엔드포인트**: `PUT /groups/:id`

**요청 본문**:

```json
{
  "name": "고객센터 1팀 (수정)",
  "description": "수정된 설명",
  "manager_agent_id": "agent_999"
}
```

**요청 예시**:

```bash
curl -X PUT "http://localhost:3000/api/asst/v1/groups/group_550e8400-e29b-41d4-a716-446655440000" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "고객센터 1팀 (수정)",
    "description": "수정된 설명"
  }'
```

**응답 예시** (200 OK):

```json
{
  "id": "group_550e8400-e29b-41d4-a716-446655440000",
  "name": "고객센터 1팀 (수정)",
  "description": "수정된 설명",
  "workspace_id": "workspace_123",
  "manager_agent_id": "agent_123",
  "sub_manager_1_agent_id": "agent_456",
  "sub_manager_2_agent_id": "agent_789",
  "sub_manager_3_agent_id": "agent_012",
  "created_at": "2024-01-01T00:00:00.000Z",
  "updated_at": "2024-01-01T01:00:00.000Z"
}
```

---

### 5. 그룹 삭제

그룹을 삭제합니다.

**엔드포인트**: `DELETE /groups/:id`

**요청 예시**:

```bash
curl -X DELETE "http://localhost:3000/api/asst/v1/groups/group_550e8400-e29b-41d4-a716-446655440000" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (204 No Content):

응답 본문 없음

---

### 6. 그룹에 상담사 배치

그룹에 상담사들을 배치합니다. 입력받은 상담사들의 `group_id`를 업데이트합니다.

**엔드포인트**: `POST /groups/assign-agents`

**요청 본문**:

```json
{
  "group_id": "group_550e8400-e29b-41d4-a716-446655440000",
  "agent_ids": ["agent_123", "agent_456", "agent_789"]
}
```

**요청 예시**:

```bash
curl -X POST "http://localhost:3000/api/asst/v1/groups/assign-agents" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_id": "group_550e8400-e29b-41d4-a716-446655440000",
    "agent_ids": ["agent_123", "agent_456", "agent_789"]
  }'
```

**응답 예시** (200 OK):

```json
[
  {
    "id": "agent_123",
    "workspace_id": "workspace_123",
    "group_id": "group_550e8400-e29b-41d4-a716-446655440000",
    "status": "ACTIVE",
    "name": "홍길동",
    "extension": "1234",
    "email": "agent@example.com",
    "created_at": "2024-01-01T00:00:00.000Z",
    "updated_at": "2024-01-01T01:00:00.000Z"
  },
  {
    "id": "agent_456",
    "workspace_id": "workspace_123",
    "group_id": "group_550e8400-e29b-41d4-a716-446655440000",
    "status": "ACTIVE",
    "name": "김철수",
    "extension": "5678",
    "email": "kim@example.com",
    "created_at": "2024-01-02T00:00:00.000Z",
    "updated_at": "2024-01-01T01:00:00.000Z"
  },
  {
    "id": "agent_789",
    "workspace_id": "workspace_123",
    "group_id": "group_550e8400-e29b-41d4-a716-446655440000",
    "status": "INACTIVE",
    "name": "이영희",
    "extension": "9012",
    "email": "lee@example.com",
    "created_at": "2024-01-03T00:00:00.000Z",
    "updated_at": "2024-01-01T01:00:00.000Z"
  }
]
```

**필드 설명**:

| 필드      | 타입     | 필수 | 설명                             |
| --------- | -------- | ---- | -------------------------------- |
| group_id  | string   | ✅   | 배치할 그룹 ID                   |
| agent_ids | string[] | ✅   | 배치할 상담사 ID 목록 (최소 1개) |

---

## 상담사 상태 관리 API

### 1. 상담사 상태 수정

상담사의 상태를 수정하고 Socket.IO로 브로드캐스트합니다.

**엔드포인트**: `PUT /agents/status`

**요청 본문**:

```json
{
  "agent_id": "agent_123",
  "status": "ACTIVE"
}
```

**요청 예시**:

```bash
curl -X PUT "http://localhost:3000/api/asst/v1/agents/status" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent_123",
    "status": "ACTIVE"
  }'
```

**응답 예시** (200 OK):

```json
{
  "id": "agent_123",
  "workspace_id": "workspace_123",
  "group_id": "group_123",
  "status": "ACTIVE",
  "name": "홍길동",
  "extension": "1234",
  "email": "agent@example.com",
  "created_at": "2024-01-01T00:00:00.000Z",
  "updated_at": "2024-01-01T01:00:00.000Z"
}
```

**Socket.IO 브로드캐스트**:

상태가 수정되면 `agent-status` room에 연결된 모든 클라이언트에게 다음 메시지가 전송됩니다:

```json
{
  "agent_id": "agent_123",
  "status": "ACTIVE",
  "timestamp": "2024-01-01T01:00:00.000Z"
}
```

**이벤트명**: `agent-status-update`

Socket.IO 연동 방법은 [상담사 상태 공유 기능 가이드](./agent-status-socket-guide.md)를 참고하세요.

---

### 2. 상태별 상담사 조회

특정 상태의 상담사 목록을 조회합니다.

**엔드포인트**: `GET /agents/status/:status`

**요청 예시**:

```bash
curl -X GET "http://localhost:3000/api/asst/v1/agents/status/ACTIVE" \
  -H "x-auth-token: Bearer YOUR_TOKEN"
```

**응답 예시** (200 OK):

```json
[
  {
    "id": "agent_123",
    "workspace_id": "workspace_123",
    "group_id": "group_123",
    "status": "ACTIVE",
    "name": "홍길동",
    "extension": "1234",
    "email": "agent@example.com",
    "created_at": "2024-01-01T00:00:00.000Z",
    "updated_at": "2024-01-01T00:00:00.000Z"
  },
  {
    "id": "agent_456",
    "workspace_id": "workspace_123",
    "group_id": "group_123",
    "status": "ACTIVE",
    "name": "김철수",
    "extension": "5678",
    "email": "kim@example.com",
    "created_at": "2024-01-02T00:00:00.000Z",
    "updated_at": "2024-01-02T00:00:00.000Z"
  }
]
```

**일반적인 상태 값**:

- `UNKNOWN` - 상태 미지정 (기본값)
- `ACTIVE` - 활성
- `INACTIVE` - 비활성
- `BUSY` - 통화 중
- `AWAY` - 자리 비움

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

| 코드 | 설명                       |
| ---- | -------------------------- |
| 200  | 성공                       |
| 201  | 생성 성공                  |
| 204  | 삭제 성공 (응답 본문 없음) |
| 400  | 잘못된 요청                |
| 401  | 인증 실패                  |
| 404  | 리소스를 찾을 수 없음      |
| 500  | 서버 내부 오류             |

### 에러 예시

**404 Not Found**:

```json
{
  "statusCode": 404,
  "message": "상담사를 찾을 수 없습니다: agent_999",
  "error": "Not Found"
}
```

**400 Bad Request**:

```json
{
  "statusCode": 400,
  "message": ["agent_id should not be empty", "status should not be empty"],
  "error": "Bad Request"
}
```

**401 Unauthorized**:

```json
{
  "statusCode": 401,
  "message": "인증 토큰이 필요합니다.",
  "error": "Unauthorized"
}
```

---

## 전체 예제 코드

### JavaScript/TypeScript (Axios)

```typescript
import axios from 'axios';

const API_BASE_URL = 'http://localhost:3000/api/asst/v1';
const AUTH_TOKEN = 'Bearer YOUR_TOKEN';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'x-auth-token': AUTH_TOKEN,
    'Content-Type': 'application/json',
  },
});

// 상담사 생성
async function createAgent() {
  try {
    const response = await apiClient.post('/agents', {
      id: 'agent_123',
      name: '홍길동',
      email: 'agent@example.com',
      status: 'UNKNOWN',
    });
    console.log('상담사 생성 성공:', response.data);
  } catch (error) {
    console.error('상담사 생성 실패:', error.response?.data);
  }
}

// 상담사 전체 조회
async function getAllAgents() {
  try {
    const response = await apiClient.get('/agents');
    console.log('상담사 목록:', response.data);
  } catch (error) {
    console.error('상담사 조회 실패:', error.response?.data);
  }
}

// 상담사 수정
async function updateAgent(agentId: string) {
  try {
    const response = await apiClient.put(`/agents/${agentId}`, {
      name: '홍길동 (수정)',
      extension: '9999',
    });
    console.log('상담사 수정 성공:', response.data);
  } catch (error) {
    console.error('상담사 수정 실패:', error.response?.data);
  }
}

// 상담사 삭제
async function deleteAgent(agentId: string) {
  try {
    await apiClient.delete(`/agents/${agentId}`);
    console.log('상담사 삭제 성공');
  } catch (error) {
    console.error('상담사 삭제 실패:', error.response?.data);
  }
}

// 그룹 생성
async function createGroup() {
  try {
    const response = await apiClient.post('/groups', {
      name: '고객센터 1팀',
      description: '고객센터 1팀 그룹입니다.',
    });
    console.log('그룹 생성 성공:', response.data);
  } catch (error) {
    console.error('그룹 생성 실패:', error.response?.data);
  }
}

// 그룹에 상담사 배치
async function assignAgentsToGroup(groupId: string, agentIds: string[]) {
  try {
    const response = await apiClient.post('/groups/assign-agents', {
      group_id: groupId,
      agent_ids: agentIds,
    });
    console.log('상담사 배치 성공:', response.data);
  } catch (error) {
    console.error('상담사 배치 실패:', error.response?.data);
  }
}

// 상담사 상태 수정
async function updateAgentStatus(agentId: string, status: string) {
  try {
    const response = await apiClient.put('/agents/status', {
      agent_id: agentId,
      status: status,
    });
    console.log('상담사 상태 수정 성공:', response.data);
  } catch (error) {
    console.error('상담사 상태 수정 실패:', error.response?.data);
  }
}

// 상태별 상담사 조회
async function getAgentsByStatus(status: string) {
  try {
    const response = await apiClient.get(`/agents/status/${status}`);
    console.log(`${status} 상태 상담사 목록:`, response.data);
  } catch (error) {
    console.error('상담사 조회 실패:', error.response?.data);
  }
}
```

### Python (requests)

```python
import requests

API_BASE_URL = 'http://localhost:3000/api/asst/v1'
AUTH_TOKEN = 'Bearer YOUR_TOKEN'

headers = {
    'x-auth-token': AUTH_TOKEN,
    'Content-Type': 'application/json',
}

# 상담사 생성
def create_agent():
    data = {
        'id': 'agent_123',
        'name': '홍길동',
        'email': 'agent@example.com',
        'status': 'UNKNOWN',
    }
    response = requests.post(
        f'{API_BASE_URL}/agents',
        json=data,
        headers=headers
    )
    if response.status_code == 201:
        print('상담사 생성 성공:', response.json())
    else:
        print('상담사 생성 실패:', response.json())

# 상담사 전체 조회
def get_all_agents():
    response = requests.get(
        f'{API_BASE_URL}/agents',
        headers=headers
    )
    if response.status_code == 200:
        print('상담사 목록:', response.json())
    else:
        print('상담사 조회 실패:', response.json())

# 상담사 상태 수정
def update_agent_status(agent_id, status):
    data = {
        'agent_id': agent_id,
        'status': status,
    }
    response = requests.put(
        f'{API_BASE_URL}/agents/status',
        json=data,
        headers=headers
    )
    if response.status_code == 200:
        print('상담사 상태 수정 성공:', response.json())
    else:
        print('상담사 상태 수정 실패:', response.json())
```

### Vue.js (Composition API)

```vue
<template>
  <div>
    <h2>상담사 관리</h2>
    <button @click="loadAgents">상담사 목록 조회</button>
    <button @click="createAgent">상담사 생성</button>
    <button @click="updateAgentStatus('agent_123', 'ACTIVE')">상태 변경</button>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import axios from 'axios';

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:3000/api/asst/v1';
const AUTH_TOKEN = 'Bearer YOUR_TOKEN';

const agents = ref([]);

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'x-auth-token': AUTH_TOKEN,
    'Content-Type': 'application/json',
  },
});

const loadAgents = async () => {
  try {
    const response = await apiClient.get('/agents');
    agents.value = response.data;
  } catch (error) {
    console.error('상담사 조회 실패:', error.response?.data);
  }
};

const createAgent = async () => {
  try {
    const response = await apiClient.post('/agents', {
      id: 'agent_123',
      name: '홍길동',
      email: 'agent@example.com',
    });
    console.log('상담사 생성 성공:', response.data);
    await loadAgents();
  } catch (error) {
    console.error('상담사 생성 실패:', error.response?.data);
  }
};

const updateAgentStatus = async (agentId, status) => {
  try {
    const response = await apiClient.put('/agents/status', {
      agent_id: agentId,
      status: status,
    });
    console.log('상담사 상태 수정 성공:', response.data);
    await loadAgents();
  } catch (error) {
    console.error('상담사 상태 수정 실패:', error.response?.data);
  }
};
</script>
```

---

## 참고 문서

- [상담사 상태 공유 기능 가이드 (Socket.IO)](./agent-status-socket-guide.md)
- [Swagger API 문서](http://localhost:3000/api/asst/v1/doc)

---

## 문의

API 관련 문의사항이 있으시면 개발팀에 문의해주세요.
