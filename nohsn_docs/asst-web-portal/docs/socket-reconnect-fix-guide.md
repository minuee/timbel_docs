# 상담사 모니터링 실시간 끊김 — 소켓 재연결 수정 이관 가이드

> 대상: 다른 레포지토리의 `asst-web` (프론트, Vue 3 + socket.io-client 4.x)
> 목적: "관리자 모니터링에서 상태/STT/VOC 실시간이 어느 순간 전부 멈추고, 새로고침해야 복구되는" 증상 해결
> 상태: 기준 레포에서 **적용 완료**.

---

## 1. 증상

- 관리자 로그인 → 모니터링 진입 → 대기 상태 상담사를 왼쪽에서 선택 → 대기.
- 이후 그 상담사가 통화를 시작하면 **상태 변경·STT 대화·VOC 감정이 실시간으로 떠야 하는데 전부 무반응.**
- **페이지 새로고침을 해야만** 그 시점까지의 내용이 노출되고 이후 실시간도 복구됨.
- 소켓/redis 자체는 백엔드상 정상. 특정 시점(예: 세션 20분 경과 부근) 이후 발생.

## 2. 근본 원인

### (A) 소켓 재연결 3회 소진 → 영구 포기 (핵심)
- socket.io 클라이언트 기본 `reconnectionAttempts`가 **3회**로 설정돼 있으면, 앞단 프록시/L4의 WS idle timeout이나 네트워크 순단으로 소켓이 끊긴 뒤 **재연결이 3회 연속 실패하면 재연결을 영구 포기**(`reconnect_failed`)한다.
- 포기하면 이후 `connect` 이벤트가 **다시는 발생하지 않으므로**, 코드에 잘 박아둔 룸 재조인 핸들러(`socket.on("connect", rejoin)`)가 **영영 안 불린다.**
- 결과: 소켓이 식물 상태 → 상태/STT/VOC 전부 미수신 → **새로고침(소켓 새로 생성)만이 회생.**

### (B) socket.io 룸 멤버십의 본질
- 룸 멤버십은 서버 메모리에 `socket.id` 기준으로만 저장됨. **소켓이 끊기면 그 즉시 모든 룸에서 자동 제거**되고, 재연결하면 **새 `socket.id`**라 이전 룸엔 아무도 없다. **재조인은 100% 클라이언트 책임.**
- redis pub/sub은 **백로그가 없어** 끊긴 동안 발행된 메시지는 영구 유실된다. (그래서 재연결돼도 과거 건 안 오고, 새로고침 시 REST 스냅샷으로만 복구됨)

> 백엔드 확인 요지: 소켓 핸드셰이크에 인증 없음(토큰 만료로 서버가 소켓을 끊지 않음) / REST 구독은 소켓 생명주기와 무관하게 서버에 남음 / 재연결 시 **`join-room`만** 다시 하면 됨 / 끊긴 사이 메시지는 유실 / 멀티 파드면 **ALB sticky session 필수**.

---

## 3. 조치 (필수·공통) — 무한 재연결 + 진단 로깅

**파일: `src/api/socketIOPlugin.ts`** (전역 단일 소켓 모듈)

이 한 파일만 고치면 이 모듈을 쓰는 **모든 진입(현행 + 리뉴얼)에 자동 적용**된다. 단, 각 진입의 `initSocket({...})` 호출부가 `reconnectionAttempts`를 **명시적으로 넘기지 않아야** 새 기본값이 먹는다. (넘기고 있으면 그 호출부도 지우거나 Infinity로 바꿀 것.)

**옵션 타입에 추가:**
```ts
export type SocketInitOptions = {
  baseUrl: string;
  path?: string;
  withCredentials?: boolean;
  reconnection?: boolean;
  reconnectionAttempts?: number;
  reconnectionDelay?: number;
  reconnectionDelayMaxMs?: number; // ← 추가: 재시도 간격 상한(백오프), 기본 5000
  timeoutMs?: number;
};
```

**`io(...)` 옵션 변경:**
```ts
socket = io(opts.baseUrl, {
  autoConnect: false,
  transports: ["websocket", "polling"],
  withCredentials: false,
  ...(opts.path ? { path: opts.path } : {}),
  reconnection: opts.reconnection ?? true,
  // ⚠️ 기존 기본 3회는 위험. 3회 연속 실패 시 재연결 영구 포기 → connect 안 뜸 →
  //    룸 재조인 핸들러가 죽어 실시간 통째로 멈춤(새로고침만 회생). → 붙을 때까지 무한 재시도.
  reconnectionAttempts: opts.reconnectionAttempts ?? Infinity,   // ← 3 → Infinity
  reconnectionDelay: opts.reconnectionDelay ?? 1000,
  reconnectionDelayMax: opts.reconnectionDelayMaxMs ?? 5000,      // ← 추가: 폭주 방지 백오프
  timeout: opts.timeoutMs ?? 20000
});
```

**진단 로깅 강화** (재현이 어려워 상시 로깅으로 다음 발생을 자동 포착):
```ts
const now = () => new Date().toISOString();

socket.on("connect", () => {
  console.log(`[socket-IO-Plugin] connected: id=${socket?.id} at=${now()}`);
});

// v4: (reason, details)
socket.on("disconnect", (reason, details) => {
  console.warn(`[socket-IO-Plugin] disconnected: reason=${reason} at=${now()}`, details ?? "");
});

socket.on("connect_error", (err: any) => {
  console.error(
    `[socket-IO-Plugin] connect_error: msg=${err?.message} desc=${err?.description ?? ""} at=${now()}`,
    err?.context ?? ""
  );
});

// Manager 레벨 재연결 수명주기 — 3회 소진 재발 여부 즉시 확인
const mgr = socket.io;
mgr.on("reconnect_attempt", (n: number) => console.log(`[socket-IO-Plugin] reconnect_attempt #${n} at=${now()}`));
mgr.on("reconnect", (n: number) => console.log(`[socket-IO-Plugin] reconnect OK after ${n} tries at=${now()}`));
mgr.on("reconnect_error", (err: any) => console.warn(`[socket-IO-Plugin] reconnect_error: ${err?.message} at=${now()}`));
mgr.on("reconnect_failed", () => console.error(`[socket-IO-Plugin] reconnect_failed — 재연결 영구 포기 at=${now()}`));
```

> **`disconnect`의 `reason` 판독표** (원인 실측용):
> - `transport close` → 앞단 프록시/L4/네트워크가 커넥션을 끊음 (프록시 WS idle timeout 유력)
> - `ping timeout` → 클라/네트워크가 pong 미응답 (서버 `pingTimeout` 초과)
> - `io server disconnect` → 서버가 명시적으로 종료

---

## 4. 인프라/백엔드 확인 (프론트 수정과 병행)
- 앞단 프록시/L4의 **WS idle / read timeout**이 서버 `pingInterval`(예: 25s)보다 짧으면 주기적으로 끊는다. → 늘리거나 제거.
- **멀티 파드 배포 시 ALB sticky session 필수** (subscribe한 파드 ≠ 소켓 붙은 파드 문제). replica 수와 sticky 설정 확인. socket.io-redis 어댑터 미사용 전제.

## 5. 적용 범위 / 이관 체크리스트

- 이 수정은 **`socketIOPlugin.ts` 한 파일**이며, 이 전역 소켓 모듈을 공유하는 **현행(consultant→admin)·리뉴얼(advisor-renual) 진입에 자동 공통 적용**된다.
- 다른 레포 이관 시 확인:
  1. `socketIOPlugin.ts`(또는 동등 소켓 모듈)의 `reconnectionAttempts` 기본값이 3인지 → Infinity로.
  2. 각 `initSocket({...})` 호출부가 `reconnectionAttempts`를 명시로 덮어쓰지 않는지.
  3. `AppInitializer` 등에서 쓰는 다른 소켓(`SocketClient.js` 등)이 있는지 — 모니터링 실시간이 어느 소켓을 쓰는지 먼저 특정할 것.

## 6. 검증 방법

배포 후 브라우저 콘솔(Preserve log 켜기)에서:
1. 평상시 `[socket-IO-Plugin] connected: id=...` 1회.
2. 끊길 때 `disconnected: reason=...` → 곧이어 `reconnect_attempt #1, #2 ...` → `reconnect OK after N tries` 가 **계속** 이어지는지 (기존엔 3회 후 멈췄음).
3. 재연결 직후 룸 재조인 로그(`[ADMIN] ... 룸 참가`, `[chat-sub] ...`)가 다시 찍히고 실시간이 복구되는지.
4. `reconnect_failed` 는 무한 재시도 설정에선 **정상적으로 안 떠야** 한다. 뜨면 앞단이 업그레이드를 막는 것(`connect_error`의 `desc`=status 확인).

## 7. 참고

- 수정 파일: `src/api/socketIOPlugin.ts`
- 원인 분석 원문: 백엔드 답변서 `docs2/realtime-socket-disconnect-answer.md`
