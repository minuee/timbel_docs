# 상담사 상태 공유 기능 가이드 (Frontend)

## 📋 목차

1. [개요](#개요)
2. [시스템 아키텍처](#시스템-아키텍처)
3. [Socket.IO 연결 설정](#socketio-연결-설정)
4. [Agent Status Room 참여](#agent-status-room-참여)
5. [상태 변경 수신](#상태-변경-수신)
6. [API 엔드포인트](#api-엔드포인트)
7. [Vue 예제 코드](#vue-예제-코드)
8. [트러블슈팅](#트러블슈팅)

---

## 개요

상담사 상태 공유 기능은 **Socket.IO**를 사용하여 실시간으로 상담사의 상태 변경을 모든 클라이언트에게 전달합니다.

### 주요 특징

- ✅ 실시간 상태 업데이트
- ✅ Room 기반 브로드캐스트 (모든 클라이언트 수신)
- ✅ 자동 재연결 지원
- ✅ agent_id와 status 정보 포함

---

## 시스템 아키텍처

```
┌─────────────┐
│  Frontend   │
│  (Socket)   │
└──────┬──────┘
       │ WebSocket
       │ join: agent-status
       ↓
┌─────────────────────┐
│  Backend Server     │
│  (Socket.IO)        │
└──────┬──────────────┘
       │
       ├─→ AgentService
       │   (상태 수정)
       ↓
  Room: agent-status
       ↓
  Frontend (모든 클라이언트)
```

### 메시지 흐름

1. **상태 수정** → DB 저장 → Socket.IO Emit → Frontend 수신

---

## Socket.IO 연결 설정

### 1. Socket.IO 클라이언트 설치

```bash
npm install socket.io-client
# or
yarn add socket.io-client
```

### 2. Socket.IO 연결 설정

```javascript
import { io } from 'socket.io-client';

const socket = io('https://your-server.com', {
  transports: ['websocket', 'polling'],
  reconnection: true,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
  reconnectionAttempts: Infinity,
});
```

---

## Agent Status Room 참여

연결 후 `agent-status` room에 참여해야 상태 변경 메시지를 수신할 수 있습니다.

```javascript
socket.on('connect', () => {
  console.log('Socket.IO 연결됨');

  // agent-status room 참여
  socket.emit('join-room', 'agent-status');

  socket.on('join-room-success', (data) => {
    console.log('Room 참여 성공:', data);
  });

  socket.on('join-room-error', (error) => {
    console.error('Room 참여 실패:', error);
  });
});
```

---

## 상태 변경 수신

`agent-status-update` 이벤트를 수신하여 상태 변경을 처리합니다.

```javascript
socket.on('agent-status-update', (data) => {
  console.log('상담사 상태 변경 수신:', data);
  // data 구조:
  // {
  //   agent_id: 'agent_123',
  //   status: 'ACTIVE',
  //   timestamp: '2024-01-01T00:00:00.000Z'
  // }

  // 상태 업데이트 처리
  updateAgentStatus(data.agent_id, data.status);
});
```

---

## API 엔드포인트

### 1. 상담사 상태 수정

```http
PUT /agents/status
Content-Type: application/json
x-auth-token: Bearer {token}

{
  "agent_id": "agent_123",
  "status": "ACTIVE"
}
```

### 2. 상태별 상담사 조회

```http
GET /agents/status/{status}
x-auth-token: Bearer {token}
```

예시:

```http
GET /agents/status/ACTIVE
x-auth-token: Bearer {token}
```

---

## Vue 예제 코드

### Composition API 사용 예제

```vue
<template>
  <div>
    <h2>상담사 상태 모니터링</h2>
    <div v-if="!connected">연결 중...</div>
    <div v-else>
      <p>연결됨: {{ connected ? '예' : '아니오' }}</p>
      <p>Room 참여: {{ roomJoined ? '예' : '아니오' }}</p>
    </div>

    <div v-if="lastUpdate">
      <h3>최근 상태 변경</h3>
      <p>상담사 ID: {{ lastUpdate.agent_id }}</p>
      <p>상태: {{ lastUpdate.status }}</p>
      <p>시간: {{ formatTimestamp(lastUpdate.timestamp) }}</p>
    </div>

    <div>
      <h3>상담사 목록</h3>
      <div v-for="agent in agents" :key="agent.id">
        <p>{{ agent.name }} ({{ agent.id }}) - {{ agent.status }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import { io } from 'socket.io-client';

const socket = ref(null);
const connected = ref(false);
const roomJoined = ref(false);
const lastUpdate = ref(null);
const agents = ref([]);

// Socket.IO 서버 URL (환경변수로 관리 권장)
const SOCKET_URL = import.meta.env.VITE_SOCKET_URL || 'http://localhost:3000';

onMounted(() => {
  // Socket.IO 연결
  socket.value = io(SOCKET_URL, {
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    reconnectionAttempts: Infinity,
  });

  // 연결 성공 이벤트
  socket.value.on('connect', () => {
    console.log('Socket.IO 연결됨:', socket.value.id);
    connected.value = true;

    // agent-status room 참여
    socket.value.emit('join-room', 'agent-status');
  });

  // 연결 해제 이벤트
  socket.value.on('disconnect', () => {
    console.log('Socket.IO 연결 해제');
    connected.value = false;
    roomJoined.value = false;
  });

  // 재연결 시도 이벤트
  socket.value.on('reconnect', (attemptNumber) => {
    console.log('Socket.IO 재연결:', attemptNumber);
    connected.value = true;
    // 재연결 시 room 다시 참여
    socket.value.emit('join-room', 'agent-status');
  });

  // Room 참여 성공
  socket.value.on('join-room-success', (data) => {
    console.log('Room 참여 성공:', data);
    roomJoined.value = true;
  });

  // Room 참여 실패
  socket.value.on('join-room-error', (error) => {
    console.error('Room 참여 실패:', error);
    roomJoined.value = false;
  });

  // 상담사 상태 변경 수신
  socket.value.on('agent-status-update', (data) => {
    console.log('상담사 상태 변경 수신:', data);
    lastUpdate.value = data;

    // 로컬 상태 업데이트
    updateLocalAgentStatus(data.agent_id, data.status);
  });

  // 연결 확인 메시지
  socket.value.on('connection-confirmed', (data) => {
    console.log('서버 연결 확인:', data);
  });
});

onUnmounted(() => {
  if (socket.value) {
    socket.value.disconnect();
  }
});

// 로컬 상담사 상태 업데이트
const updateLocalAgentStatus = (agentId, status) => {
  const agent = agents.value.find((a) => a.id === agentId);
  if (agent) {
    agent.status = status;
  }
};

// 타임스탬프 포맷팅
const formatTimestamp = (timestamp) => {
  return new Date(timestamp).toLocaleString('ko-KR');
};

// 초기 상담사 목록 로드 (API 호출)
const loadAgents = async () => {
  try {
    const response = await fetch('/api/agents', {
      headers: {
        'x-auth-token': 'Bearer YOUR_TOKEN',
      },
    });
    const data = await response.json();
    agents.value = data;
  } catch (error) {
    console.error('상담사 목록 로드 실패:', error);
  }
};

// 컴포넌트 마운트 시 상담사 목록 로드
onMounted(() => {
  loadAgents();
});
</script>
```

### Options API 사용 예제

```vue
<template>
  <div>
    <h2>상담사 상태 모니터링</h2>
    <div v-if="!connected">연결 중...</div>
    <div v-else>
      <p>연결됨: {{ connected ? '예' : '아니오' }}</p>
      <p>Room 참여: {{ roomJoined ? '예' : '아니오' }}</p>
    </div>

    <div v-if="lastUpdate">
      <h3>최근 상태 변경</h3>
      <p>상담사 ID: {{ lastUpdate.agent_id }}</p>
      <p>상태: {{ lastUpdate.status }}</p>
      <p>시간: {{ formatTimestamp(lastUpdate.timestamp) }}</p>
    </div>
  </div>
</template>

<script>
import { io } from 'socket.io-client';

export default {
  name: 'AgentStatusMonitor',
  data() {
    return {
      socket: null,
      connected: false,
      roomJoined: false,
      lastUpdate: null,
      SOCKET_URL: process.env.VUE_APP_SOCKET_URL || 'http://localhost:3000',
    };
  },
  mounted() {
    this.initSocket();
  },
  beforeUnmount() {
    if (this.socket) {
      this.socket.disconnect();
    }
  },
  methods: {
    initSocket() {
      // Socket.IO 연결
      this.socket = io(this.SOCKET_URL, {
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        reconnectionAttempts: Infinity,
      });

      // 연결 성공 이벤트
      this.socket.on('connect', () => {
        console.log('Socket.IO 연결됨:', this.socket.id);
        this.connected = true;

        // agent-status room 참여
        this.socket.emit('join-room', 'agent-status');
      });

      // 연결 해제 이벤트
      this.socket.on('disconnect', () => {
        console.log('Socket.IO 연결 해제');
        this.connected = false;
        this.roomJoined = false;
      });

      // 재연결 시도 이벤트
      this.socket.on('reconnect', (attemptNumber) => {
        console.log('Socket.IO 재연결:', attemptNumber);
        this.connected = true;
        // 재연결 시 room 다시 참여
        this.socket.emit('join-room', 'agent-status');
      });

      // Room 참여 성공
      this.socket.on('join-room-success', (data) => {
        console.log('Room 참여 성공:', data);
        this.roomJoined = true;
      });

      // Room 참여 실패
      this.socket.on('join-room-error', (error) => {
        console.error('Room 참여 실패:', error);
        this.roomJoined = false;
      });

      // 상담사 상태 변경 수신
      this.socket.on('agent-status-update', (data) => {
        console.log('상담사 상태 변경 수신:', data);
        this.lastUpdate = data;
      });

      // 연결 확인 메시지
      this.socket.on('connection-confirmed', (data) => {
        console.log('서버 연결 확인:', data);
      });
    },
    formatTimestamp(timestamp) {
      return new Date(timestamp).toLocaleString('ko-KR');
    },
  },
};
</script>
```

### Composable 함수로 분리한 예제

`composables/useAgentStatus.ts`:

```typescript
import { ref, onMounted, onUnmounted } from 'vue';
import { io, Socket } from 'socket.io-client';

interface AgentStatusUpdate {
  agent_id: string;
  status: string;
  timestamp: string;
}

export function useAgentStatus(socketUrl?: string) {
  const socket = ref<Socket | null>(null);
  const connected = ref(false);
  const roomJoined = ref(false);
  const lastUpdate = ref<AgentStatusUpdate | null>(null);

  const SOCKET_URL =
    socketUrl || import.meta.env.VITE_SOCKET_URL || 'http://localhost:3000';

  const initSocket = () => {
    socket.value = io(SOCKET_URL, {
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: Infinity,
    });

    socket.value.on('connect', () => {
      console.log('Socket.IO 연결됨:', socket.value?.id);
      connected.value = true;
      socket.value?.emit('join-room', 'agent-status');
    });

    socket.value.on('disconnect', () => {
      console.log('Socket.IO 연결 해제');
      connected.value = false;
      roomJoined.value = false;
    });

    socket.value.on('reconnect', () => {
      console.log('Socket.IO 재연결');
      connected.value = true;
      socket.value?.emit('join-room', 'agent-status');
    });

    socket.value.on('join-room-success', () => {
      console.log('Room 참여 성공');
      roomJoined.value = true;
    });

    socket.value.on('join-room-error', (error) => {
      console.error('Room 참여 실패:', error);
      roomJoined.value = false;
    });

    socket.value.on('agent-status-update', (data: AgentStatusUpdate) => {
      console.log('상담사 상태 변경 수신:', data);
      lastUpdate.value = data;
    });
  };

  const disconnect = () => {
    if (socket.value) {
      socket.value.disconnect();
      socket.value = null;
      connected.value = false;
      roomJoined.value = false;
    }
  };

  onMounted(() => {
    initSocket();
  });

  onUnmounted(() => {
    disconnect();
  });

  return {
    socket,
    connected,
    roomJoined,
    lastUpdate,
    disconnect,
  };
}
```

사용 예제:

```vue
<template>
  <div>
    <h2>상담사 상태 모니터링</h2>
    <div v-if="!connected">연결 중...</div>
    <div v-else>
      <p>연결됨: {{ connected ? '예' : '아니오' }}</p>
      <p>Room 참여: {{ roomJoined ? '예' : '아니오' }}</p>
    </div>

    <div v-if="lastUpdate">
      <h3>최근 상태 변경</h3>
      <p>상담사 ID: {{ lastUpdate.agent_id }}</p>
      <p>상태: {{ lastUpdate.status }}</p>
      <p>시간: {{ new Date(lastUpdate.timestamp).toLocaleString('ko-KR') }}</p>
    </div>
  </div>
</template>

<script setup>
import { useAgentStatus } from '@/composables/useAgentStatus';

const { connected, roomJoined, lastUpdate } = useAgentStatus();
</script>
```

---

## 트러블슈팅

### 1. Room에 참여했지만 메시지를 받지 못하는 경우

- Room 참여가 성공했는지 확인 (`join-room-success` 이벤트 확인)
- 서버 로그에서 room에 클라이언트가 연결되어 있는지 확인
- 네트워크 연결 상태 확인

### 2. 재연결 후 메시지를 받지 못하는 경우

- 재연결 시 `join-room` 이벤트를 다시 보내는지 확인
- `reconnect` 이벤트 핸들러에서 room 재참여 처리

### 3. 연결이 자주 끊기는 경우

- 네트워크 상태 확인
- 서버의 `pingTimeout`, `pingInterval` 설정 확인
- 방화벽 또는 프록시 설정 확인

---

## 참고사항

- Socket.IO 연결은 HTTPS/WSS를 사용하는 것이 권장됩니다.
- 프로덕션 환경에서는 환경변수로 Socket.IO 서버 URL을 관리하세요.
- Room 참여는 연결 성공 후 즉시 수행하는 것이 좋습니다.
- 재연결 시 Room을 다시 참여해야 메시지를 계속 수신할 수 있습니다.
