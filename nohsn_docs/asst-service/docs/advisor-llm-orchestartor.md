# 어드바이저 LLM / Orchestrator 정리

asst-service가 LLM을 호출하는 기능과 프롬프트·스키마 정리.

## 1. LLM 호출 경로 한눈에

`POST /summary` 안에서 4갈래 병렬 + `POST /todos/auto-create` 별도.

| 기능 | LLM_ORCHESTRATOR_HOST 사용? | 프롬프트 위치 | 호출 방식 / 모델 |
|------|:---:|------|------|
| 요약문 | ✅ | Orchestrator 등록 `adv-conversations-summarize` | complete |
| 키워드 | ✅ | Orchestrator 등록 `adv-conversations-summarize-keyword` | complete |
| 상담유형 | ✅ | **코드 하드코딩** (`summary.service.ts`) | customComplete (openai/gpt-4o-mini) |
| 감정/VOC | ❌ 기본 CE | 코드(`buildVocPrompt`) / CE쪽 | 기본 CE API · `VOC_ANALYZER=llm`이면 orchestrator |
| 자동 To-Do | ✅ | Orchestrator 등록 `adv-auto-create-todos` | complete |

- **요약/키워드/자동todo**: 프롬프트가 Orchestrator에 등록 → 코드 안 건드리고 교체 가능.
- **상담유형**: 프롬프트가 코드에 박힘(분류 체계 목록까지) → 변경 시 코드 수정 + 재배포. 단 호출은 orchestrator를 탐.
- **감정**: 호출 자체가 CE 서비스(orchestrator 아님).

## 2. Orchestrator 호스트 (환경별)

| 환경 | LLM_ORCHESTRATOR_HOST | 비고 |
|------|------------------------|------|
| AWS k8s 배포 | `http://llm-orchestrator-service-svc.aicc/api/llm-orchestrator/v1` (내부 DNS) | 인프라가 차트(values)에 설정. 클러스터 내부 전용 |
| 5층/192 도커 | `https://ecpad.etaas.co.kr/aicc/llm-orchestrator-service` (게이트웨이) | 끝슬래시·`/api` prefix 없음 (게이트웨이가 prefix 부여) |
| (구) langsa | `https://dev-ecp-llm-orchestrator-service.langsa.ai/api/llm-orchestrator/v1` | **삭제 예정** — 위 두 경로로 대체됨 |

- 게이트웨이 주소 **직접 호출 검증 완료**(201, success:true, gpt-4o-mini 응답). 코드가 base에 `/llm/complete`·`/llm/custom/complete` 를 붙임.
- 호출 헤더: `Content-Type`, `X-Tenant-Id`(테넌트), `X-Service-Name: adv`, `Authorization: Bearer <token>`.
- 응답 형식: `{ success, data: { content, usage, model, provider, traceId, latencyMs }, timestamp }`.

## 3. 등록 프롬프트 호출 형식 (complete)

코드는 promptName + variables 만 보냄. 프롬프트 전문은 **Orchestrator 레지스트리에서 관리**(레포에 없음).

| promptName | variables | 비고 |
|------------|-----------|------|
| `adv-conversations-summarize` | `conversation` | 요약문 4항목(고객문의/처리결과/후속조치/특이사항) → 마크다운 조립 |
| `adv-conversations-summarize-keyword` | `conversation`, `count` | 키워드 배열 |
| `adv-auto-create-todos` | `callStat`, `maxLength`, `includeSimple` | 할일 문자열 배열 |

### 키워드 프롬프트가 system/user 2개인 이유
버그 아님 — ChatCompletion 표준 구조. **system=역할·규칙(고정), user=실제 대화 데이터(가변)**. 분리 이유: ①모델이 system을 지시로 더 강하게 따름 ②역할 고정·데이터만 교체(재사용성) ③프롬프트 인젝션 방어 ④OpenAI role 규격. (상담유형도 동일하게 system+user 구조)

---

## 4. 상담유형 분류 (코드 하드코딩 — 전문)

| 항목 | 값 |
|------|-----|
| 명 | `classify-counseling-type` (코드 내장, Orchestrator 미등록) |
| 목적 | 상담 종료 후 상담유형 최대 3개 분류 (대분류>중분류>소분류) |
| 위치 | `summary.service.ts` `classifyCounselingType` |

### 프롬프트 설정
```json
{ "provider": "openai", "model": "gpt-4o-mini" }
```
> 코드 customComplete는 provider/model만 전달. temperature·maxTokens 등 미지정 → Orchestrator 기본값.

### System Prompt
```text
당신은 콜센터 상담 내용을 분석하여 상담유형을 분류하는 전문가입니다.

아래 대화 내용을 분석하여 가장 적합한 상담유형을 최대 3개까지 분류해주세요.
상담유형은 "대분류 > 중분류 > 소분류" 형태의 3계층 구조입니다.

## 상담유형 목록

### 금융/은행
- 예금 > 정기예금 > 가입문의
- 예금 > 정기예금 > 해지문의
- 예금 > 정기예금 > 금리문의
- 예금 > 보통예금 > 잔액조회
- 예금 > 보통예금 > 이체문의
- 대출 > 주택담보대출 > 금리문의
- 대출 > 주택담보대출 > 상환문의
- 대출 > 주택담보대출 > 신규신청
- 대출 > 신용대출 > 금리문의
- 대출 > 신용대출 > 한도문의
- 대출 > 신용대출 > 상환문의
- 카드 > 신용카드 > 발급문의
- 카드 > 신용카드 > 분실신고
- 카드 > 신용카드 > 한도문의
- 카드 > 체크카드 > 발급문의
- 카드 > 체크카드 > 분실신고

### 결제/거래
- 결제 > 온라인결제 > 결제오류
- 결제 > 온라인결제 > 환불요청
- 결제 > 온라인결제 > 중복결제
- 결제 > 오프라인결제 > 결제오류
- 결제 > 오프라인결제 > 단말기문의
- 이체 > 계좌이체 > 이체한도
- 이체 > 계좌이체 > 이체오류
- 이체 > 자동이체 > 등록문의
- 이체 > 자동이체 > 해지문의

### 계정/보안
- 계정 > 비밀번호 > 재설정
- 계정 > 비밀번호 > 잠금해제
- 계정 > 인증서 > 발급문의
- 계정 > 인증서 > 갱신문의
- 보안 > 사기의심 > 피싱신고
- 보안 > 사기의심 > 이상거래

### 증권/투자
- 주식 > 국내주식 > 매매문의
- 주식 > 국내주식 > 수수료문의
- 주식 > 국내주식 > 종목문의
- 주식 > 해외주식 > 매매문의
- 주식 > 해외주식 > 수수료문의
- 주식 > 해외주식 > 환율문의
- 펀드 > 펀드가입 > 가입문의
- 펀드 > 펀드가입 > 해지문의
- 펀드 > 펀드가입 > 수익률문의
- 계좌 > 증권계좌 > 개설문의
- 계좌 > 증권계좌 > 해지문의
- 계좌 > 신용계좌 > 설정문의
- 계좌 > 신용계좌 > 해지문의
- 계좌 > 신용계좌 > 융자문의
- HTS/MTS > 트레이딩시스템 > 오류문의
- HTS/MTS > 트레이딩시스템 > 사용방법

### 보험
- 보험 > 생명보험 > 가입문의
- 보험 > 생명보험 > 해지문의
- 보험 > 생명보험 > 보험금청구
- 보험 > 손해보험 > 가입문의
- 보험 > 손해보험 > 해지문의
- 보험 > 손해보험 > 보험금청구
- 보험 > 자동차보험 > 가입문의
- 보험 > 자동차보험 > 사고접수
- 보험 > 자동차보험 > 보험료문의

### 통신/모바일
- 통신 > 요금 > 요금문의
- 통신 > 요금 > 납부문의
- 통신 > 요금 > 환불요청
- 통신 > 서비스 > 가입문의
- 통신 > 서비스 > 해지문의
- 통신 > 서비스 > 변경문의
- 통신 > 단말기 > 구매문의
- 통신 > 단말기 > AS문의
- 통신 > 장애 > 네트워크장애
- 통신 > 장애 > 서비스장애

### 유통/쇼핑
- 주문 > 주문접수 > 주문문의
- 주문 > 주문접수 > 주문변경
- 주문 > 주문접수 > 주문취소
- 배송 > 배송현황 > 배송조회
- 배송 > 배송현황 > 배송지연
- 배송 > 배송현황 > 배송지변경
- 교환/반품 > 교환 > 교환신청
- 교환/반품 > 반품 > 반품신청
- 교환/반품 > 환불 > 환불문의

### 서비스
- 서비스 > 앱/웹 > 오류문의
- 서비스 > 앱/웹 > 사용방법
- 서비스 > 전화상담 > 연결문의
- 서비스 > 전화상담 > 불만접수
- 서비스 > 기타 > 일반문의
- 서비스 > 기타 > 서류요청

## 분류 규칙

1. 반드시 위 목록에서 가장 적합한 유형을 선택하세요.
2. 정확히 일치하는 유형이 없더라도, 가장 유사한 유형을 선택하여 분류하세요. 빈 배열을 반환하지 마세요.

## 응답 형식

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트를 포함하지 마세요.

[
  {
    "id": "1",
    "categoryPath": "대분류 > 중분류 > 소분류"
  }
]

- 가장 적합한 순서대로 최대 3개
- id는 순번 ("1", "2", "3")
- categoryPath는 위 목록에 있는 정확한 경로
```

### User Prompt
```text
다음 상담 대화를 분석하여 상담유형을 분류해주세요:

{{conversation}}
```

### Input Schema
```json
{
  "type": "object",
  "properties": {
    "conversation": { "type": "string", "description": "상담 대화 내용 (role: utterance 줄바꿈 연결)" }
  },
  "additionalProperties": false,
  "required": ["conversation"]
}
```

### Output Schema
```json
{
  "type": "array",
  "maxItems": 3,
  "description": "상담유형 분류 결과 (가장 적합한 순 최대 3개)",
  "items": {
    "type": "object",
    "properties": {
      "id": { "type": "string", "description": "순번 (1,2,3)" },
      "categoryPath": { "type": "string", "description": "대분류 > 중분류 > 소분류 (목록 내 정확 경로)" }
    },
    "additionalProperties": false,
    "required": ["id", "categoryPath"]
  }
}
```
