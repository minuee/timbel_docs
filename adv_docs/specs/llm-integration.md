# LLM 통합 (LLM Orchestrator 연동)

> Advisor에서 LLM을 부르는 모든 경로는 [LlmOrchestratorService](../../asst-service/src/common/services/llm-orchestrator.service.ts) 1개를 통합니다.
> 직접 fetch/axios로 LLM API 호출 금지.

---

## 1. 통합 지점

| 호출자 | 용도 | API | 프롬프트 |
|--------|------|-----|---------|
| `SummaryService` | 통화 요약 | `complete()` | `adv-conversations-summarize` |
| `SummaryService` | 키워드 추출 | `complete()` | `adv-conversations-summarize-keyword` |
| `TodoService` | 자동 todo 생성 | `complete()` | `adv-conversations-todo` |
| (확장) 통화 분류 | LLM 카테고리 분류 | `complete()` | 설계: [plans/done/2026-04-17-counseling-type-llm-plan.md](../plans/done/2026-04-17-counseling-type-llm-plan.md) |

→ 사용자 발화 RAG 답변(`assist-stream`)은 LLM Orchestrator가 아닌 **`SEARCH_HOST`**를 직접 호출. 별개 경로.

---

## 2. 두 가지 API

### 2-1. `complete()` — 프롬프트 이름 기반 (권장)

```typescript
const result = await llmOrchestratorService.complete<string>({
  promptName: 'adv-conversations-summarize',
  tenantId: tenantConfig.tenant_id,
  serviceName: 'asst-service',
  token: req.token,
  userId: agentId,
  variables: { turns: [...], topIntents: [...] },
});
```

- LLM Orchestrator 측에 등록된 프롬프트 이름을 호출
- variables 객체가 프롬프트 템플릿에 주입됨
- 모델/파라미터는 Orchestrator 측 설정에 위임 → **프롬프트 변경 시 Advisor 코드 수정 불필요**

엔드포인트: `POST {LLM_ORCHESTRATOR_HOST}/llm/complete`

### 2-2. `customComplete()` — provider/model 직접 지정

```typescript
const result = await llmOrchestratorService.customComplete<string>({
  provider: 'openai',
  model: 'gpt-4o',
  messages: [
    { role: 'system', content: '...' },
    { role: 'user', content: '...' },
  ],
  tenantId,
  serviceName: 'asst-service',
  token,
});
```

- 프롬프트 템플릿 없이 직접 messages 전달
- 모델/provider를 코드에서 직접 결정

엔드포인트: `POST {LLM_ORCHESTRATOR_HOST}/llm/custom/complete`

**언제 어느 걸 쓰나?**
- 일반: `complete()` 사용 — 프롬프트 관리를 Orchestrator로 분리
- 실험적/임시 호출: `customComplete()`

---

## 3. 필수 헤더

모든 호출에 다음 헤더가 자동으로 부착됩니다:

| 헤더 | 값 | 의미 |
|------|------|------|
| `X-Tenant-Id` | `tenantConfig.tenant_id` | 멀티테넌트 격리 (필수) |
| `X-Service-Name` | `'asst-service'` 등 | 호출자 식별 (Orchestrator 측 로깅/과금) |
| `Authorization` | `Bearer <token>` | 사용자 토큰 (옵션) |
| `X-User-Id` | agent_id | 사용자 식별 (옵션) |

**⚠️ `tenantId`가 비어 있으면 400 에러로 fail-fast** ([line 77-82](../../asst-service/src/common/services/llm-orchestrator.service.ts#L77-L82)). assist-stream의 `X-Tenant-Id` 하드코딩 TODO 와 동일한 패턴 — 정상 호출 경로에서는 토큰에서 추출.

---

## 4. 응답 형식

[line 6-19](../../asst-service/src/common/services/llm-orchestrator.service.ts#L6-L19):

```typescript
interface LlmOrchestratorResponse<T> {
  success: boolean;
  data?: {
    content: T;            // 실제 결과 (제네릭)
    usage?: unknown;       // 토큰 사용량
    model?: string;        // 사용된 모델
    provider?: string;
    traceId?: string;      // Orchestrator 측 trace ID
    latencyMs?: number;
    promptVersion?: string;
  };
  timestamp?: string;
}
```

→ `complete()` 메서드는 `data.content`만 반환. 메타데이터(usage/model/cost)가 필요하면 wrapper에서 추출 필요.

---

## 5. 에러 처리

[line 141-171](../../asst-service/src/common/services/llm-orchestrator.service.ts#L141-L171):

| 원인 | 상태 코드 | 메시지 |
|------|-----------|--------|
| `LLM_ORCHESTRATOR_HOST` 미설정 | 500 | `LLM Orchestrator Host가 설정되지 않았습니다.` |
| `tenantId` 누락 | 400 | `X-Tenant-Id에 사용할 tenantId가 필요합니다.` |
| Orchestrator 응답 4xx/5xx | 502 | `LLM Orchestrator 서비스 오류: 500 Internal Server Error` |
| `response.success === false` | 502 | `LLM Orchestrator 응답 형식이 올바르지 않습니다.` |
| 네트워크 연결 불가 | 503 | `LLM Orchestrator 서비스에 연결할 수 없습니다.` |
| 그 외 | 500 | `LLM Orchestrator 호출 중 오류가 발생했습니다.` |

호출자(서비스)는 이 에러를 그대로 throw하거나 도메인 컨텍스트로 wrap (예: SummaryService).

---

## 6. Timeout

axios `timeout: 30000` (30초). LLM 응답이 30초 초과 시 timeout 에러.

→ 실시간성이 중요한 경로(예: 통화 중 todo 생성)에서는 적절히 조정 필요. 현재는 모든 호출 동일 30초.

---

## 7. Fallback: `LLM_HOST`

[line 50-53](../../asst-service/src/common/services/llm-orchestrator.service.ts#L50-L53):

```typescript
this.orchestratorHost =
  this.configService.get<string>('LLM_ORCHESTRATOR_HOST') ||
  this.configService.get<string>('LLM_HOST') ||
  '';
```

→ `LLM_ORCHESTRATOR_HOST`가 없으면 `LLM_HOST` 사용. **레거시 LLM Manager 호환용**이며 같은 API 스펙을 가정. 운영 환경에서는 `LLM_ORCHESTRATOR_HOST` 사용 권장.

---

## 8. 호출 추적

호출 시점 로그 ([line 101-107](../../asst-service/src/common/services/llm-orchestrator.service.ts#L101-L107)):

```
LLM Orchestrator 요청 상세 { url, promptName, tenantId, serviceName, hasToken: true }
```

토큰 본문은 로깅하지 않고 `hasToken` boolean만 기록.

추가 추적은 응답의 `data.traceId`로 Orchestrator 측 로그와 연결.

---

## 9. 프롬프트 이름 컨벤션

```
adv-{영역}-{용도}-{선택적 옵션}
```

예시:
- `adv-conversations-summarize` — 통화 요약
- `adv-conversations-summarize-keyword` — 키워드 추출
- `adv-conversations-todo` — 자동 todo 생성

→ 새 프롬프트 추가 시 `adv-` prefix + 도메인 + 명사. Orchestrator 측 운영자와 합의.

---

## 10. 인계 시 체크 포인트

1. **`X-Tenant-Id` 정확성** — 토큰에서 추출한 `tenant_id` 사용. 하드코딩 금지.
2. **`X-Service-Name`** — `'asst-service'` 고정. 다른 서비스에서 호출 시 변경 (예: BFF 프록시).
3. **에러 분기** — 502 (LLM 측 응답 오류) vs 503 (연결 불가)을 사용자에게 다르게 표시 가능.
4. **30초 timeout** — 답변이 긴 경우 잘릴 수 있음. 스트리밍이 필요하면 별도 SSE 엔드포인트 사용.
5. **변수 주입 검증** — `variables` 객체에 누락된 키가 있으면 Orchestrator 측에서 에러. 호출 전 검증 권장.
6. **모델/비용 변경** — Advisor 코드 수정 없이 Orchestrator 측 프롬프트 설정만으로 가능 (decoupling).
7. **테스트**: 단위 테스트에서는 `LlmOrchestratorService` 모킹. spy를 통해 호출 인자 검증.

---

## 11. 향후 개선 후보

- **재시도 정책**: 현재는 1회 호출 후 실패하면 즉시 에러. transient 에러(503)에 대한 exponential backoff 검토.
- **응답 캐싱**: 같은 요약 요청이 반복될 때 캐싱 (현재 없음).
- **모델별 timeout 차등**: 짧은 응답(키워드)과 긴 응답(요약)에 다른 timeout.
- **메타데이터 활용**: `usage.totalTokens` 모니터링으로 비용 추적.
