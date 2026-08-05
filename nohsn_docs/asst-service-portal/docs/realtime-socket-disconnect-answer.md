# 실시간 끊김 이슈 — 백엔드 답변서 (프론트엔드 전달용)

> 대상: asst-service (NestJS + socket.io 4.8) 백엔드
> 증상: 어느 시점 이후 상태/STT/VOC 실시간이 전부 멈추고, 새로고침해야 복구됨

## 결론 (요약)

- **이 백엔드의 socket.io 핸드셰이크에는 인증이 전혀 없습니다.** 토큰/쿠키/쿼리 무엇도 검증하지 않습니다.
- 따라서 **"20분 토큰 갱신 → 서버가 소켓을 강제로 끊음"은 이 백엔드에서 발생하지 않습니다.**
- 실시간이 멈추는 유력 원인은:
  1. 앞단 **게이트웨이의 WS idle/read 타임아웃**으로 소켓이 끊김
  2. 재연결된 **새 소켓(new socket.id)이 room을 재조인하지 않아** 모든 브로드캐스트를 못 받음
- 새로고침하면 join 흐름 전체가 다시 돌아 복구됩니다.

---

## 1. 세션 갱신(20분) ↔ 소켓 연결

**Q. 20분 토큰 갱신 시점에 서버가 기존 WebSocket을 강제로 끊나요?**
→ **아니요.** 백엔드 socket.io 레이어는 토큰을 전혀 보지 않습니다. 토큰 갱신 때문에 서버가 소켓을 끊는 코드 경로가 없습니다.
※ 단, 배포 환경 앞단에 **API 게이트웨이(Spring Cloud Gateway)** 가 있습니다. 게이트웨이가 WS 업그레이드 시 토큰을 검증/차단한다면 그건 게이트웨이 정책이며 별도 확인 필요. (로컬 106 직결은 게이트웨이 없음 → 해당 없음.)

**Q. 소켓 핸드셰이크 인증은 무엇으로?**
→ **인증 없음.** 쿠키/Authorization/query token 어느 것도 사용하지 않습니다. 누구나 핸드셰이크 성공합니다.

**Q. 만료된 토큰/세션으로 재연결(handshake)하면 서버가 거부하나요?**
→ **백엔드는 거부하지 않습니다.** `connect_error`가 반복된다면 **게이트웨이가 WS 업그레이드를 거부**하는 경우입니다. 프론트에서 `connect_error`의 error payload/HTTP status를 캡처해 주세요 — 서버발/게이트웨이발이 바로 구분됩니다.

> ⚠️ **소켓은 안 끊겨도 데이터 파이프라인은 토큰에 의존합니다.** 채널 구독 등록(`POST /redis-monitor/subscribe`), assist-stream 토큰 캐시, 상담사 상태 API 등 REST 경로는 인증 미들웨어를 타므로 토큰 만료 시 401이 납니다. "소켓은 붙어 있는데 데이터만 안 옴"이 이 조합에서 나올 수 있습니다.

## 2. Redis 구독(REST `/redis-monitor/subscribe/{channel}`) ↔ 소켓 생명주기

**Q. 소켓 disconnect 시 이 구독이 자동 해제되나요?**
→ **아니요, 서버에 그대로 남습니다.** 구독은 **서버 전역 채널 목록 + Redis pub/sub 구독**으로 저장되며 소켓과 연결돼 있지 않습니다. `DELETE /redis-monitor/unsubscribe/{channel}` 호출 시에만 해제됩니다.

**Q. 재연결로 새 socket.id가 되면 REST 구독을 다시 해야 하나요, room join만 다시 하면 되나요?**
→ **room join만 다시 하면 됩니다.** 채널은 이미 서버에 구독돼 있어 재구독은 불필요(재호출해도 `isAlreadyMonitored: true`로 무해). **필수는 `join-room` 재조인**입니다.

**Q. 구독 등록 시 서버는 어느 소켓에 매핑하나요?**
→ **어떤 소켓에도 매핑하지 않습니다. 채널(=room 이름) 기준**입니다. 요청 바디에 socket.id가 없는 게 정상입니다. 흐름 분리:
- `subscribe` REST = "이 채널을 Redis에서 구독해 같은 이름의 room으로 중계해 둬라" (전역 1회)
- `join-room` 소켓 이벤트 = "내 소켓을 그 room에 넣어라" (소켓별, 재연결마다)
- 전달: Redis 메시지 → 같은 이름의 room으로 `redis-message` 이벤트 emit

## 3. 룸 재조인 & 메시지 유실

**Q. 끊겼다 재연결되는 사이 발행된 메시지는 유실되나요?**
→ **네, 유실됩니다.** 기본 in-memory 어댑터를 쓰고 백로그/재전송이 없습니다. 소켓이 끊긴 순간 모든 room에서 제거되고, 재연결 후 `join-room` 하기 전까지 그 room으로 간 메시지는 사라집니다. **이게 현 증상의 핵심입니다.**

**Q. Connection State Recovery를 쓰나요? 켤 수 있나요?**
→ **현재 안 씁니다.** 켤 수는 있으나 근본 해결책은 아닙니다(복구 윈도우 짧음, 멀티 파드 시 어댑터 필요, 재연결 자체가 되어야 의미 있음). **더 확실한 해결은 프론트가 `connect`/`reconnect`마다 room을 무조건 재조인**하는 것입니다.

## 4. 연결이 끊기는 원인

**Q. 서버 socket.io ping/pong, idle timeout 값은?**
- `pingInterval: 25000` (25초마다 서버→클라 ping)
- `pingTimeout: 60000` (pong 60초 미수신 시 끊음)
- `upgradeTimeout: 30000`

→ **정상 ping/pong만 오가면 서버가 idle로 끊지 않습니다.** 서버가 끊는 건 "pong 미응답 ~85초(25+60)"뿐이며 그때 reason은 `ping timeout`으로 찍힙니다.

**Q. 앞단 게이트웨이/프록시 타임아웃으로 주기적 단절 여지가 있나요?**
→ **네, 가장 유력한 단절 원인입니다.** 게이트웨이/프록시의 **read timeout · WS idle timeout · response timeout**이 ping 간격보다 짧으면 주기적으로 WS를 끊습니다. 게이트웨이 저장소에서 확인 요청:
- Spring Cloud Gateway `httpclient.response-timeout` / WebSocket idle timeout
- (nginx 경유 시) `proxy_read_timeout` / `proxy_send_timeout`

> 🔎 **백엔드 로그로 원인 구분 가능** (멈춘 시점 서버 로그 확인):
> - `🔌 DISCONNECT REASON: ... reason="ping timeout"` → 클라/네트워크가 pong 못 보냄
> - `🔌 TRANSPORT CLOSE: ... reason="transport close"` → 게이트웨이/프록시가 커넥션을 끊음 (게이트웨이 타임아웃 유력)

## 5. 정상 흐름 재확인

**Q. 대기 상태일 때 미리 채널을 구독(join)해두면, 통화 시작 시 call:events(start)가 그 room으로 정상 발행되나요?**
→ **네, 통화 전 사전 구독은 유효합니다.** room은 통화 상태와 무관한 단순 socket.io room이라, publish 시점에 그 room에 join돼 있으면 받습니다. (상태 변경도 고정 room `agent-status`로 동일 패턴 발행.)

**단, 정상 수신에는 발행 시점에 두 조건이 동시에 만족되어야 합니다:**
1. **그 소켓이 해당 room에 join된 상태일 것** ← 재연결 후 재조인 안 하면 깨짐 (3번과 직결)
2. **(멀티 파드 배포 시) 소켓이 붙은 파드 = 채널을 Redis 구독한 파드**일 것. 현재 `subscribe` REST를 받은 파드에만 구독이 등록되고 room도 파드 로컬입니다(socket.io-redis 어댑터 미사용). **그래서 ALB sticky session이 필수**입니다. 파드가 1개면 이 이슈 없음. 실제 배포 replica 수와 sticky 설정 확인 요청.

---

## 종합 진단 & 프론트 확인 요청

두 시나리오 중 하나입니다:

- **시나리오 A (가장 유력):** 게이트웨이 WS 타임아웃 등으로 소켓 끊김 → 새 socket.id로 재연결은 되지만 → 프론트가 **재연결 후 `join-room`(및 `agent-status` join)을 다시 안 함** → 새 소켓이 어떤 room에도 없어 상태/STT/VOC 전부 미수신. 새로고침 = join 흐름 재실행이라 복구.
- **시나리오 B:** 재연결 자체 실패(`connect_error` 반복). 백엔드는 소켓을 거부하지 않으므로, 게이트웨이가 WS 업그레이드를 막는 경우 → 게이트웨이 저장소 확인 필요.

**프론트에서 확인/조치 부탁:**
1. socket 클라이언트에 `connect`(첫 연결 포함)·`reconnect` 리스너를 달고, **매 연결마다 필요한 모든 room을 재조인**(`join-room` + `agent-status`). 재구독 REST는 불필요.
2. `connect_error` 발생 시 error 객체/HTTP status 로깅 → 서버발 vs 게이트웨이발 구분.
3. 멈춘 시점 브라우저 네트워크탭에서 WS 프레임이 끊긴 시각 확인 → 백엔드 `DISCONNECT REASON`/`TRANSPORT CLOSE` 로그 시각과 대조.

**백엔드 측 개선 여지 (필요 시 진행):**
- `connectionStateRecovery` 활성화 (임시 완충용)
- 재연결 소켓을 자동으로 이전 room에 재조인시키는 로직 (멀티 파드면 socket.io-redis 어댑터 병행 필요)
