# 상담유형 LLM 분류 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 상담 요약 시 기존 NLU intent 기반 상담유형 분류를 LLM custom complete 호출로 교체하여, 전체 대화를 기반으로 대/중/소분류 형태의 상담유형을 자동 분류한다.

**Architecture:** `SummaryService.summarizeCall()`의 병렬 호출에서 기존 CE intent external-category 조회를 제거하고, LLM Orchestrator의 `/llm/custom/complete` 엔드포인트를 호출하는 방식으로 교체. LLM에게 system 메시지로 상담유형 목록과 분류 지침을, user 메시지로 전체 대화를 전달. 응답은 기존 프론트엔드 `CounselingType` 구조(`{ id, categoryPath }`)와 호환되도록 설계.

**Tech Stack:** NestJS 11, TypeScript, axios, Vue 3

**현재 흐름:**
```
summarizeCall() → Promise.all([
  callLlmSummarize(),        // → summary 텍스트
  callLlmKeywords(),         // → keywords 배열
  getIntentExternalCategories()  // → CE intent 기반 상담유형 (제거 대상)
])
```

**변경 후 흐름:**
```
summarizeCall() → Promise.all([
  callLlmSummarize(),           // → summary 텍스트 (기존 유지)
  callLlmKeywords(),            // → keywords 배열 (기존 유지)
  classifyCounselingType()      // → LLM custom complete 기반 상담유형 (신규)
])
```

**기존 저장 구조 유지:** `advisor.call_categories` 테이블에 `(callstats_id, external_categories_id)` 복합키로 저장하는 방식은 그대로. LLM이 반환하는 ID를 `external_categories_id`로 저장.

---

## Task 1: 백엔드 — LlmOrchestratorService에 customComplete 메서드 추가

**Files:**
- Modify: `asst-service/src/common/services/llm-orchestrator.service.ts`

**Step 1: interface 및 메서드 추가**

기존 `CompleteParams` 아래에 새 인터페이스를 추가하고, `customComplete` 메서드를 추가한다.

`asst-service/src/common/services/llm-orchestrator.service.ts` — `CompleteParams` 인터페이스 아래 (29행 부근)에 추가:

```typescript
interface CustomCompleteMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

interface CustomCompleteParams {
  provider: string;
  model: string;
  messages: CustomCompleteMessage[];
  tenantId: string;
  serviceName: string;
  token?: string;
}
```

클래스 내부 `complete()` 메서드 아래에 추가:

```typescript
async customComplete<T>({
  provider,
  model,
  messages,
  tenantId,
  serviceName,
  token,
}: CustomCompleteParams): Promise<T> {
  if (!this.orchestratorHost) {
    throw new HttpException(
      'LLM Orchestrator Host가 설정되지 않았습니다.',
      HttpStatus.INTERNAL_SERVER_ERROR,
    );
  }

  if (!tenantId) {
    throw new HttpException(
      'X-Tenant-Id에 사용할 tenantId가 필요합니다.',
      HttpStatus.BAD_REQUEST,
    );
  }

  const url = `${this.orchestratorHost}/llm/custom/complete`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Tenant-Id': tenantId,
    'X-Service-Name': serviceName,
  };

  if (token) {
    headers.Authorization = token.startsWith('Bearer ')
      ? token
      : `Bearer ${token}`;
  }

  this.logger.log(`LLM Custom Complete 요청`, {
    url,
    provider,
    model,
    tenantId,
    serviceName,
    messageCount: messages.length,
  });

  try {
    const response: AxiosResponse<LlmOrchestratorResponse<T>> =
      await axios.post(
        url,
        {
          provider,
          model,
          messages,
        },
        {
          headers,
          timeout: 30000,
        },
      );

    if (response.status < 200 || response.status >= 300) {
      throw new HttpException(
        `LLM Custom Complete API 응답 오류: ${response.status}`,
        HttpStatus.BAD_GATEWAY,
      );
    }

    if (
      !response.data?.success ||
      response.data.data?.content === undefined
    ) {
      throw new HttpException(
        'LLM Custom Complete 응답 형식이 올바르지 않습니다.',
        HttpStatus.BAD_GATEWAY,
      );
    }

    return response.data.data.content;
  } catch (error) {
    this.logger.error(
      `LLM Custom Complete 호출 실패: provider=${provider}, model=${model}`,
      error instanceof Error ? error.stack : String(error),
    );

    if (axios.isAxiosError(error)) {
      if (error.response) {
        throw new HttpException(
          `LLM Custom Complete 서비스 오류: ${error.response.status} ${error.response.statusText}`,
          HttpStatus.BAD_GATEWAY,
        );
      }

      if (error.request) {
        throw new HttpException(
          'LLM Custom Complete 서비스에 연결할 수 없습니다.',
          HttpStatus.SERVICE_UNAVAILABLE,
        );
      }
    }

    if (error instanceof HttpException) {
      throw error;
    }

    throw new HttpException(
      'LLM Custom Complete 호출 중 오류가 발생했습니다.',
      HttpStatus.INTERNAL_SERVER_ERROR,
    );
  }
}
```

**Step 2: 타입체크**

```bash
cd asst-service && npx tsc --noEmit
```

**Step 3: 커밋**

```bash
git add asst-service/src/common/services/llm-orchestrator.service.ts
git commit -m "feat: LLM Orchestrator에 customComplete 메서드 추가

- /llm/custom/complete 엔드포인트 호출 지원
- provider, model, messages 직접 전달 방식
- 기존 complete()와 동일한 헤더/에러 처리 패턴"
```

---

## Task 2: 백엔드 — SummaryService에 상담유형 분류 메서드 추가 및 기존 intent 로직 교체

**Files:**
- Modify: `asst-service/src/advisor/summary/services/summary.service.ts`
- Modify: `asst-service/src/advisor/summary/dto/summary-response.dto.ts`

**Step 1: SummaryResponseDto 수정**

`asst-service/src/advisor/summary/dto/summary-response.dto.ts` — `intents` 필드의 타입과 설명을 변경:

```typescript
import { ApiProperty } from '@nestjs/swagger';

export class CounselingTypeItemDto {
  @ApiProperty({ description: '상담유형 ID (external_categories_id)' })
  id: string;

  @ApiProperty({
    description: '상담유형 경로 (대분류 > 중분류 > 소분류)',
    example: '대출 > 주택담보대출 > 금리문의',
  })
  categoryPath: string;
}

export class SummaryResponseDto {
  @ApiProperty({
    description: '요약 내용',
    example:
      '고객이 결제 오류 문제로 상담을 요청했으며, 상담원이 환불 처리 방법을 안내함',
  })
  summary: string;

  @ApiProperty({
    description: '추출된 키워드 목록',
    example: ['중복결제', '환불', '온라인쇼핑', '네이버쇼핑', '카드결제오류'],
    type: [String],
  })
  keywords: string[];

  @ApiProperty({
    description: 'LLM 기반 상담유형 분류 결과',
    type: [CounselingTypeItemDto],
  })
  counselingTypes: CounselingTypeItemDto[];
}

export class LlmSummarizeContentDto {
  @ApiProperty({
    description: '요약 내용',
  })
  content: string;
}

export class LlmKeywordContentDto {
  @ApiProperty({
    description: '키워드 목록',
    type: [String],
  })
  keywords: string[];
}
```

**Step 2: SummaryService 수정**

`asst-service/src/advisor/summary/services/summary.service.ts` — 다음을 변경한다:

1. import 변경 (기존 `SummaryResponseDto` 외에 `CounselingTypeItemDto` 추가):

```typescript
import {
  SummaryResponseDto,
  LlmKeywordContentDto,
  CounselingTypeItemDto,
} from '@app/advisor/summary/dto/summary-response.dto';
```

2. `summarizeCall()` 메서드의 Promise.all 부분 (110~116행) 교체:

기존:
```typescript
const [summarizeResult, keywordResult, intentCategories] =
  await Promise.all([
    this.callLlmSummarize(conversation, tenantId, token),
    this.callLlmKeywords(conversation, keyword_count, tenantId, token),
    this.getIntentExternalCategories(topIntents, token),
  ]);
```

변경:
```typescript
const [summarizeResult, keywordResult, counselingTypes] =
  await Promise.all([
    this.callLlmSummarize(conversation, tenantId, token),
    this.callLlmKeywords(conversation, keyword_count, tenantId, token),
    this.classifyCounselingType(conversation, tenantId, token),
  ]);
```

3. result 구성 부분 (118~123행) 교체:

기존:
```typescript
const result: SummaryResponseDto = {
  summary: summarizeResult,
  keywords: keywordResult.keywords,
  intents: intentCategories,
};
```

변경:
```typescript
const result: SummaryResponseDto = {
  summary: summarizeResult,
  keywords: keywordResult.keywords,
  counselingTypes,
};
```

4. `extractTopIntents()` 호출 제거 — `summarizeCall()` 내 107행의 `const topIntents = this.extractTopIntents(turns);` 삭제 (더 이상 사용하지 않음)

5. 새 메서드 `classifyCounselingType()` 추가 (클래스 내부, `extractTopIntents()` 위치에):

```typescript
/**
 * LLM Custom Complete를 통해 상담유형을 분류합니다.
 * @param conversation 전체 대화 내용
 * @param tenantId 테넌트 ID
 * @param token 인증 토큰
 * @returns 상담유형 분류 결과 (최대 3개)
 */
private async classifyCounselingType(
  conversation: string,
  tenantId: string,
  token: string | undefined,
): Promise<CounselingTypeItemDto[]> {
  this.logger.log('LLM Custom Complete 상담유형 분류 시작');

  const systemPrompt = `당신은 콜센터 상담 내용을 분석하여 상담유형을 분류하는 전문가입니다.

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

### 서비스
- 서비스 > 앱/웹 > 오류문의
- 서비스 > 앱/웹 > 사용방법
- 서비스 > 전화상담 > 연결문의
- 서비스 > 전화상담 > 불만접수
- 서비스 > 기타 > 일반문의
- 서비스 > 기타 > 서류요청

## 응답 형식

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트를 포함하지 마세요.

\`\`\`json
[
  {
    "id": "1",
    "categoryPath": "대분류 > 중분류 > 소분류"
  }
]
\`\`\`

- 가장 적합한 순서대로 최대 3개
- id는 순번 ("1", "2", "3")
- categoryPath는 위 목록에 있는 정확한 경로
- 해당하는 유형이 없으면 빈 배열 [] 반환`;

  const userMessage = `다음 상담 대화를 분석하여 상담유형을 분류해주세요:\n\n${conversation}`;

  try {
    const response = await this.llmOrchestratorService.customComplete<string>({
      provider: 'openai',
      model: 'gpt-4o-mini',
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userMessage },
      ],
      tenantId,
      serviceName: 'adv',
      token,
    });

    // LLM 응답 파싱 (JSON 문자열 → 배열)
    const parsed = this.parseCounselingTypeResponse(response);
    this.logger.log(`상담유형 분류 완료: ${parsed.length}개`);
    return parsed;
  } catch (error) {
    this.logger.error(
      '상담유형 LLM 분류 실패',
      error instanceof Error ? error.stack : String(error),
    );
    return [];
  }
}

/**
 * LLM 응답을 파싱하여 CounselingTypeItemDto 배열로 변환합니다.
 */
private parseCounselingTypeResponse(response: string): CounselingTypeItemDto[] {
  try {
    // JSON 코드 블록이 포함된 경우 추출
    let jsonStr = response;
    const codeBlockMatch = response.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (codeBlockMatch) {
      jsonStr = codeBlockMatch[1].trim();
    }

    const parsed = JSON.parse(jsonStr);

    if (!Array.isArray(parsed)) {
      this.logger.warn('상담유형 LLM 응답이 배열이 아닙니다.');
      return [];
    }

    return parsed
      .filter(
        (item: unknown): item is { id: string; categoryPath: string } =>
          item !== null &&
          typeof item === 'object' &&
          'id' in item &&
          'categoryPath' in item &&
          typeof (item as { id: unknown }).id === 'string' &&
          typeof (item as { categoryPath: unknown }).categoryPath === 'string',
      )
      .slice(0, 3);
  } catch (error) {
    this.logger.error(
      'LLM 상담유형 응답 파싱 실패',
      error instanceof Error ? error.message : String(error),
    );
    return [];
  }
}
```

6. 기존 `extractTopIntents()`, `callCeIntentExternalCategory()`, `getIntentExternalCategories()` 3개 메서드는 **삭제**.

**Step 3: 타입체크 + 린트**

```bash
cd asst-service && npx tsc --noEmit && npm run lint
```

**Step 4: 커밋**

```bash
git add asst-service/src/advisor/summary/services/summary.service.ts \
       asst-service/src/advisor/summary/dto/summary-response.dto.ts
git commit -m "feat: 상담유형 분류를 LLM custom complete로 교체

- 기존 CE intent external-category 기반 분류 제거
- LLM custom complete (openai/gpt-4o-mini) 기반 상담유형 분류 추가
- 프롬프트에 대/중/소분류 목록 하드코딩
- 응답 DTO intents → counselingTypes로 변경"
```

---

## Task 3: 프론트엔드 — CounselingStatus.vue 응답 구조 변경 반영

**Files:**
- Modify: `asst-web/src/components/layout/HeaderActionBar/CounselingStatus.vue`

**Step 1: 요약 응답 파싱 부분 수정**

기존 (306~316행):
```typescript
counselingTypes.value = response.data.intents
  .filter(intent => Object.hasOwn(intent, "externalCategory"))
  .map((intent, index) => {
    const target = intent.externalCategory;
    return {
      id: target.id,
      rank: `${index + 1}순위`,
      category: target.categoryPath || "",
      isChecked: index === 0
    };
  });
```

변경:
```typescript
counselingTypes.value = (response.data.counselingTypes || [])
  .map((item: { id: string; categoryPath: string }, index: number) => ({
    id: item.id,
    rank: `${index + 1}순위`,
    category: item.categoryPath || "",
    isChecked: index === 0,
  }));
```

**Step 2: 린트**

```bash
cd asst-web && npm run lint
```

**Step 3: 커밋**

```bash
git add asst-web/src/components/layout/HeaderActionBar/CounselingStatus.vue
git commit -m "feat: 상담유형 응답 구조 변경 반영 (intents → counselingTypes)"
```

---

## Task 4: 프론트엔드 — SummaryData 타입 정리

**Files:**
- Modify: `asst-web/src/api/types/summary.type.ts`

**Step 1: SummaryData 타입 수정**

기존 `counseling_type?: string` 필드는 DB에 대응하는 컬럼이 없으므로 제거하거나, 실제 사용하는 필드로 정리.

`asst-web/src/api/types/summary.type.ts`:
```typescript
// Summary 관련 타입 정의

export interface CounselingTypeItem {
  id: string;
  categoryPath: string;
}

export interface SummaryData {
  id: string;
  callstats_id: string;
  summary: string;
  keywords?: string[];
  external_categories?: string[];
  counselingTypes?: CounselingTypeItem[];
  created_at: string;
  updated_at: string;
}

export interface CreateSummaryReq {
  callstats_id: string;
  keyword_count: number;
}

export interface SaveSummaryDataReq {
  callstats_id: string;
  summary: string;
  keywords: string[];
  external_categories_id: string[];
}
```

**Step 2: 커밋**

```bash
git add asst-web/src/api/types/summary.type.ts
git commit -m "refactor: SummaryData 타입에 CounselingTypeItem 추가, 미사용 counseling_type 제거"
```

---

## Task 5: 검증

**Step 1: 백엔드 빌드 확인**

```bash
cd asst-service && npm run build
```

**Step 2: 프론트엔드 빌드 확인**

```bash
cd asst-web && npm run build:dev
```

**Step 3: ChatHistoryModal 등 다른 참조 확인**

`ChatHistoryModal.vue`에서 `external_categories`를 사용하는 부분이 있다면 확인. 저장 시 `saveSummaryData`에서 보내는 `external_categories_id`는 기존 `counselingTypes`의 `id`를 그대로 사용하므로, `call_categories` 테이블에 저장되는 흐름은 변경 없음.

**Step 4: 빌드 오류 수정 후 최종 커밋 (필요 시)**

---

## 주의사항

1. **프롬프트 상담유형 목록은 임시** — 현재 하드코딩된 목록은 실제 운영 데이터와 다를 수 있음. 추후 CE lexicon external-categories에서 동적으로 가져오는 방식으로 개선 가능.

2. **LLM 응답이 JSON이 아닌 경우** — `parseCounselingTypeResponse()`에서 코드 블록 추출 + try-catch로 방어. 파싱 실패 시 빈 배열 반환 (서비스 중단 방지).

3. **기존 call_categories 저장 호환** — LLM이 반환하는 `id`가 순번 문자열("1", "2", "3")이므로, `external_categories_id`로 저장됨. 기존 CE에서 오던 UUID와 형식이 다르지만 테이블 구조는 `VARCHAR(64)`라 문제없음.

4. **수정 모달 (CounselingTypeModal)** — 상담사가 직접 수정/추가하는 모달은 기존 CE lexicon에서 옵션을 가져오는 방식 그대로 유지됨 (depth1~depth4). 이 부분은 이번 변경에 영향 없음.
