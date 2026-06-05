# 에러 처리 & 로깅 가이드

> Advisor 의 표준 에러 처리, 로깅 패턴, 분산 추적.

---

## 1. 로깅 시스템 개요

```
NestJS Logger
    │
    └─ WinstonModule.createLogger(createWinstonConfig())
        │
        └─ winston transports:
            ├─ Console (개발/디버깅)
            └─ winston-daily-rotate-file (운영)
                ├─ logs/asst-service-yyyy-MM-dd.log  (전체)
                └─ logs/error-yyyy-MM-dd.log         (에러)
```

설정: [src/config/winston.config.ts](../../asst-service/src/config/winston.config.ts)

---

## 2. 로그 레벨

| 레벨 | 용도 | 운영 |
|------|------|------|
| `error` | 처리 실패, 외부 서비스 다운 | 항상 출력 |
| `warn` | 비정상 상황이지만 계속 진행 | 항상 출력 |
| `info` (log) | 주요 라이프사이클 (요청 시작/종료) | 기본 |
| `debug` | 디버깅용 (변수 값, 분기) | 개발만 |
| `verbose` | 매우 상세 | 거의 안 씀 |

### 환경변수로 제어

| 변수 | 의미 |
|------|------|
| `LOG_LEVEL` | 콘솔 로그 레벨 (기본 `info`) |
| `FILE_LOG_LEVEL` | 파일 로그 레벨 (기본 `info`) |
| `LOG_PRETTY_JSON` | JSON 메타 정보 들여쓰기 (기본 `false`) |

---

## 3. `TraceLogger` 패턴 (권장)

[src/common/utils/trace-logger.util.ts](../../asst-service/src/common/utils/trace-logger.util.ts):

```typescript
import { TraceLogger } from '@app/common/utils/trace-logger.util';

@Injectable()
export class FooService {
  private readonly logger = new TraceLogger(FooService.name);

  async doSomething() {
    this.logger.log('작업 시작', { foo: 'bar' });
    this.logger.error('실패', error.stack);
  }
}
```

### 일반 `Logger` 와의 차이

`TraceLogger`는 **자동으로 trace ID prefix** 추가:

```
\x1b[90m[abc-123-def]\x1b[0m 작업 시작
\x1b[90m{
  "foo": "bar"
}\x1b[0m
```

→ 분산 추적에 필수. 같은 요청의 모든 로그를 grep 가능.

### Trace ID 동작

[src/common/utils/trace-id.util.ts](../../asst-service/src/common/utils/trace-id.util.ts) — `AsyncLocalStorage` 기반:

1. `TraceIdMiddleware` 가 요청마다 trace ID 생성 (또는 헤더에서 계승)
2. `runWithTraceId(traceId, () => next())` 로 비동기 컨텍스트 wrap
3. 이후 비동기 깊이와 무관하게 `getTraceId()` 호출 가능
4. 응답 헤더에도 `x-trace-id` 부착 (클라이언트가 추적 가능)

---

## 4. 에러 처리 패턴

### 4-1. NestJS 표준 `HttpException`

```typescript
throw new HttpException(
  '통화 통계를 찾을 수 없습니다',
  HttpStatus.NOT_FOUND,
);
```

→ NestJS가 자동으로 JSON 응답 변환:

```json
{
  "statusCode": 404,
  "message": "통화 통계를 찾을 수 없습니다",
  "error": "Not Found"
}
```

### 4-2. 외부 서비스 호출 표준 에러 매핑

[llm-orchestrator.service.ts](../../asst-service/src/common/services/llm-orchestrator.service.ts) 등에서 사용하는 패턴:

```typescript
try {
  const response = await axios.post(url, body, { headers, timeout: 30000 });
  // ...
} catch (error) {
  if (axios.isAxiosError(error)) {
    if (error.response) {
      throw new HttpException(
        `LLM Orchestrator 서비스 오류: ${error.response.status}`,
        HttpStatus.BAD_GATEWAY,  // 502
      );
    }
    if (error.request) {
      throw new HttpException(
        'LLM Orchestrator 서비스에 연결할 수 없습니다.',
        HttpStatus.SERVICE_UNAVAILABLE,  // 503
      );
    }
  }
  if (error instanceof HttpException) throw error;
  throw new HttpException('호출 중 오류 발생', HttpStatus.INTERNAL_SERVER_ERROR);
}
```

표준 매핑:
- **502 Bad Gateway** — 외부 서비스가 응답했지만 4xx/5xx
- **503 Service Unavailable** — 외부 서비스 연결 불가 (네트워크/DNS)
- **500 Internal Server Error** — 그 외 알 수 없는 에러
- **400 Bad Request** — 입력 검증 실패
- **404 Not Found** — 리소스 없음

### 4-3. 에러 정보 추출 헬퍼

[src/common/utils/error.util.ts](../../asst-service/src/common/utils/error.util.ts):

```typescript
export const extractErrorInfo = (error: unknown): { message: string; stack?: string } => {
  if (error instanceof Error) return { message: error.message, stack: error.stack };
  if (typeof error === 'string') return { message: error };
  return { message: 'Unknown error' };
};
```

`catch (error: unknown)` 패턴에서 안전하게 메시지/스택 추출.

---

## 5. 절대 금지 사항

### ❌ 에러를 silent하게 삼키지 말 것

```typescript
// 잘못된 예
try {
  await externalCall();
} catch {
  // 아무것도 안 함
}
```

```typescript
// 올바른 예
try {
  await externalCall();
} catch (error) {
  this.logger.warn('외부 호출 실패, 계속 진행', { error: extractErrorInfo(error) });
  // 또는 throw 또는 fallback
}
```

### ❌ `any` 타입의 에러 catch

```typescript
// 잘못
} catch (error: any) {
  console.log(error.message);  // 런타임에 undefined일 수 있음
}
```

```typescript
// 올바름
} catch (error: unknown) {
  const { message } = extractErrorInfo(error);
  this.logger.error(message);
}
```

### ❌ `console.log` 디버깅 잔존

운영 코드에 `console.log` 금지. `Logger` / `TraceLogger` 사용.

> **현재 `auth.middleware.ts`에 console.log 다수 존재** — 운영 환경에서는 줄여야 함 (인계 이슈).

---

## 6. OpenTelemetry 통합

[main.ts:1, 19, 23](../../asst-service/src/main.ts) — `@opentelemetry/sdk-node` 자동 트레이싱:

```typescript
import { tracer } from '@app/tracer';
tracer.start();
```

자동 계측 대상:
- HTTP 인바운드/아웃바운드
- TypeORM 쿼리
- Express 라우트
- Socket.IO

### 환경변수

| 변수 | 의미 |
|------|------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP 수집기 URL |
| `OTEL_SERVICE_NAME` | 서비스 식별자 (`asst-service`) |
| `OTEL_RESOURCE_ATTRIBUTES` | 추가 메타데이터 |
| `OTEL_TRACES_SAMPLER` | 샘플링 (예: `parentbased_traceidratio`) |
| `OTEL_TRACES_SAMPLER_ARG` | 샘플링 비율 (0.0~1.0) |

→ 운영에서는 보통 1~10% 샘플링. 모든 요청 추적 시 비용 증가.

---

## 7. 로그 검색 / 모니터링

운영 환경 권장 구성:

| 도구 | 용도 |
|------|------|
| Loki / Elasticsearch | 로그 집계 |
| Grafana / Kibana | 로그 검색 / 시각화 |
| Jaeger / Tempo | 분산 추적 시각화 |
| Prometheus | 메트릭 (별도 구현 필요) |

**핵심 쿼리 패턴**:
- 특정 요청 추적: `x-trace-id:abc-123` 또는 `[abc-123]`
- 에러 모니터링: `level:error AND service:asst-service`
- 외부 서비스 장애: `"LLM Orchestrator 서비스 오류"`
- 테넌트별 트래픽: `tenant_id:tenantA`

---

## 8. 알려진 로깅 함정

1. **민감 정보 노출**:
   - [auth.middleware.ts](../../asst-service/src/common/middleware/auth.middleware.ts) 가 토큰 일부 출력
   - [llm-orchestrator.service.ts](../../asst-service/src/common/services/llm-orchestrator.service.ts) 는 `hasToken: boolean`만 출력 (좋은 예)
   - 비밀번호, 신용카드, 주민번호 등은 마스킹 필수
2. **JSON 직렬화 비용** — 매우 큰 객체 로깅 시 성능 저하. `LOG_PRETTY_JSON=false` 권장.
3. **로그 디스크 누적** — `winston-daily-rotate-file` 의 `maxSize` / `maxFiles` 설정 확인
4. **K8s 로그 손실** — pod 재시작 시 파일 로그 손실. stdout으로 수집기에 전송 필요.

---

## 9. 인계 시 강조

1. **`TraceLogger` 사용 권장** — 모든 신규 서비스에 적용
2. **`auth.middleware.ts` console.log 정리** — 운영 노이즈 + 보안
3. **외부 서비스 에러 매핑 일관성** — 502/503 컨벤션 유지
4. **에러 silent 금지** — 항상 log + rethrow 또는 fallback
5. **OpenTelemetry 샘플링 비율** — 트래픽 늘면 조정 필요
6. **로그 보존 정책** — 디스크 용량 + 컴플라이언스(개인정보 보관 기간)

---

## 10. 디버깅 워크플로우

문제 발생 시:

1. **trace ID 확보** — 사용자 화면에서 응답 헤더 `x-trace-id` 복사
2. **로그 시스템에서 trace ID 검색** — 전체 흐름 파악
3. **에러 메시지로 코드 위치 추적** — 메시지 grep
4. **외부 서비스 호출이라면** Orchestrator 측 trace ID도 확인 (LLM 응답 `data.traceId`)
5. **재현이 안 되면** Redis 메시지 시뮬레이션 또는 mock 응답으로 시나리오 재현
