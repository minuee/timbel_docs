# 이중화(HA) / 오토스케일 아키텍처 분석

> asst-service 를 여러 인스턴스로 띄웠을 때 문제가 되는 지점과, 현재 배포 구조에서의 결론 정리.
> (2026-07-16 분석)

## 0. 한 줄 결론

**현재 배포는 KEDA `maxReplicaCount: 1` = 실질 단일 액티브라 코드 수정 없이 안전하다.**
2대 이상 동시 가동(액티브-액티브)하게 되면 그때 아래 **5가지 조건**을 반드시 검토해야 한다.

---

## 1. "이중화"는 두 가지다 — 먼저 목적을 구분하라

대화가 꼬이는 근본 원인은 "이중화"라는 단어가 **목적이 다른 두 개**를 동시에 가리키기 때문이다.

| 구분 | 목적 | 전제 | 이 프로젝트에서 |
|------|------|------|----------------|
| **HA (가용성)** | "한 대 죽어도 서비스 유지" | **실질 1대**만 가동해도 성립 (죽으면 재기동/스탠바이) | ✅ **필요, 현 구조가 맞음** |
| **스케일아웃 (부하분산)** | "여러 대가 부하 나눠받기 (처리량↑)" | **2대 이상 동시 가동** | ❌ **불필요** (콜센터 몇십~몇백 명 규모엔 1대로 충분) |

판단 순서: **목적 → 아키텍처 → 코드 영향**.
- 목적이 가용성이면 → 실질 1대로 충분, 코드 그대로 OK.
- 목적이 부하분산이면 → 2대 이상 필요 → 5가지 조건 검토 필수.

> **핵심 반문:** "이 규모에 부하분산(스케일아웃)이 정말 필요한가?" — 목적을 먼저 정의하게 만드는 질문.

---

## 2. 현재 배포 구조 (dev, 2026-07 기준)

- **플랫폼:** AWS EKS + ArgoCD(GitOps) + **Istio 서비스 메시** + **KEDA 오토스케일러**
- **네임스페이스:** `aicc`
- **이미지:** `harbor.timbel.dev/aicc/asst-service_dev:v182`, `NODE_ENV=development`
- **KEDA ScaledObject 설정:**
  ```yaml
  spec:
    minReplicaCount: 0      # 유휴 시 0대까지 내려감 (scale-to-zero)
    idleReplicaCount: 0
    maxReplicaCount: 1      # ★ 최대 1대 — 절대 2대 이상 안 됨
    cooldownPeriod: 300
    pollingInterval: 30
  ```

### 왜 이게 안전한가
- **`maxReplicaCount: 1`** → 파드가 아무리 부하를 받아도 **최대 1대**. Istio가 라운드로빈할 대상이 2개가 될 수 없으니 **액티브-액티브가 원천 불가능** → 아래 5가지 문제 전부 무효.

### 알아둘 성격 (문제는 아님)
1. **scale-to-zero (`min 0 / idle 0`)**: 유휴 시 0대로 내려감 → 그 순간 WebSocket 전부 끊김, 다시 1대 뜰 때 클라 재접속(룸 재조인은 클라 몫이라 설계상 OK) + 콜드스타트 지연.
   - **확인 권장:** KEDA `triggers:` 가 근무 중 0으로 안 내려가는 지표인지. (상담원 상시 접속을 못 보는 트리거면 근무 중에도 소켓이 끊길 수 있음)
2. **핫 스탠바이가 아니다:** `max 1`이라 예비 1대가 상시 대기하는 게 아니라 **죽으면 새로 1대 재기동**하는 방식. 장애 시 콜드스타트만큼 짧은 다운타임 존재(이 규모엔 충분). "무중단 핫스탠바이"를 요구하면 2대 상시가동이 필요하고, 그 순간 액티브-액티브가 되어 5가지 작업이 강제됨 → **트레이드오프**.

---

## 3. ArgoCD 간단 조회법 (AA/AS 판정)

ArgoCD는 GitOps라 "실제 클러스터에 뜬 상태"를 그대로 보여줌 → 배포 담당자에게 안 물어도 셀프 확인 가능.

**앱 리소스 트리에서 볼 것:**

1. **`pod` 박스 (맨 오른쪽)** — `1/1 running` 배지에서 **현재 떠있는 파드 수** 확인.
   - Pod 박스 1개 = 현재 1대 (단일 액티브).
2. **`deploy` (Deployment) 박스** 클릭 → YAML `spec.replicas` 숫자.
3. **`scaledobject` / `hpa` (KEDA) 박스** 클릭 → **`maxReplicaCount`** (또는 HPA `MaxPods`). ← **가장 중요**. 오토스케일 상한이므로 이게 최종 답.

**판정표:**

| `maxReplicaCount` | 결론 |
|---|---|
| **1** | 절대 2대 안 됨 → **완전 안전, 코드 수정 0** |
| **2 이상** | 부하 시 Istio가 라운드로빈 = **액티브-액티브** → 5가지 조건 검토 필수 (평소 1대라 멀쩡하다가 스케일업 순간 간헐 장애 = 잡기 어려운 잠재 폭탄) |

> 주의: 바닐라 k8s Deployment+Service, 그리고 Istio 메시 모두 **"스탠바이" 개념이 기본으로 없다.** replicas/max가 2 이상이면 무조건 트래픽을 나눠 보내므로 자동으로 액티브-액티브가 된다.

---

## 4. 2대 이상 동시 가동 시 검토할 5가지 (액티브-액티브 전제)

> `maxReplicaCount ≥ 2` 로 바꾸거나 무중단 핫스탠바이(2대 상시)로 갈 때만 해당.

| # | 문제 | 심각도 | 해결 |
|---|------|:---:|------|
| **1** | **Socket.IO에 Redis 어댑터 없음** (기본 인메모리 어댑터). HTTP로 트리거되는 직접 emit — `notice.service`(`broadcastNotice`), `agent.service`(`broadcastToAgentStatusRoom`), `sendPersonalMessage` — 은 **자기 인스턴스에 붙은 소켓만** 전달 → 다른 인스턴스 클라는 못 받음. | 🔴 **핵심 블로커** | `@socket.io/redis-adapter` 추가 (Istio면 DestinationRule `consistentHash` 병행). Redis 인프라 이미 있음 → 어댑터만 붙이면 세 경로 한 방에 해결 |
| **2** | **세션 스티키 필요** — Socket.IO 핸드셰이크(polling→ws 업그레이드)가 같은 인스턴스로 붙어야 함. Istio에선 ALB sticky 안 먹힘 | 🔴 | Istio `DestinationRule` consistentHash(쿠키/헤더) 또는 ws-only transport |
| **3** | **VOC 실시간 인메모리 상태** (`voc-realtime.service`의 `callTokens`/`companyUuidByVendor`/`states` `Map`). assist-stream(HTTP)이 캐시한 인스턴스와 nlp:complete(Redis) 처리 인스턴스가 다르면 캐시 miss → 분석 스킵. (단 **분석/저장 중복은 `acquireVocLock` SET NX EX:60 으로 이미 방어됨** → 위험은 "중복"이 아니라 "누락") | 🟡 조건부 | 캐시를 Redis로 이전, 또는 같은 callId는 같은 인스턴스가 처리 보장 |
| **4** | **테넌트 DB 커넥션 폭증** — `DynamicDatabaseService`가 인스턴스마다 테넌트별 DataSource 풀을 따로 잡음 → `N인스턴스 × M테넌트 × 풀사이즈`로 RDS `max_connections` 압박 | 🟡 | 풀사이즈 축소 + RDS Proxy/PgBouncer + 스케일 상한 |
| **5** | **스키마 마이그레이션 레이스** — `runSchemaMigrations`가 커넥션 생성마다 실행, 두 인스턴스가 동시에 같은 테넌트 첫 연결 시 DDL 레이스 | 🟢 낮음 | 이미 try/catch로 감싸져 경고만 찍고 안 죽음. 완벽히 하려면 `pg_advisory_lock` |

### 액티브-액티브에서도 문제없는 것 (참고)
- **Redis pub/sub 다리를 타는 브로드캐스트**(코칭요청/코칭 `coaching-socket.handler`, 실시간 VOC publish): 모든 인스턴스가 같은 채널 subscribe → 각자 자기 로컬 룸에만 emit → 합쳐지면 전체 전파. **이건 정석 HA 팬아웃이라 안전.**
- 순수 HTTP/프록시 API — 무상태.
- `@Cron`/`ScheduleModule` 없음(중복 배치 없음). `setInterval`은 Redis 헬스체크·로깅뿐이라 인스턴스별 N번 돌아도 무해.

---

## 5. 요약 / 보고용 한 줄

> "이중화 목적은 **가용성(HA)** 이지 **부하분산**이 아니다. 현재 KEDA `maxReplicaCount:1` = 실질 단일 액티브라 코드 문제없음. 단 이건 재기동 방식이지 무중단 핫스탠바이는 아님. 부하분산/무중단 핫스탠바이(2대 상시)로 갈 거면 Socket.IO Redis 어댑터·세션 스티키·실시간 상태 공유를 먼저 해결해야 함."
