# 코칭 알림 기능 연동 가이드 (Frontend)

## 📋 목차

1. [개요](#개요)
2. [시스템 아키텍처](#시스템-아키텍처)
3. [Socket.IO 연결 설정](#socketio-연결-설정)
4. [Coaching Room 참여](#coaching-room-참여)
5. [알림 수신](#알림-수신)
6. [API 엔드포인트](#api-엔드포인트)
7. [전체 예제 코드](#전체-예제-코드)
8. [트러블슈팅](#트러블슈팅)

---

## 개요

코칭 알림 기능은 **Redis Pub/Sub**과 **Socket.IO**를 사용하여 실시간으로 코칭 요청 및 코칭 메시지를 수신자에게 전달합니다.

### 주요 특징

- ✅ 실시간 푸시 알림
- ✅ Room 기반 타겟팅 (user_key 기반)
- ✅ 자동 재연결 지원
- ✅ 읽음/안읽음 상태 관리
- ✅ 중요도 및 우선순위 표시

---

## 시스템 아키텍처

```
┌─────────────┐
│  Frontend   │
│  (Socket)   │
└──────┬──────┘
       │ WebSocket
       │ join: coaching_{user_key}
       ↓
┌─────────────────────┐
│  Backend Server     │
│  (Socket.IO)        │
└──────┬──────────────┘
       │
       ├─→ Redis Pub/Sub ←─┐
       │                   │
       │              ┌────┴─────┐
       │              │ Coaching │
       │              │ Service  │
       │              └──────────┘
       ↓
  Room: coaching_{receiver_key}
       ↓
  Frontend (수신자)
```

### 메시지 흐름

1. **코칭 요청 생성** → DB 저장 → Redis Pub → Socket.IO Emit → Frontend 수신
2. **코칭 생성** → DB 저장 → Redis Pub → Socket.IO Emit → Frontend 수신

---

## Socket.IO 연결 설정

### 1. Socket.IO 클라이언트 설치

```bash
npm install socket.io-client
# or
yarn add socket.io-client
```

### 2. Socket 연결 생성

```typescript
import { io, Socket } from 'socket.io-client';

// Socket.IO 서버 URL
const SOCKET_URL =
  process.env.NEXT_PUBLIC_SOCKET_URL || 'wss://your-server.com';

// Socket 인스턴스 생성
const socket: Socket = io(SOCKET_URL, {
  transports: ['websocket', 'polling'],
  reconnection: true,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
  reconnectionAttempts: 5,
  timeout: 20000,
});

// 연결 상태 이벤트
socket.on('connect', () => {
  console.log('✅ Socket.IO 연결 성공:', socket.id);
});

socket.on('disconnect', (reason) => {
  console.log('🔌 Socket.IO 연결 해제:', reason);
});

socket.on('connect_error', (error) => {
  console.error('❌ Socket.IO 연결 오류:', error);
});

socket.on('connection-confirmed', (data) => {
  console.log('✅ 서버 연결 확인:', data);
  // data.clientId, data.timestamp
});
```

---

## Coaching Room 참여

사용자는 자신의 `user_key`를 사용하여 **`coaching_{user_key}`** room에 참여해야 합니다.

### Room 참여 방법

```typescript
interface User {
  user_key: string;
  name: string;
  // ... 기타 필드
}

function joinCoachingRoom(user: User) {
  const roomName = `coaching_${user.user_key}`;

  console.log(`🏠 Coaching room 참여: ${roomName}`);

  // Room 참여
  socket.emit('join-room', roomName);

  // 참여 성공 이벤트
  socket.on('join-room-success', (data) => {
    console.log('✅ Room 참여 성공:', data);
    // data.room, data.clientCount
  });

  // 참여 실패 이벤트
  socket.on('join-room-error', (data) => {
    console.error('❌ Room 참여 실패:', data);
    // data.error, data.message
  });
}
```

### Room 나가기 (선택사항)

```typescript
function leaveCoachingRoom(user: User) {
  const roomName = `coaching_${user.user_key}`;

  console.log(`🚪 Coaching room 나가기: ${roomName}`);

  socket.emit('leave-room', roomName);

  socket.on('leave-room-success', (data) => {
    console.log('✅ Room 나가기 성공:', data);
  });
}
```

---

## 알림 수신

### 1. 코칭 요청 알림

사용자가 **수신자(receiver)**일 때 받는 코칭 요청 알림입니다.

```typescript
interface CoachingRequestPayload {
  id: string; // 코칭 요청 ID (예: coachrq_uuid)
  call_id: string; // 통화 ID
  sender_key: string; // 발신자 user_key
  receiver_key: string; // 수신자 user_key (본인)
  content: string | null; // 요청 내용
  is_read: boolean; // 읽음 여부 (생성 시 false)
  is_important: boolean; // 중요 표시
  priority_type: number; // 0: 일반, 1: 긴급
  created_at: string; // 생성일시 (ISO 8601)
  updated_at: string; // 수정일시 (ISO 8601)
}

interface CoachingRequestNotification {
  event: 'coaching_request';
  payload: CoachingRequestPayload;
}

// 코칭 요청 알림 수신
socket.on('coaching_request', (data: CoachingRequestNotification) => {
  console.log('📨 새로운 코칭 요청:', data);

  const { payload } = data;

  // UI 알림 표시
  showNotification({
    title:
      payload.priority_type === 1 ? '🚨 긴급 코칭 요청' : '📝 새로운 코칭 요청',
    message: payload.content || '새로운 코칭 요청이 도착했습니다.',
    isImportant: payload.is_important,
    data: payload,
  });

  // 상태 업데이트
  updateCoachingRequestList(payload);

  // 배지 카운트 증가
  incrementUnreadBadge('coaching_request');
});
```

### 2. 코칭 알림

사용자가 **수신자(receiver)**일 때 받는 코칭 메시지 알림입니다.

```typescript
interface CoachingPayload {
  id: string; // 코칭 ID (예: coach_uuid)
  call_id: string; // 통화 ID
  coaching_request_id: string | null; // 연관된 코칭 요청 ID (없을 수도 있음)
  sender_key: string; // 발신자 user_key
  receiver_key: string; // 수신자 user_key (본인)
  content: string | null; // 코칭 내용
  is_read: boolean; // 읽음 여부 (생성 시 false)
  is_important: boolean; // 중요 표시
  priority_type: number; // 0: 일반, 1: 긴급
  created_at: string; // 생성일시 (ISO 8601)
  updated_at: string; // 수정일시 (ISO 8601)
}

interface CoachingNotification {
  event: 'coaching';
  payload: CoachingPayload;
}

// 코칭 알림 수신
socket.on('coaching', (data: CoachingNotification) => {
  console.log('📨 새로운 코칭:', data);

  const { payload } = data;

  // UI 알림 표시
  showNotification({
    title: payload.priority_type === 1 ? '🚨 긴급 코칭' : '💬 새로운 코칭',
    message: payload.content || '새로운 코칭 메시지가 도착했습니다.',
    isImportant: payload.is_important,
    data: payload,
  });

  // 상태 업데이트
  updateCoachingList(payload);

  // 배지 카운트 증가
  incrementUnreadBadge('coaching');
});
```

---

## API 엔드포인트

### 코칭 요청 API

#### 1. 코칭 요청 생성

```typescript
// POST /api/asst/v1/coachings/requests
interface CreateCoachingRequestDto {
  call_id: string; // 필수
  sender_key: string; // 필수
  receiver_key: string; // 필수
  content?: string; // 선택
  is_important?: boolean; // 선택 (기본: false)
  priority_type?: number; // 선택 (0: 일반, 1: 긴급)
}

const response = await fetch('/api/asst/v1/coachings/requests', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  },
  body: JSON.stringify({
    call_id: 'call_12345',
    sender_key: 'user_001',
    receiver_key: 'user_002',
    content: '이 통화에서 고객 응대 방법을 코칭해주세요.',
    is_important: true,
    priority_type: 1,
  }),
});

const coachingRequest = await response.json();
// → 생성 즉시 수신자에게 Socket.IO로 알림 전송
```

#### 2. 발신자별 코칭 요청 조회

```typescript
// GET /api/asst/v1/coachings/requests/sender/{senderKey}?is_read=false&page=1&limit=10
const response = await fetch(
  `/api/asst/v1/coachings/requests/sender/${userKey}?is_read=false&page=1&limit=10`,
  {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  },
);

const result = await response.json();
// result: { data, total, page, limit, totalPages, hasNext, hasPrev }
```

#### 3. 수신자별 코칭 요청 조회 (받은 요청)

```typescript
// GET /api/asst/v1/coachings/requests/receiver/{receiverKey}?is_read=false
const response = await fetch(
  `/api/asst/v1/coachings/requests/receiver/${userKey}?is_read=false&is_important=true`,
  {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  },
);

const result = await response.json();
```

#### 4. 코칭 요청 읽음 처리

```typescript
// PATCH /api/asst/v1/coachings/requests/{id}/read
const response = await fetch(
  `/api/asst/v1/coachings/requests/${requestId}/read`,
  {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  },
);

const updatedRequest = await response.json();
// updatedRequest.is_read === true
```

### 코칭 API

#### 1. 코칭 생성

```typescript
// POST /api/asst/v1/coachings
interface CreateCoachingDto {
  call_id: string; // 필수
  sender_key: string; // 필수
  receiver_key: string; // 필수
  coaching_request_id?: string; // 선택 (연관된 요청 ID)
  content?: string; // 선택
  is_important?: boolean; // 선택 (기본: false)
  priority_type?: number; // 선택 (0: 일반, 1: 긴급)
}

const response = await fetch('/api/asst/v1/coachings', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  },
  body: JSON.stringify({
    call_id: 'call_12345',
    sender_key: 'user_001',
    receiver_key: 'user_002',
    coaching_request_id: 'coachrq_uuid', // 요청에 대한 응답인 경우
    content: '고객 응대 시 더 부드러운 톤으로 대화해주세요.',
    is_important: false,
    priority_type: 0,
  }),
});

const coaching = await response.json();
// → 생성 즉시 수신자에게 Socket.IO로 알림 전송
```

#### 2. 통화별 코칭 조회

```typescript
// GET /api/asst/v1/coachings/call/{callId}
const response = await fetch(`/api/asst/v1/coachings/call/${callId}`, {
  headers: {
    Authorization: `Bearer ${token}`,
  },
});

const result = await response.json();
// result: { requests: CoachingRequest[], coachings: Coaching[] }
```

#### 3. 수신자별 코칭 조회

```typescript
// GET /api/asst/v1/coachings/receiver/{receiverKey}?is_read=false
const response = await fetch(
  `/api/asst/v1/coachings/receiver/${userKey}?is_read=false`,
  {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  },
);

const result = await response.json();
// Pagination 결과
```

#### 4. 코칭 읽음 처리

```typescript
// PATCH /api/asst/v1/coachings/{id}/read
const response = await fetch(`/api/asst/v1/coachings/${coachingId}/read`, {
  method: 'PATCH',
  headers: {
    Authorization: `Bearer ${token}`,
  },
});

const updatedCoaching = await response.json();
// updatedCoaching.is_read === true
```

---

## 전체 예제 코드

### React/Next.js 예제

```typescript
// hooks/useCoachingNotifications.ts
import { useEffect, useState, useCallback } from 'react';
import { io, Socket } from 'socket.io-client';

interface User {
  user_key: string;
  name: string;
}

interface CoachingRequestPayload {
  id: string;
  call_id: string;
  sender_key: string;
  receiver_key: string;
  content: string | null;
  is_read: boolean;
  is_important: boolean;
  priority_type: number;
  created_at: string;
  updated_at: string;
}

interface CoachingPayload {
  id: string;
  call_id: string;
  coaching_request_id: string | null;
  sender_key: string;
  receiver_key: string;
  content: string | null;
  is_read: boolean;
  is_important: boolean;
  priority_type: number;
  created_at: string;
  updated_at: string;
}

export function useCoachingNotifications(user: User) {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [coachingRequests, setCoachingRequests] = useState<
    CoachingRequestPayload[]
  >([]);
  const [coachings, setCoachings] = useState<CoachingPayload[]>([]);
  const [unreadCount, setUnreadCount] = useState({ requests: 0, coachings: 0 });

  // Socket 초기화
  useEffect(() => {
    const socketInstance = io(process.env.NEXT_PUBLIC_SOCKET_URL!, {
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 5,
    });

    setSocket(socketInstance);

    // 연결 이벤트
    socketInstance.on('connect', () => {
      console.log('✅ Socket 연결:', socketInstance.id);
      setIsConnected(true);

      // Coaching room 자동 참여
      const roomName = `coaching_${user.user_key}`;
      socketInstance.emit('join-room', roomName);
    });

    socketInstance.on('disconnect', (reason) => {
      console.log('🔌 Socket 연결 해제:', reason);
      setIsConnected(false);
    });

    socketInstance.on('join-room-success', (data) => {
      console.log('✅ Room 참여 성공:', data.room);
    });

    // 코칭 요청 알림 수신
    socketInstance.on(
      'coaching_request',
      (data: {
        event: 'coaching_request';
        payload: CoachingRequestPayload;
      }) => {
        console.log('📨 새로운 코칭 요청:', data.payload);

        // 리스트에 추가
        setCoachingRequests((prev) => [data.payload, ...prev]);

        // 안읽음 카운트 증가
        setUnreadCount((prev) => ({
          ...prev,
          requests: prev.requests + 1,
        }));

        // 알림 표시
        if (Notification.permission === 'granted') {
          new Notification(
            data.payload.priority_type === 1
              ? '🚨 긴급 코칭 요청'
              : '📝 새로운 코칭 요청',
            {
              body: data.payload.content || '새로운 코칭 요청이 도착했습니다.',
              icon: '/icons/coaching.png',
              badge: '/icons/badge.png',
            },
          );
        }
      },
    );

    // 코칭 알림 수신
    socketInstance.on(
      'coaching',
      (data: { event: 'coaching'; payload: CoachingPayload }) => {
        console.log('📨 새로운 코칭:', data.payload);

        // 리스트에 추가
        setCoachings((prev) => [data.payload, ...prev]);

        // 안읽음 카운트 증가
        setUnreadCount((prev) => ({
          ...prev,
          coachings: prev.coachings + 1,
        }));

        // 알림 표시
        if (Notification.permission === 'granted') {
          new Notification(
            data.payload.priority_type === 1
              ? '🚨 긴급 코칭'
              : '💬 새로운 코칭',
            {
              body: data.payload.content || '새로운 코칭이 도착했습니다.',
              icon: '/icons/coaching.png',
            },
          );
        }
      },
    );

    // Cleanup
    return () => {
      socketInstance.disconnect();
    };
  }, [user.user_key]);

  // 코칭 요청 읽음 처리
  const markCoachingRequestAsRead = useCallback(async (requestId: string) => {
    try {
      const response = await fetch(
        `/api/asst/v1/coachings/requests/${requestId}/read`,
        {
          method: 'PATCH',
          headers: {
            Authorization: `Bearer ${getToken()}`,
          },
        },
      );

      if (response.ok) {
        // 로컬 상태 업데이트
        setCoachingRequests((prev) =>
          prev.map((req) =>
            req.id === requestId ? { ...req, is_read: true } : req,
          ),
        );

        // 카운트 감소
        setUnreadCount((prev) => ({
          ...prev,
          requests: Math.max(0, prev.requests - 1),
        }));
      }
    } catch (error) {
      console.error('코칭 요청 읽음 처리 실패:', error);
    }
  }, []);

  // 코칭 읽음 처리
  const markCoachingAsRead = useCallback(async (coachingId: string) => {
    try {
      const response = await fetch(
        `/api/asst/v1/coachings/${coachingId}/read`,
        {
          method: 'PATCH',
          headers: {
            Authorization: `Bearer ${getToken()}`,
          },
        },
      );

      if (response.ok) {
        // 로컬 상태 업데이트
        setCoachings((prev) =>
          prev.map((coaching) =>
            coaching.id === coachingId
              ? { ...coaching, is_read: true }
              : coaching,
          ),
        );

        // 카운트 감소
        setUnreadCount((prev) => ({
          ...prev,
          coachings: Math.max(0, prev.coachings - 1),
        }));
      }
    } catch (error) {
      console.error('코칭 읽음 처리 실패:', error);
    }
  }, []);

  return {
    socket,
    isConnected,
    coachingRequests,
    coachings,
    unreadCount,
    markCoachingRequestAsRead,
    markCoachingAsRead,
  };
}
```

### Vue.js 예제

```typescript
// composables/useCoachingNotifications.ts
import { ref, onMounted, onUnmounted } from 'vue';
import { io, Socket } from 'socket.io-client';

export function useCoachingNotifications(userKey: string) {
  const socket = ref<Socket | null>(null);
  const isConnected = ref(false);
  const coachingRequests = ref<CoachingRequestPayload[]>([]);
  const coachings = ref<CoachingPayload[]>([]);
  const unreadCount = ref({ requests: 0, coachings: 0 });

  const connect = () => {
    const socketInstance = io(import.meta.env.VITE_SOCKET_URL, {
      transports: ['websocket', 'polling'],
      reconnection: true,
    });

    socket.value = socketInstance;

    socketInstance.on('connect', () => {
      console.log('✅ Socket 연결');
      isConnected.value = true;

      // Coaching room 참여
      socketInstance.emit('join-room', `coaching_${userKey}`);
    });

    socketInstance.on('disconnect', () => {
      console.log('🔌 Socket 연결 해제');
      isConnected.value = false;
    });

    // 코칭 요청 알림
    socketInstance.on('coaching_request', (data: any) => {
      console.log('📨 새로운 코칭 요청:', data.payload);
      coachingRequests.value.unshift(data.payload);
      unreadCount.value.requests++;
    });

    // 코칭 알림
    socketInstance.on('coaching', (data: any) => {
      console.log('📨 새로운 코칭:', data.payload);
      coachings.value.unshift(data.payload);
      unreadCount.value.coachings++;
    });
  };

  onMounted(() => {
    connect();
  });

  onUnmounted(() => {
    socket.value?.disconnect();
  });

  return {
    socket,
    isConnected,
    coachingRequests,
    coachings,
    unreadCount,
  };
}
```

---

## 트러블슈팅

### 1. Socket.IO 연결이 안 됨

**증상**: `connect_error` 이벤트 발생

**해결책**:

- CORS 설정 확인
- WebSocket 프로토콜 확인 (ws:// vs wss://)
- 방화벽/프록시 설정 확인

```typescript
// 연결 오류 디버깅
socket.on('connect_error', (error) => {
  console.error('연결 오류:', error.message);
  console.error('Transport:', socket.io.engine.transport.name);
});
```

### 2. Room 참여했는데 알림이 안 옴

**확인사항**:

1. Room 이름이 올바른지 확인: `coaching_{user_key}`
2. Socket 연결 후 room 참여했는지 확인
3. `join-room-success` 이벤트 수신 확인

```typescript
// Room 참여 상태 확인
socket.on('join-room-success', (data) => {
  console.log('✅ Room 참여:', data.room, `(${data.clientCount}명)`);
});

socket.on('join-room-error', (data) => {
  console.error('❌ Room 참여 실패:', data.error, data.message);
});
```

### 3. 알림은 오는데 중복으로 옴

**원인**: 여러 번 room에 참여하거나 Socket 인스턴스가 중복 생성됨

**해결책**:

- Socket 인스턴스를 싱글톤으로 관리
- 컴포넌트 unmount 시 정리
- room 참여 전 이미 참여했는지 확인

```typescript
// 싱글톤 패턴
let socketInstance: Socket | null = null;

export function getSocket(): Socket {
  if (!socketInstance) {
    socketInstance = io(SOCKET_URL, {
      /* options */
    });
  }
  return socketInstance;
}
```

### 4. 페이지 새로고침 시 알림이 안 옴

**원인**: Socket 재연결 후 room 재참여 안 함

**해결책**:

- `connect` 이벤트에서 room 재참여

```typescript
socket.on('connect', () => {
  console.log('재연결 후 room 재참여');
  socket.emit('join-room', `coaching_${user.user_key}`);
});
```

### 5. is_read=false 필터가 작동 안 함

**해결됨**: boolean 쿼리 파라미터 변환 문제 해결됨

**사용법**:

```typescript
// 올바른 사용법
fetch(`/api/asst/v1/coachings/requests/receiver/${userKey}?is_read=false`);

// 잘못된 사용법 (작동 안 함)
fetch(`/api/asst/v1/coachings/requests/receiver/${userKey}?is_read=0`);
```

---

## 권장 구현 패턴

### 1. 알림 배지 표시

```typescript
function NotificationBadge() {
  const { unreadCount } = useCoachingNotifications(currentUser);

  const totalUnread = unreadCount.requests + unreadCount.coachings;

  return (
    <div className="notification-badge">
      {totalUnread > 0 && (
        <span className="badge">{totalUnread > 99 ? '99+' : totalUnread}</span>
      )}
    </div>
  );
}
```

### 2. 우선순위별 UI 표시

```typescript
function CoachingItem({ coaching }: { coaching: CoachingPayload }) {
  const priorityClass = coaching.priority_type === 1 ? 'urgent' : 'normal';
  const importantClass = coaching.is_important ? 'important' : '';

  return (
    <div className={`coaching-item ${priorityClass} ${importantClass}`}>
      {coaching.priority_type === 1 && <span>🚨 긴급</span>}
      {coaching.is_important && <span>⭐ 중요</span>}
      {!coaching.is_read && <span className="unread-dot">●</span>}
      <p>{coaching.content}</p>
    </div>
  );
}
```

### 3. 실시간 목록 업데이트

```typescript
function CoachingList() {
  const { coachingRequests, markCoachingRequestAsRead } = useCoachingNotifications(currentUser);

  const handleItemClick = async (request: CoachingRequestPayload) => {
    // 상세 보기
    showCoachingRequestDetail(request);

    // 읽음 처리
    if (!request.is_read) {
      await markCoachingRequestAsRead(request.id);
    }
  };

  return (
    <div>
      {coachingRequests.map((request) => (
        <div key={request.id} onClick={() => handleItemClick(request)}>
          {/* ... */}
        </div>
      ))}
    </div>
  );
}
```

### 4. 브라우저 알림 권한 요청

```typescript
async function requestNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    const permission = await Notification.requestPermission();
    console.log('알림 권한:', permission);
    return permission === 'granted';
  }
  return Notification.permission === 'granted';
}

// 앱 초기화 시 호출
useEffect(() => {
  requestNotificationPermission();
}, []);
```

---

## 쿼리 파라미터 옵션

모든 목록 조회 API는 다음 파라미터를 지원합니다:

| 파라미터       | 타입    | 필수 | 기본값 | 설명                            |
| -------------- | ------- | ---- | ------ | ------------------------------- |
| `page`         | number  | 선택 | 1      | 페이지 번호                     |
| `limit`        | number  | 선택 | 10     | 페이지당 항목 수                |
| `is_read`      | boolean | 선택 | -      | 읽음 여부 필터 (`true`/`false`) |
| `is_important` | boolean | 선택 | -      | 중요 표시 필터 (`true`/`false`) |

### 사용 예시

```typescript
// 안읽은 중요한 코칭만 조회
fetch(
  `/api/asst/v1/coachings/receiver/${userKey}?is_read=false&is_important=true&page=1&limit=20`,
);

// 읽은 코칭만 조회
fetch(`/api/asst/v1/coachings/sender/${userKey}?is_read=true`);

// 중요한 코칭 요청만 조회
fetch(`/api/asst/v1/coachings/requests/receiver/${userKey}?is_important=true`);
```

---

## Swagger 문서

API 상세 문서는 다음 URL에서 확인할 수 있습니다:

```
https://your-server.com/api/asst/v1/doc
```

Swagger UI에서 다음을 확인할 수 있습니다:

- 모든 API 엔드포인트
- 요청/응답 스키마
- 예제 데이터
- Try it out 기능으로 직접 테스트

---

## 주요 포인트 요약

1. ✅ **Socket.IO 연결**: 앱 시작 시 한 번만 연결
2. ✅ **Room 참여**: `coaching_{user_key}` room에 자동 참여
3. ✅ **이벤트 수신**: `coaching_request`, `coaching` 이벤트 리스닝
4. ✅ **읽음 처리**: PATCH API로 is_read를 true로 변경
5. ✅ **필터링**: `is_read=false`로 안읽은 항목만 조회
6. ✅ **재연결**: Socket 재연결 시 room 재참여 필요

---

## 문의사항

기술적 문의사항이나 이슈가 있으면 백엔드 팀에 문의해주세요.

- 📧 Email: backend-team@example.com
- 💬 Slack: #coaching-notification
- 📖 Swagger: https://your-server.com/api/asst/v1/doc
