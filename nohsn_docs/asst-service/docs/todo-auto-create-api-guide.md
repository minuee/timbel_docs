# 할일 자동 생성 API 연동 가이드

## 📋 목차

1. [개요](#개요)
2. [인증](#인증)
3. [API 기본 정보](#api-기본-정보)
4. [할일 자동 생성 API](#할일-자동-생성-api)
5. [에러 처리](#에러-처리)
6. [전체 예제 코드](#전체-예제-코드)
7. [LLM 서비스 연동](#llm-서비스-연동)

---

## 개요

할일 자동 생성 기능은 LLM(대규모 언어 모델)을 사용하여 통화내역을 분석하고 자동으로 할일을 생성합니다.

### 주요 기능

- ✅ 통화내역 기반 할일 자동 생성
- ✅ LLM을 통한 지능형 할일 추출
- ✅ 최대 길이 및 간단한 할일 포함 옵션
- ✅ 자동으로 todos 테이블에 저장

### 동작 흐름

```
1. 클라이언트 요청 (callstats_id, maxLength, includeSimple, user_key)
   ↓
2. callstats_turn 테이블에서 통화내역 조회
   ↓
3. 통화내역 텍스트 구성 (role: utterance 형식)
   ↓
4. LLM API 호출
   ↓
5. LLM 응답 (todos 배열)
   ↓
6. todos 테이블에 저장
   ↓
7. 생성된 할일 목록 반환
```

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

## 할일 자동 생성 API

### 할일 자동 생성

LLM을 사용하여 통화내역을 분석하여 할일을 자동으로 생성합니다.

**엔드포인트**: `POST /todos/auto-create`

**요청 본문**:

```json
{
  "callstats_id": "callstats_123",
  "maxLength": 100,
  "includeSimple": true,
  "user_key": "user_123"
}
```

**요청 예시**:

```bash
curl -X POST "http://localhost:3000/api/asst/v1/todos/auto-create" \
  -H "x-auth-token: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "callstats_id": "callstats_123",
    "maxLength": 100,
    "includeSimple": true,
    "user_key": "user_123"
  }'
```

**응답 예시** (201 Created):

```json
[
  {
    "id": "todo_550e8400-e29b-41d4-a716-446655440000",
    "user_key": "user_123",
    "callstats_id": "callstats_123",
    "title": "고객 문의사항 처리",
    "state": 0,
    "created_at": "2024-01-01T00:00:00.000Z",
    "updated_at": "2024-01-01T00:00:00.000Z"
  },
  {
    "id": "todo_550e8400-e29b-41d4-a716-446655440001",
    "user_key": "user_123",
    "callstats_id": "callstats_123",
    "title": "후속 조치 확인",
    "state": 0,
    "created_at": "2024-01-01T00:00:00.000Z",
    "updated_at": "2024-01-01T00:00:00.000Z"
  },
  {
    "id": "todo_550e8400-e29b-41d4-a716-446655440002",
    "user_key": "user_123",
    "callstats_id": "callstats_123",
    "title": "상품 정보 전달",
    "state": 0,
    "created_at": "2024-01-01T00:00:00.000Z",
    "updated_at": "2024-01-01T00:00:00.000Z"
  }
]
```

**필드 설명**:

| 필드          | 타입    | 필수 | 설명                    |
| ------------- | ------- | ---- | ----------------------- |
| callstats_id  | string  | ✅   | 통화 통계 ID            |
| maxLength     | number  | ✅   | 할일 제목의 최대 길이   |
| includeSimple | boolean | ✅   | 간단한 할일 포함 여부   |
| user_key      | string  | ✅   | 사용자 키 (할일 소유자) |

**동작 과정**:

1. **통화내역 조회**: `callstats_id`로 `raw_call.callstats_turn` 테이블에서 턴 데이터 조회
2. **텍스트 구성**: 턴 데이터를 `role: utterance` 형식으로 조합하여 통화내역 텍스트 생성
3. **LLM 호출**: LLM 서비스에 통화내역, maxLength, includeSimple 전달
4. **할일 저장**: LLM이 반환한 할일 목록을 `todos` 테이블에 저장
5. **결과 반환**: 생성된 할일 목록 반환

**참고사항**:

- 생성된 할일의 `state`는 기본값 `0` (진행중)으로 설정됩니다.
- 할일 ID는 자동으로 `todo_{uuid_v4}` 형식으로 생성됩니다.
- LLM이 할일을 생성하지 않은 경우 빈 배열(`[]`)을 반환합니다.

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
| 502  | LLM 서비스 연결 오류  |
| 503  | LLM 서비스 이용 불가  |
| 500  | 서버 내부 오류        |

### 에러 예시

**404 Not Found** (통화 턴 데이터 없음):

```json
{
  "statusCode": 404,
  "message": "통화 턴 데이터가 없습니다: callstats_id=callstats_999",
  "error": "Not Found"
}
```

**400 Bad Request** (잘못된 요청):

```json
{
  "statusCode": 400,
  "message": [
    "callstats_id should not be empty",
    "maxLength must be a positive number",
    "includeSimple must be a boolean value"
  ],
  "error": "Bad Request"
}
```

**502 Bad Gateway** (LLM 서비스 오류):

```json
{
  "statusCode": 502,
  "message": "LLM 할일 자동 생성 서비스 오류: 500 Internal Server Error",
  "error": "Bad Gateway"
}
```

**503 Service Unavailable** (LLM 서비스 연결 불가):

```json
{
  "statusCode": 503,
  "message": "LLM 할일 자동 생성 서비스에 연결할 수 없습니다.",
  "error": "Service Unavailable"
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

// 할일 자동 생성
async function autoCreateTodos(
  callstatsId: string,
  maxLength: number,
  includeSimple: boolean,
  userKey: string,
) {
  try {
    const response = await apiClient.post('/todos/auto-create', {
      callstats_id: callstatsId,
      maxLength: maxLength,
      includeSimple: includeSimple,
      user_key: userKey,
    });

    console.log('할일 자동 생성 성공:', response.data);
    console.log(`생성된 할일 수: ${response.data.length}개`);

    return response.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      if (error.response) {
        console.error('할일 자동 생성 실패:', error.response.data);
        console.error('상태 코드:', error.response.status);
      } else if (error.request) {
        console.error('서버에 연결할 수 없습니다.');
      }
    } else {
      console.error('예상치 못한 오류:', error);
    }
    throw error;
  }
}

// 사용 예시
async function example() {
  try {
    const todos = await autoCreateTodos('callstats_123', 100, true, 'user_123');

    todos.forEach((todo, index) => {
      console.log(`${index + 1}. ${todo.title}`);
    });
  } catch (error) {
    console.error('할일 자동 생성 중 오류 발생:', error);
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

def auto_create_todos(callstats_id, max_length, include_simple, user_key):
    """
    할일을 자동 생성합니다.

    Args:
        callstats_id: 통화 통계 ID
        max_length: 할일 제목의 최대 길이
        include_simple: 간단한 할일 포함 여부
        user_key: 사용자 키

    Returns:
        생성된 할일 목록
    """
    url = f'{API_BASE_URL}/todos/auto-create'
    data = {
        'callstats_id': callstats_id,
        'maxLength': max_length,
        'includeSimple': include_simple,
        'user_key': user_key,
    }

    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()

        todos = response.json()
        print(f'할일 자동 생성 성공: {len(todos)}개 생성됨')

        for index, todo in enumerate(todos, 1):
            print(f'{index}. {todo["title"]}')

        return todos
    except requests.exceptions.HTTPError as e:
        print(f'HTTP 오류: {e.response.status_code}')
        print(f'오류 메시지: {e.response.json()}')
        raise
    except requests.exceptions.RequestException as e:
        print(f'요청 오류: {e}')
        raise

# 사용 예시
if __name__ == '__main__':
    try:
        todos = auto_create_todos(
            callstats_id='callstats_123',
            max_length=100,
            include_simple=True,
            user_key='user_123'
        )
    except Exception as e:
        print(f'할일 자동 생성 중 오류 발생: {e}')
```

### Vue.js (Composition API)

```vue
<template>
  <div>
    <h2>할일 자동 생성</h2>

    <div class="form-group">
      <label>통화 통계 ID:</label>
      <input v-model="form.callstats_id" type="text" />
    </div>

    <div class="form-group">
      <label>최대 길이:</label>
      <input v-model.number="form.maxLength" type="number" min="1" />
    </div>

    <div class="form-group">
      <label>
        <input v-model="form.includeSimple" type="checkbox" />
        간단한 할일 포함
      </label>
    </div>

    <div class="form-group">
      <label>사용자 키:</label>
      <input v-model="form.user_key" type="text" />
    </div>

    <button @click="handleAutoCreate" :disabled="loading">
      {{ loading ? '생성 중...' : '할일 자동 생성' }}
    </button>

    <div v-if="createdTodos.length > 0" class="todos-list">
      <h3>생성된 할일 ({{ createdTodos.length }}개)</h3>
      <ul>
        <li v-for="todo in createdTodos" :key="todo.id">
          {{ todo.title }}
        </li>
      </ul>
    </div>

    <div v-if="error" class="error-message">
      {{ error }}
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import axios from 'axios';

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:3000/api/asst/v1';
const AUTH_TOKEN = 'Bearer YOUR_TOKEN';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'x-auth-token': AUTH_TOKEN,
    'Content-Type': 'application/json',
  },
});

const form = ref({
  callstats_id: '',
  maxLength: 100,
  includeSimple: true,
  user_key: '',
});

const loading = ref(false);
const createdTodos = ref([]);
const error = ref('');

const handleAutoCreate = async () => {
  if (!form.value.callstats_id || !form.value.user_key) {
    error.value = '통화 통계 ID와 사용자 키는 필수입니다.';
    return;
  }

  loading.value = true;
  error.value = '';
  createdTodos.value = [];

  try {
    const response = await apiClient.post('/todos/auto-create', {
      callstats_id: form.value.callstats_id,
      maxLength: form.value.maxLength,
      includeSimple: form.value.includeSimple,
      user_key: form.value.user_key,
    });

    createdTodos.value = response.data;
    console.log(`할일 자동 생성 성공: ${response.data.length}개 생성됨`);
  } catch (err) {
    if (axios.isAxiosError(err)) {
      if (err.response) {
        error.value = `오류: ${err.response.data.message || err.message}`;
      } else {
        error.value = '서버에 연결할 수 없습니다.';
      }
    } else {
      error.value = '예상치 못한 오류가 발생했습니다.';
    }
    console.error('할일 자동 생성 실패:', err);
  } finally {
    loading.value = false;
  }
};
</script>

<style scoped>
.form-group {
  margin-bottom: 1rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
}

.form-group input {
  width: 100%;
  padding: 0.5rem;
}

.todos-list {
  margin-top: 2rem;
}

.todos-list ul {
  list-style-type: none;
  padding: 0;
}

.todos-list li {
  padding: 0.5rem;
  border-bottom: 1px solid #ddd;
}

.error-message {
  color: red;
  margin-top: 1rem;
}
</style>
```

### React (Hooks)

```tsx
import React, { useState } from 'react';
import axios from 'axios';

const API_BASE_URL = 'http://localhost:3000/api/asst/v1';
const AUTH_TOKEN = 'Bearer YOUR_TOKEN';

interface Todo {
  id: string;
  user_key: string;
  callstats_id: string;
  title: string;
  state: number;
  created_at: string;
  updated_at: string;
}

function AutoCreateTodos() {
  const [form, setForm] = useState({
    callstats_id: '',
    maxLength: 100,
    includeSimple: true,
    user_key: '',
  });
  const [loading, setLoading] = useState(false);
  const [createdTodos, setCreatedTodos] = useState<Todo[]>([]);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!form.callstats_id || !form.user_key) {
      setError('통화 통계 ID와 사용자 키는 필수입니다.');
      return;
    }

    setLoading(true);
    setError('');
    setCreatedTodos([]);

    try {
      const response = await axios.post(
        `${API_BASE_URL}/todos/auto-create`,
        {
          callstats_id: form.callstats_id,
          maxLength: form.maxLength,
          includeSimple: form.includeSimple,
          user_key: form.user_key,
        },
        {
          headers: {
            'x-auth-token': AUTH_TOKEN,
            'Content-Type': 'application/json',
          },
        },
      );

      setCreatedTodos(response.data);
      console.log(`할일 자동 생성 성공: ${response.data.length}개 생성됨`);
    } catch (err) {
      if (axios.isAxiosError(err)) {
        if (err.response) {
          setError(`오류: ${err.response.data.message || err.message}`);
        } else {
          setError('서버에 연결할 수 없습니다.');
        }
      } else {
        setError('예상치 못한 오류가 발생했습니다.');
      }
      console.error('할일 자동 생성 실패:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2>할일 자동 생성</h2>

      <form onSubmit={handleSubmit}>
        <div>
          <label>
            통화 통계 ID:
            <input
              type="text"
              value={form.callstats_id}
              onChange={(e) =>
                setForm({ ...form, callstats_id: e.target.value })
              }
              required
            />
          </label>
        </div>

        <div>
          <label>
            최대 길이:
            <input
              type="number"
              min="1"
              value={form.maxLength}
              onChange={(e) =>
                setForm({ ...form, maxLength: parseInt(e.target.value) })
              }
              required
            />
          </label>
        </div>

        <div>
          <label>
            <input
              type="checkbox"
              checked={form.includeSimple}
              onChange={(e) =>
                setForm({ ...form, includeSimple: e.target.checked })
              }
            />
            간단한 할일 포함
          </label>
        </div>

        <div>
          <label>
            사용자 키:
            <input
              type="text"
              value={form.user_key}
              onChange={(e) => setForm({ ...form, user_key: e.target.value })}
              required
            />
          </label>
        </div>

        <button type="submit" disabled={loading}>
          {loading ? '생성 중...' : '할일 자동 생성'}
        </button>
      </form>

      {createdTodos.length > 0 && (
        <div>
          <h3>생성된 할일 ({createdTodos.length}개)</h3>
          <ul>
            {createdTodos.map((todo) => (
              <li key={todo.id}>{todo.title}</li>
            ))}
          </ul>
        </div>
      )}

      {error && <div style={{ color: 'red' }}>{error}</div>}
    </div>
  );
}

export default AutoCreateTodos;
```

---

## LLM 서비스 연동

### LLM 서비스 엔드포인트

할일 자동 생성 기능은 외부 LLM 서비스를 사용합니다.

**엔드포인트**: `POST {LLM_HOST}/api/llm-manager/v1/llm/adv/todos/auto-create`

**요청 본문**:

```json
{
  "callStat": "customer: 안녕하세요\nagent: 네, 안녕하세요. 무엇을 도와드릴까요?\ncustomer: 상품 문의가 있습니다.",
  "maxLength": 100,
  "includeSimple": true
}
```

**응답 형식**:

```json
{
  "todos": ["고객 문의사항 처리", "후속 조치 확인", "상품 정보 전달"]
}
```

### 환경 변수 설정

LLM 서비스 호스트는 환경 변수로 설정합니다:

```bash
LLM_HOST=http://llm-service.example.com
```

### LLM 서비스 요구사항

- **엔드포인트**: `/api/llm-manager/v1/llm/adv/todos/auto-create`
- **메서드**: `POST`
- **Content-Type**: `application/json`
- **요청 본문**:
  - `callStat` (string): 통화내역 텍스트
  - `maxLength` (number): 할일 제목의 최대 길이
  - `includeSimple` (boolean): 간단한 할일 포함 여부
- **응답 형식**:
  - `todos` (string[]): 생성된 할일 제목 배열

---

## 통화내역 텍스트 구성

서버는 `callstats_turn` 테이블에서 조회한 데이터를 다음과 같은 형식으로 구성합니다:

```
customer: 고객의 첫 번째 발화
agent: 상담사의 첫 번째 응답
customer: 고객의 두 번째 발화
agent: 상담사의 두 번째 응답
...
```

**예시**:

```
customer: 안녕하세요, 상품 문의가 있습니다.
agent: 네, 안녕하세요. 어떤 상품에 대해 문의하시나요?
customer: A 상품의 가격과 기능을 알고 싶습니다.
agent: A 상품은 100,000원이며, 다음과 같은 기능이 있습니다...
customer: 감사합니다. 후속 조치가 필요하면 연락드리겠습니다.
agent: 네, 감사합니다. 좋은 하루 되세요.
```

이 텍스트가 LLM 서비스에 전달되어 할일이 자동으로 생성됩니다.

---

## 사용 시나리오

### 시나리오 1: 통화 후 즉시 할일 생성

```typescript
// 통화가 끝난 직후 할일 자동 생성
async function afterCall(callstatsId: string, userId: string) {
  try {
    const todos = await autoCreateTodos(
      callstatsId,
      100, // 최대 길이
      true, // 간단한 할일 포함
      userId,
    );

    // 생성된 할일을 사용자에게 표시
    showNotification(`할일 ${todos.length}개가 자동 생성되었습니다.`);
  } catch (error) {
    console.error('할일 자동 생성 실패:', error);
  }
}
```

### 시나리오 2: 상세한 할일만 생성

```typescript
// 간단한 할일 제외하고 상세한 할일만 생성
async function createDetailedTodos(callstatsId: string, userId: string) {
  try {
    const todos = await autoCreateTodos(
      callstatsId,
      200, // 더 긴 제목 허용
      false, // 간단한 할일 제외
      userId,
    );

    return todos;
  } catch (error) {
    console.error('상세 할일 생성 실패:', error);
    throw error;
  }
}
```

### 시나리오 3: 할일 생성 후 목록 새로고침

```typescript
// 할일 자동 생성 후 목록 조회
async function createAndRefreshTodos(callstatsId: string, userId: string) {
  try {
    // 할일 자동 생성
    const createdTodos = await autoCreateTodos(callstatsId, 100, true, userId);

    console.log(`생성된 할일: ${createdTodos.length}개`);

    // 할일 목록 조회
    const allTodos = await apiClient.get('/todos', {
      params: {
        user_key: userId,
      },
    });

    return allTodos.data;
  } catch (error) {
    console.error('할일 생성 및 조회 실패:', error);
    throw error;
  }
}
```

---

## 주의사항

### 1. 통화 턴 데이터 필요

- `callstats_id`에 해당하는 통화 턴 데이터가 `raw_call.callstats_turn` 테이블에 존재해야 합니다.
- 턴 데이터가 없으면 `404 Not Found` 오류가 발생합니다.

### 2. LLM 서비스 가용성

- LLM 서비스가 사용 불가능한 경우 `503 Service Unavailable` 오류가 발생합니다.
- LLM 서비스 응답이 지연될 수 있으므로 타임아웃(30초)이 설정되어 있습니다.

### 3. 할일 생성 실패 처리

- LLM이 할일을 생성하지 않은 경우 빈 배열(`[]`)을 반환합니다.
- 일부 할일만 생성되는 경우도 있을 수 있으므로, 항상 응답 배열의 길이를 확인하세요.

### 4. 중복 생성 방지

- 동일한 `callstats_id`로 여러 번 호출하면 중복된 할일이 생성될 수 있습니다.
- 필요시 클라이언트 측에서 중복 생성 방지 로직을 구현하세요.

---

## 참고 문서

- [상담사 및 그룹 관리 API 가이드](./agents-groups-api-guide.md)
- [공지사항 API 및 Socket.IO 가이드](./notices-api-socket-guide.md)
- [Swagger API 문서](http://localhost:3000/api/asst/v1/doc)

---

## 문의

API 관련 문의사항이 있으시면 개발팀에 문의해주세요.
