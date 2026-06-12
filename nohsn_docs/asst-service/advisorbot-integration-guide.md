# Advisorbot 연동 가이드

## 1. 연결 설정

### Socket.io 클라이언트 설치

```bash
npm install socket.io-client
```

### 연결 생성

```typescript
import { io } from "socket.io-client";

const socket = io("/advisorbot", {
  path: "/api/ce/v1/socket.io",
  transports: ["websocket"],
  // 인증 방법 1: extraHeaders (권장)
  extraHeaders: {
    Authorization: "Bearer YOUR_JWT_TOKEN",
  },
  // 또는 인증 방법 2: auth
  // auth: {
  //   token: 'YOUR_JWT_TOKEN'
  // }
});
```

## 2. 인증

**필수**: JWT 토큰 또는 `tenant_xxx` 형식의 tenantId

- `Authorization: Bearer <JWT_TOKEN>` (extraHeaders)
- 또는 `auth: { token: <TOKEN> }`

## 3. 이벤트

### 클라이언트 → 서버

#### 3.1. 세션 초기화 (`session:initialize`)

```typescript
socket.emit("session:initialize", {
  botId: string, // Bot ID (옵셔널)
  graphId: string, // Graph ID (옵셔널)
  metadata: object, // 추가 메타데이터 (옵셔널)
});
```

**참고**: `botId` 또는 `graphId` 중 **최소 하나는 필수**

- `graphId`가 있으면 우선 사용
- 없으면 `botId`로부터 메인 그래프 조회

#### 3.2. 발화 전송 (`message:utterance`)

```typescript
socket.emit("message:utterance", {
  role: "agent" | "customer", // 필수: 발화자 역할
  text: string, // 필수: 발화 내용
  timestamp: string, // 필수: ISO 8601 형식
});
```

**동작**:

- `role: 'agent'`: 대화 맥락에만 추가 (그래프 실행 안 함)
- `role: 'customer'`: 대화 맥락 추가 + 그래프 실행

#### 3.3. 세션 종료 (`session:disconnect`)

```typescript
socket.emit("session:disconnect");
```

### 서버 → 클라이언트

#### 3.4. 연결 완료 (`connection:connected`)

```typescript
socket.on("connection:connected", (data) => {
  console.log(data.sessionId); // Socket.io 세션 ID
});
```

#### 3.5. 세션 초기화 완료 (`session:initialized`)

```typescript
socket.on("session:initialized", (data) => {
  console.log("Session initialized:", data.sessionId);
});
```

#### 3.6. 그래프 실행 결과 (`result:execution`)

```typescript
socket.on("result:execution", (result) => {
  console.log("Execution result:", result);
});
```

**응답 구조**:

```typescript
{
  sessionId: string;
  graphId: string;              // 메인 그래프 ID
  graphName?: string;
  executedNodes: Array<{        // 실행된 노드 목록 (순서대로)
    executionOrder: number;     // 실행 순서 (1부터 시작)
    nodeId: string;
    nodeType: string;           // 'LLM', 'EXTERNAL_API', 'CALL_ACTION', 'STATIC' 등
    nodeName?: string;
    graphId: string;            // 노드가 속한 그래프 ID
    graphName?: string;
    metadata?: {                // 노드별 상세 메타데이터
      nodeType: string;
      processingTime?: number;
      llm?: { ... };            // LLM 노드인 경우
      externalApi?: { ... };    // API 노드인 경우
      // ...
    };
    timestamp: string;
  }>;
  executedGraphs: Array<{       // 실행된 그래프 목록 (메인 + 서브그래프)
    graphId: string;
    graphName?: string;
    nodeCount: number;          // 해당 그래프에서 실행된 노드 개수
  }>;
  totalNodes: number;           // 총 실행된 노드 개수
  executionTime: number;        // 실행 시간 (ms)
  timestamp: string;
}
```

#### 3.7. 에러 (`error:general`)

```typescript
socket.on("error:general", (error) => {
  console.error("Error:", error.message);
});
```

#### 3.8. 연결 종료 (`connection:disconnected`)

```typescript
socket.on("connection:disconnected", (data) => {
  console.log("Disconnected:", data.sessionId);
});
```

## 4. 완전한 예제

```typescript
import { io } from "socket.io-client";

// 1. 연결 생성
const socket = io("/advisorbot", {
  path: "/api/ce/v1/socket.io",
  transports: ["websocket"],
  extraHeaders: {
    Authorization: "Bearer YOUR_JWT_TOKEN",
  },
});

// 2. 이벤트 리스너 등록
socket.on("connection:connected", (data) => {
  console.log("✅ Connected:", data.sessionId);

  // 3. 세션 초기화
  socket.emit("session:initialize", {
    botId: "019aba3a-dd4c-7038-af3a-54e5a7bd16b9",
    // graphId: 'graph-456',  // 옵셔널
    metadata: {
      botName: "Customer Support Bot",
    },
  });
});

socket.on("session:initialized", (data) => {
  console.log("✅ Session initialized:", data.sessionId);

  // 4. 상담사 발화 전송
  socket.emit("message:utterance", {
    role: "agent",
    text: "안녕하세요, 무엇을 도와드릴까요?",
    timestamp: new Date().toISOString(),
  });

  // 5. 고객 발화 전송 (그래프 실행됨)
  socket.emit("message:utterance", {
    role: "customer",
    text: "주문 취소하고 싶어요",
    timestamp: new Date().toISOString(),
  });
});

// 6. 그래프 실행 결과 수신
socket.on("result:execution", (result) => {
  console.log("📊 Execution result:", {
    graphName: result.graphName,
    totalNodes: result.totalNodes,
    executionTime: result.executionTime,
    nodes: result.executedNodes.map((node) => ({
      order: node.executionOrder,
      type: node.nodeType,
      name: node.nodeName,
    })),
  });
});

// 7. 에러 처리
socket.on("error:general", (error) => {
  console.error("❌ Error:", error.message);
});

// 8. 연결 종료 처리
socket.on("disconnect", () => {
  console.log("🔌 Disconnected");
});

// 9. 세션 종료 (필요시)
function disconnectSession() {
  socket.emit("session:disconnect");
}
```

## 5. 주의사항

### 5.1. 발화 구분

- **상담사 발화** (`role: 'agent'`): 대화 맥락에만 추가, 그래프 실행 안 함
- **고객 발화** (`role: 'customer'`): 대화 맥락 추가 + 그래프 실행

### 5.2. 인증

- JWT 토큰 또는 tenantId는 **필수**
- 토큰이 없으면 세션 초기화 실패

### 5.3. botId vs graphId

- 둘 중 **최소 하나는 필수**
- `graphId` 우선, 없으면 `botId`로부터 메인 그래프 조회
- 둘 다 제공하면 `graphId` 사용

### 5.4. 타임스탬프

- ISO 8601 형식 사용: `new Date().toISOString()`

## 6. TypeScript 타입 정의

```typescript
// 세션 초기화 요청
interface SessionInitializeRequest {
  botId?: string;
  graphId?: string;
  metadata?: Record<string, any>;
}

// 발화 메시지
interface ConversationMessage {
  role: "agent" | "customer";
  text: string;
  timestamp: string; // ISO 8601
}

// 그래프 실행 결과
interface AdvisorbotProcessResult {
  sessionId: string;
  graphId: string;
  graphName?: string;
  executedNodes: NodeExecutionInfo[];
  executedGraphs: GraphExecutionInfo[];
  totalNodes: number;
  executionTime: number;
  timestamp: string;
}

interface NodeExecutionInfo {
  executionOrder: number;
  nodeId: string;
  nodeType: string;
  nodeName?: string;
  graphId: string;
  graphName?: string;
  metadata?: NodeProcessingMetadata;
  timestamp: string;
}

interface GraphExecutionInfo {
  graphId: string;
  graphName?: string;
  nodeCount: number;
}
```
