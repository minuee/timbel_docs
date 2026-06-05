> **문서 상태**
> | 항목 | 값 |
> |------|-----|
> | 상태 | `draft` |
> | 검수 | `unreviewed` |
> | 출처 | `docs/02-architecture/06-external-integration/6-3-retrieval-service-integration.md` 엣지케이스 분석 |
> | 최종 수정 | 2026-04-08 |

# retrieval-service 연동 — 엣지케이스 및 권장 대응 방안

> 원문 위치: [retrieval-service 연동](./6-3-retrieval-service-integration.md)
>
> 본 문서는 retrieval-service 연동 설계에서 명시적으로 다뤄지지 않은 엣지케이스를 식별하고, 각 케이스에 대한 권장 대응 방안을 정리한다.

---

## 요약 — 엣지케이스 매트릭스

| # | 엣지케이스 | 우선순위 | 카테고리 | 결정 | 관련 엔드포인트 | 영향 |
|:-:|-----------|:-------:|---------|:----:|---------------|------|
| EC-01 | 같은 source_id 동시 embed/re-embed 경합 | **높음** | 동시성 | **보류** | `POST /ingest/embed`, `POST /ingest/re-embed` | 청크 중복·데이터 정합성 |
| EC-02 | BullMQ 재시도 시 append 중복 (멱등성 부재) | **높음** | 멱등성 | **A안 채택** | `POST /ingest/embed` | 청크 이중 생성 |
| EC-03 | 배치 분할 Child Job 부분 실패 | **높음** | 배치 처리 | **권장안 채택** | `POST /ingest/embed` | embedding_status 불확정 |
| EC-04 | 블록 삭제·추가 시 re-embed 처리 | **중간** | 데이터 무결성 | **변형안 채택** | `POST /ingest/re-embed` | 고아 청크·누락 청크 |
| EC-05 | 임베딩 대상 블록 0개인 문서 | **중간** | 경계값 | **권장안 채택** | `POST /ingest/embed` | 상태 처리 누락 |
| EC-06 | 에러 응답 공통 구조 부재 | **중간** | API 설계 | **권장안 채택** | 전체 | 소비자 구현 불확정 |
| EC-07 | is_suspended 갱신 지연 검색 노출 | **중간** | 일관성 | **보류** | `PATCH /metadata`, `POST /search` | 보안·UX |
| EC-08 | 메타데이터 갱신과 재임베딩 동시 실행 | **중간** | 동시성 | **권장안 채택** | `PATCH /metadata`, `POST /ingest/re-embed` | 메타 불일치 |
| EC-09 | 존재하지 않는 source_id 삭제 | **낮음** | 예외 처리 | **권장안 채택** | `DELETE /sources/{sourceId}` | 동작 모호 |
| EC-10 | PUT /config 유효성 검증 | **낮음** | 입력 검증 | **보류** | `PUT /config` | 잘못된 설정 적용 |
| EC-11 | hybrid 모드 + ES disconnected | **낮음** | 장애 대응 | 미결정 | `POST /search` | 검색 모드 degradation |
| EC-12 | 검색 결과 0건 처리 | **낮음** | 경계값 | 미결정 | `POST /search` | UX |

---

## EC-01: 같은 source_id 동시 embed / re-embed 경합 — `보류`

### 문제

문서 게시 직후 빠르게 수정하면 BullMQ `embedding` 큐와 `re-embedding` 큐에 같은 문서의 Job이 동시에 존재할 수 있다. retrieval-service가 append 방식이므로 청크가 중복 생성되거나, re-embed가 아직 존재하지 않는 청크를 삭제 시도하는 등 정합성 문제가 발생한다.

```
시간 →
  T1: document.published → embedding 큐에 Job A 등록 (전체 임베딩)
  T2: 사용자 블록 수정 → re-embedding 큐에 Job B 등록 (부분 재임베딩)
  T3: Job A 실행 중... (Milvus에 청크 append 중)
  T4: Job B 실행 시작 — Job A가 만든 청크가 아직 불완전한 상태에서 변경분 교체 시도
  → 불확정 상태
```

### 권장 방안

**A안 (권장): source_id 단위 BullMQ concurrency 제한**

```typescript
// EmbeddingProcessor 워커 설정
// 같은 source_id를 가진 Job은 동시 실행 불가 — BullMQ의 Job groupId 활용
const embeddingWorker = new Worker('embedding', processor, {
  concurrency: 10,     // 전체 동시 처리 수
  group: {
    concurrency: 1,    // 같은 group(= source_id) 내에서는 직렬 실행
  },
});

// Job 등록 시 groupId 지정
await embeddingQueue.add('embed', payload, {
  group: { id: payload.source_id },
});
```

- `embedding`과 `re-embedding` 큐를 **단일 `embedding` 큐**로 통합하고, Job data 내 `type: 'embed' | 're-embed'`으로 구분
- source_id 기준 group concurrency = 1로 설정하여 같은 문서에 대한 Job이 자연스럽게 FIFO 직렬 실행됨
- 다른 문서의 Job은 병렬 실행 가능하므로 전체 처리량에 영향 없음

**B안: re-embed 등록 시 기존 embed Job 취소**

```typescript
// re-embed Job 등록 전 대기 중인 embed Job 제거
const waitingJobs = await embeddingQueue.getJobs(['waiting', 'delayed']);
for (const job of waitingJobs) {
  if (job.data.source_id === sourceId && job.data.type === 'embed') {
    await job.remove();
  }
}
// 이미 active인 Job은 완료 후 re-embed가 덮어쓰므로 허용
await embeddingQueue.add('re-embed', payload);
```

- embed가 이미 실행 중이면 완료 후 re-embed가 변경분을 교체하므로 결과적 정합성 확보
- 단, active Job 취소는 Milvus 데이터 불일치를 유발하므로 **waiting 상태만 제거**

### 결론

**A안을 권장**한다. BullMQ의 group concurrency는 정확히 이 사용 사례를 위해 설계되었으며, 큐 통합은 운영 복잡도도 줄인다. 두 큐를 유지해야 한다면 B안을 병행한다.

---

## EC-02: BullMQ 재시도 시 append 중복 (멱등성 키 부재) — `A안 채택 → 연동 문서 반영 완료`

### 문제

`POST /ingest/embed`는 멱등성 ✗이고 append 방식이다. 다음 시나리오에서 청크가 이중 생성된다:

```
T1: aicm-service → POST /ingest/embed 전송
T2: retrieval-service가 청크를 Milvus에 append 완료, 200 응답 전송
T3: 네트워크 오류로 aicm-service가 응답 수신 실패
T4: BullMQ가 Job을 재시도 → 동일 블록이 다시 append됨
→ 같은 블록에서 파생된 동일 청크가 2벌 존재
```

### 권장 방안

**A안 (권장): request_id 기반 중복 방지 (서버 사이드 멱등성)**

```typescript
interface IngestEmbedRequest {
  request_id: string;        // 추가: UUID v4 — Job ID를 그대로 사용
  source_id: string;
  blocks: IngestBlock[];
  source_metadata: { ... };
  chunking_config?: ChunkingConfig;
}
```

- aicm-service가 BullMQ Job ID를 `request_id`로 전달
- retrieval-service는 `request_id`를 Redis/인메모리 캐시에 TTL(예: 1시간) 기록
- 동일 `request_id` 재요청 시 이전 결과를 캐시에서 반환 (실제 처리 스킵)
- TTL은 BullMQ 재시도 간격(지수 백오프 최대값) + 여유를 고려하여 설정

**B안: 요청 전 기존 청크 삭제 (upsert 방식)**

```
embed 요청 시:
1. retrieval-service가 해당 source_id + request 범위의 기존 청크를 먼저 삭제
2. 새 청크를 삽입
→ 재시도해도 delete-then-insert로 중복 방지
```

- 단, 배치 분할 시 각 배치가 서로 다른 블록 범위를 담당하므로 "어떤 범위의 청크를 삭제할지" 판별이 복잡해짐
- append 방식의 설계 의도와 충돌

**C안: aicm-service 사이드 보정**

```typescript
// EmbeddingProcessor — embed 응답 처리 시
const existingChunks = await chunkRepository.findByDocumentId(sourceId);
const newChunkIds = response.chunks.map(c => c.chunk_id);
const duplicates = existingChunks.filter(c => newChunkIds.includes(c.id));
if (duplicates.length > 0) {
  // 기존 중복 청크 레코드 제거 후 새 것으로 교체
  await chunkRepository.removeByIds(duplicates.map(d => d.id));
}
await chunkRepository.bulkInsert(response.chunks);
```

- RDB 측 중복은 방지하지만 Milvus/ES에 중복 청크가 남아 검색 시 동일 내용이 중복 반환됨

### 결론

**A안을 권장**한다. `request_id`는 BullMQ Job ID를 그대로 재활용할 수 있어 구현이 간단하고, 벡터 DB 측 중복도 원천 차단한다. `IngestEmbedRequest`에 `request_id` 필드를 추가해야 하므로 API 스펙 변경이 수반된다.

---

## EC-03: 배치 분할 Child Job 부분 실패 — `권장안 채택 → 연동 문서 반영 완료`

### 문제

블록 수 > `ingest_batch_size`일 때 BullMQ Flow(Parent + Child N개)로 분할되는데, 일부 Child만 실패하면:

- 성공한 Child의 청크는 이미 Milvus에 append됨
- 실패한 Child의 블록은 임베딩되지 않음
- `embedding_status`를 `completed`? `partial`? `failed`?
- `content_hash`가 전체 블록 기준으로 산출되어 있으나, 실제 임베딩된 블록은 일부분

### 권장 방안

**Parent Job 완료 조건 및 상태 전이 규칙을 명확히 정의:**

```
모든 Child 성공:
  → embedding_status = 'completed'
  → content_hash 정합성 OK

일부 Child 성공, 일부 실패 (재시도 3회 소진):
  → embedding_status = 'partial'
  → 성공한 청크는 유지 (검색 가능)
  → 실패 Child의 block_id 목록을 Document.embedding_context JSONB에 기록:
    { "failed_batches": [{ "block_ids": [...], "error": "...", "failed_at": "..." }] }
  → Reconciliation 배치에서 partial 문서를 감지하여 failed 블록만 재시도

모든 Child 실패:
  → embedding_status = 'failed'
  → Milvus에 부분 삽입된 청크가 있으면 Reconciliation에서 정리

전체 Child 성공이지만 일부 블록에 failed_blocks 존재:
  → embedding_status = 'partial'
  → ChunkResult는 성공 블록의 청크만 포함
```

**content_hash 불일치 보정:**

```typescript
// Reconciliation 배치 — partial 문서 처리
if (document.embedding_status === 'partial') {
  const storedHash = await retrievalClient.getSourceContentHash(document.id);
  const currentHash = computeContentHash(document.blocks);
  
  if (storedHash !== currentHash) {
    // 실패 블록이 있으므로 해시 불일치는 예상된 상태
    // failed_batches에 기록된 블록만 재임베딩 시도
    await embeddingQueue.add('re-embed-partial', {
      source_id: document.id,
      block_ids: document.embedding_context.failed_batches.flatMap(b => b.block_ids),
    });
  }
}
```

**BullMQ Flow 설정:**

```typescript
// Parent Job은 모든 Child 완료를 대기
const flow = new FlowProducer();
await flow.add({
  name: 'embed-parent',
  queueName: 'embedding',
  data: { source_id: docId, total_batches: N },
  children: batches.map((batch, i) => ({
    name: `embed-child-${i}`,
    queueName: 'embedding',
    data: { source_id: docId, blocks: batch, batch_index: i },
    opts: { attempts: 3, backoff: { type: 'exponential', delay: 5000 } },
  })),
  opts: {
    failParentOnFailure: false,  // Child 실패 시 Parent는 partial 처리
  },
});
```

### 결론

`failParentOnFailure: false`로 설정하여 Child 부분 실패를 허용하고, Parent Job의 `onCompleted` 핸들러에서 Child 상태를 집계하여 `embedding_status`를 결정한다. Reconciliation 배치가 `partial` 상태를 감지하여 재시도하는 자동 복구 루프를 구성한다.

---

## EC-04: 블록 삭제·추가 시 re-embed 처리 — `변형안 채택 → 연동 문서 반영 완료`

> **채택안**: 권장안(구조 변경 시 전체 재임베딩)이 아닌, **`modified_block_ids` / `added_block_ids` / `removed_block_ids`를 명시적으로 분리 전달**하는 방식을 채택함. retrieval-service가 변경 유형별로 최적화된 처리를 수행할 수 있다.

### 문제

`POST /ingest/re-embed`는 `changed_block_ids`로 **변경된** 블록을 지정하지만, 블록 삭제·추가·순서 변경 시 처리가 불명확하다.

| 시나리오 | `blocks` 배열 | `changed_block_ids` | 질문 |
|---------|--------------|-------------------|------|
| 블록 B 삭제 | A, C, D (B 없음) | `[B]`? `[]`? | blocks에 없는 ID를 changed에 넣을 수 있는가? |
| 블록 E 추가 | A, B, C, D, E | `[E]`? | 신규 블록도 "변경"으로 간주하는가? |
| 블록 순서만 변경 | D, C, B, A | `[]`? `[A,B,C,D]`? | content 동일이지만 청크 구성이 달라질 수 있음 |

### 권장 방안

**changed_block_ids의 의미를 확장 정의:**

```typescript
interface IngestReEmbedRequest {
  source_id: string;
  blocks: IngestBlock[];             // 변경 후 문서의 전체 블록 (현재 상태)
  changed_block_ids: string[];       // 변경/추가된 블록 ID (삭제 블록은 포함하지 않음)
  removed_block_ids?: string[];      // 추가: 삭제된 블록 ID 목록
  source_metadata: { ... };
  chunking_config: ChunkingConfig;
}
```

**시나리오별 처리 규칙:**

| 시나리오 | `changed_block_ids` | `removed_block_ids` | retrieval-service 처리 |
|---------|---------------------|--------------------|-----------------------|
| 블록 B 수정 | `["B"]` | — | B를 포함하는 청크만 재생성 |
| 블록 B 삭제 | — | `["B"]` | B를 포함하는 청크 삭제, 인접 블록 청크 재생성 |
| 블록 E 추가 | `["E"]` | — | E에서 새 청크 생성, 인접 블록 그룹 재계산 |
| 순서만 변경 | — | — | 블록 그룹 재계산 필요 시 전체 re-embed |

**대안: 전체 재임베딩 위임 (단순화)**

블록 삭제·추가·순서 변경이 수반되면 re-embed 대신 **embed(전체)를 재실행**하는 전략도 유효하다:

```typescript
// EmbeddingProcessor 판단 로직
const hasStructuralChange = 
  newBlockIds.length !== oldBlockIds.length ||
  !arraysEqual(newBlockIds, oldBlockIds);

if (hasStructuralChange) {
  // 구조 변경(블록 추가/삭제/순서변경) → 전체 재임베딩
  // 기존 청크 전체 삭제 후 새로 embed
  await retrievalClient.deleteSource(sourceId);
  await embeddingQueue.add('embed', { source_id: sourceId, blocks: allBlocks });
} else {
  // 내용 변경만 → 부분 재임베딩
  await embeddingQueue.add('re-embed', { 
    source_id: sourceId, 
    blocks: allBlocks, 
    changed_block_ids: modifiedBlockIds 
  });
}
```

### 결론

**구조 변경(추가/삭제/순서변경)은 전체 재임베딩, 내용 변경만은 부분 재임베딩**으로 이원화하는 것을 권장한다. `removed_block_ids` 필드를 추가하는 방안은 retrieval-service의 부분 삭제 로직이 복잡해지므로, 구조 변경 시에는 delete → embed 순서로 처리하는 것이 단순하고 안전하다. 빈도를 고려하면 블록 추가/삭제는 일반 수정 대비 드문 케이스이므로 전체 재임베딩의 비용이 수용 가능하다.

---

## EC-05: 임베딩 대상 블록 0개인 문서 — `권장안 채택 → 연동 문서 반영 완료`

### 문제

다음 조건에서 `blocks` 배열이 빈 상태로 `POST /ingest/embed`를 호출해야 하는지 불명확하다:
- 문서의 모든 블록이 `file` 타입
- `image`/`table` 블록만 있는데 모두 `caption`이 없음
- `Block.embeddable = false`인 블록만 존재

### 권장 방안

**aicm-service에서 사전 판별하여 호출 자체를 스킵:**

```typescript
// EmbeddingProcessor
async processEmbed(document: Document): Promise<void> {
  const embeddableBlocks = document.blocks.filter(b => 
    b.embeddable && this.hasEmbeddableContent(b)
  );

  if (embeddableBlocks.length === 0) {
    // retrieval-service 호출 없이 상태만 갱신
    await this.documentRepository.updateEmbeddingStatus(
      document.id, 
      'skipped',       // embedding_status = 'skipped'
    );
    this.logger.info(`Document ${document.id}: no embeddable blocks, skipped`);
    return;
  }

  // 정상 임베딩 진행...
}

private hasEmbeddableContent(block: Block): boolean {
  switch (block.block_type) {
    case 'text':
    case 'code':
      return !!block.content_text?.trim();
    case 'image':
    case 'table':
      return !!block.caption?.trim();
    case 'file':
      return false;
    default:
      return false;
  }
}
```

**상태 전이:**

| 조건 | embedding_status | 비고 |
|------|-----------------|------|
| embeddable 블록 0개 | `skipped` | retrieval-service 미호출 |
| embeddable 블록 > 0, 전부 성공 | `completed` | 정상 |
| embeddable 블록 > 0, 일부 실패 | `partial` | failed_blocks 존재 |
| 이전 `completed`였다가 수정 후 embeddable 0개 | `skipped` | 기존 청크 삭제 필요 (아래 참조) |

**주의 — 기존 청크 정리:**

기존에 `completed`/`partial` 상태로 청크가 존재하던 문서가 수정 후 embeddable 블록이 0개가 되면, 단순히 `skipped`로 변경하면 안 된다. **기존 청크를 먼저 삭제**해야 한다:

```typescript
if (embeddableBlocks.length === 0 && document.embedding_status !== 'skipped') {
  // 기존 청크가 있을 수 있으므로 삭제 후 skipped
  await retrievalClient.deleteSource(document.id);
  await chunkRepository.deleteByDocumentId(document.id);
  await documentRepository.updateEmbeddingStatus(document.id, 'skipped');
}
```

### 결론

`blocks` 배열이 비어 있는 상태에서 retrieval-service를 호출하지 않도록 aicm-service에서 사전 필터링한다. `embedding_status = 'skipped'`를 활용하되, 기존 청크가 있던 문서의 상태 전이 시 삭제를 선행한다.

---

## EC-06: 에러 응답 공통 구조 부재 — `권장안 채택 → 연동 문서 반영 완료`

### 문제

성공 응답은 잘 정의되어 있지만, 4xx/5xx 에러 시 반환되는 응답 바디 구조가 없다. aicm-service에서 에러를 파싱하여 적절한 fallback이나 로깅을 수행하려면 에러 구조가 필요하다.

### 권장 방안

**retrieval-service 에러 응답 공통 구조 정의:**

```typescript
interface RetrievalServiceError {
  error: {
    code: string;           // 에러 코드 (예: 'INVALID_REQUEST', 'SOURCE_NOT_FOUND')
    message: string;        // 사람이 읽을 수 있는 에러 메시지
    details?: Record<string, any>;   // 추가 컨텍스트 (선택)
  };
  request_id?: string;      // 요청 추적용 (EC-02에서 추가한 request_id 또는 서버 생성)
}
```

**에러 코드 매핑 테이블:**

| HTTP 상태 | 에러 코드 | 설명 | aicm-service 매핑 |
|:---------:|----------|------|-------------------|
| `400` | `INVALID_REQUEST` | 요청 파라미터 오류 | 로깅 + Job 실패 (재시도 불필요) |
| `400` | `BATCH_LIMIT_EXCEEDED` | source_ids > 100건 | 분할 재호출 |
| `404` | `SOURCE_NOT_FOUND` | 해당 source_id 미존재 | 정상 처리 (이미 삭제됨) |
| `409` | `CONCURRENT_OPERATION` | 같은 source에 대한 동시 작업 | 지수 백오프 재시도 |
| `422` | `EMPTY_BLOCKS` | blocks 배열이 비어 있음 | EC-05 사전 필터링 미적용 시 |
| `429` | `RATE_LIMITED` | 요청 제한 초과 | 지수 백오프 재시도 |
| `500` | `INTERNAL_ERROR` | 서버 내부 오류 | 재시도 대상 |
| `503` | `SERVICE_UNAVAILABLE` | 하위 인프라 비가용 | Circuit Breaker 반영 |

**aicm-service 에러 핸들링 매핑:**

```typescript
// RetrievalServiceClient — 공통 에러 핸들러
private handleError(error: AxiosError<RetrievalServiceError>): void {
  const code = error.response?.data?.error?.code;
  
  switch (code) {
    case 'INVALID_REQUEST':
    case 'EMPTY_BLOCKS':
      // 재시도 불필요 — 즉시 실패
      throw new NonRetryableError(code, error.response?.data?.error?.message);
    
    case 'CONCURRENT_OPERATION':
    case 'RATE_LIMITED':
    case 'INTERNAL_ERROR':
    case 'SERVICE_UNAVAILABLE':
      // 재시도 대상
      throw new RetryableError(code, error.response?.data?.error?.message);
    
    case 'SOURCE_NOT_FOUND':
      // 삭제/메타갱신 시 정상 — 이미 삭제된 상태
      this.logger.info(`Source not found, treating as success: ${code}`);
      return;
    
    default:
      throw new RetryableError('UNKNOWN', error.message);
  }
}
```

### 결론

에러 응답 공통 구조와 에러 코드 체계를 API 스펙에 추가하고, aicm-service의 `RetrievalServiceClient`에서 에러 코드별 재시도 여부를 판별하는 핸들러를 구현한다.

---

## EC-07: is_suspended 갱신 지연으로 인한 검색 노출 — `보류`

> 갱신 지연 수준이 무시 가능하므로 별도 대응하지 않음.

### 문제

`document.suspended` 이벤트 발생 → `PATCH /sources/{sourceId}/metadata`로 `is_suspended=true` 갱신까지 시간차가 존재한다. 그 사이 검색 요청이 오면 suspended 문서의 청크가 반환될 수 있다.

```
T1: document.suspended 이벤트 발행
T2: 검색 요청 도착 — retrieval-service의 is_suspended는 아직 false
    → suspended 문서의 청크가 검색 결과에 포함됨
T3: PATCH /metadata로 is_suspended=true 갱신 완료
```

### 권장 방안

**이중 필터 전략 — aicm-service에서 RDB 기반 추가 필터링:**

```typescript
// SearchService (aicm-service)
async search(query: string, userId: string): Promise<SearchResult[]> {
  // 1단계: retrieval-service에서 시맨틱/하이브리드 검색 (메타데이터 필터 포함)
  const rawResults = await retrievalClient.search({
    query,
    mode: 'hybrid',
    filters: await this.buildPermissionFilters(userId),
  });

  // 2단계: RDB에서 최신 상태를 확인하여 추가 필터링 (안전망)
  const documentIds = [...new Set(rawResults.results.map(r => r.source_id))];
  const activeDocuments = await this.documentRepository.findActiveByIds(documentIds);
  // is_suspended=false, is_deleted=false인 문서만 통과
  const activeDocumentIds = new Set(activeDocuments.map(d => d.id));

  return rawResults.results.filter(r => activeDocumentIds.has(r.source_id));
}
```

- retrieval-service의 메타데이터 필터는 **1차 필터** (대부분 걸러냄)
- aicm-service의 RDB 조회는 **2차 안전망** (갱신 지연 보정)
- RDB는 이벤트 처리와 동일 트랜잭션에서 `is_suspended`가 업데이트되므로 최신 상태가 보장됨

**메타데이터 갱신 우선순위 강화:**

```typescript
// is_suspended 갱신은 일반 메타데이터 갱신보다 높은 우선순위
await metadataQueue.add('update-metadata', payload, {
  priority: payload.is_suspended !== undefined ? 1 : 5,
  // 또는 동기 호출로 이벤트 핸들러에서 즉시 처리
});
```

### 결론

**이중 필터 전략**을 권장한다. 완전한 실시간 일관성은 분산 시스템에서 보장이 어렵고, 비용이 크다. RDB 기반 2차 필터는 가볍고(document_id IN 쿼리) 확실한 안전망을 제공한다. 메타데이터 갱신의 우선순위 강화는 보조 수단으로 병행한다.

---

## EC-08: 메타데이터 갱신과 재임베딩 동시 실행 — `권장안 채택 → 연동 문서 반영 완료`

### 문제

`PATCH /metadata`로 `is_suspended=true` 갱신과 `POST /ingest/re-embed`가 동시에 수행되면, re-embed가 삽입하는 새 청크의 메타데이터가 갱신 이전 값을 가질 수 있다.

### 권장 방안

**re-embed 응답 처리 시 최신 메타데이터를 Milvus에 반영:**

re-embed는 source_metadata를 요청에 포함하므로, **aicm-service가 re-embed 요청을 구성하는 시점에 최신 Document 상태를 조회**하면 자연스럽게 해결된다:

```typescript
// EmbeddingProcessor — re-embed Job 실행 시
async processReEmbed(jobData: ReEmbedJobData): Promise<void> {
  // Job 데이터의 스냅샷이 아닌, 실행 시점의 최신 상태를 조회
  const document = await this.documentRepository.findById(jobData.source_id);
  
  const request: IngestReEmbedRequest = {
    source_id: document.id,
    blocks: this.buildBlocks(document),
    changed_block_ids: jobData.changed_block_ids,
    source_metadata: {
      board_id: document.board_id,           // 최신 값
      tags: document.tags,                    // 최신 값
      is_suspended: document.is_suspended,    // 최신 값
      content_hash: this.computeContentHash(document.blocks),
    },
    chunking_config: await this.getChunkingConfig(document.board_id),
  };
  
  await this.retrievalClient.reEmbed(request);
}
```

- BullMQ Job data에는 최소 정보(`source_id`, `changed_block_ids`)만 담고, **실행 시점에 DB에서 최신 상태를 다시 조회**
- 이렇게 하면 Job 등록 ~ 실행 사이에 메타데이터가 변경되어도 최신 값이 반영됨

### 결론

Job data에 스냅샷을 저장하지 말고, 실행 시점에 최신 Document를 조회하여 `source_metadata`를 구성한다. 이는 메타데이터 갱신 경합뿐 아니라, Job이 큐에서 오래 대기하는 경우에도 유효하다.

---

## EC-09: 존재하지 않는 source_id 삭제 — `권장안 채택 → 연동 문서 반영 완료`

### 문제

`DELETE /sources/{sourceId}`에 이미 삭제된 source_id 또는 한 번도 임베딩되지 않은 source_id를 전달했을 때의 응답이 정의되지 않았다.

### 권장 방안

**멱등성 원칙에 따라 200 + `deleted_chunk_count: 0` 반환:**

```typescript
// retrieval-service 응답
// 존재하지 않는 source_id에 대해:
{
  "source_id": "non-existent-id",
  "deleted_chunk_count": 0        // 삭제된 것이 없음
}
// HTTP 200 — 404를 반환하지 않음
```

- API 메트릭스 테이블에서 멱등성 ✓로 표기되어 있으므로, 이 동작이 자연스러움
- aicm-service에서 "문서 삭제 → 임베딩 삭제"를 수행할 때, embedding_status가 `pending`/`skipped`인 문서도 안전하게 삭제 호출 가능
- 별도 존재 여부 확인 API 호출이 불필요해져 로직이 단순해짐

**API 스펙 보완 문구:**

> 해당 `sourceId`에 대한 청크가 존재하지 않는 경우(미임베딩 또는 이미 삭제) `200`과 `deleted_chunk_count: 0`을 반환한다. 멱등성을 보장하여 동일 요청의 중복 전송이 안전하다.

### 결론

`DELETE /sources/{sourceId}` API 스펙에 "존재하지 않으면 200 + count 0" 동작을 명시한다. 배치 `DELETE /sources`에서도 동일 원칙 적용 — 존재하지 않는 source_id는 성공 처리에 포함하되 `deleted_chunk_count`에 기여하지 않음.

---

## EC-10: PUT /config 유효성 검증 — `보류`

### 문제

검색 설정 push 시 값의 범위 제약이 정의되지 않아, 잘못된 설정이 적용될 수 있다.

### 권장 방안

**retrieval-service 입력 검증 규칙:**

| 필드 | 타입 | 제약 | 위반 시 |
|------|------|------|--------|
| `hybrid_weight_bm25` | number | `0.0 ≤ x ≤ 1.0` | `400 INVALID_REQUEST` |
| `hybrid_weight_vector` | number | `0.0 ≤ x ≤ 1.0` | `400 INVALID_REQUEST` |
| `hybrid_weight_bm25 + hybrid_weight_vector` | — | `== 1.0` (±0.001 허용) | `400 INVALID_REQUEST` |
| `rrf_k` | number | `1 ≤ x ≤ 100`, 정수 | `400 INVALID_REQUEST` |
| `top_k` | number | `1 ≤ x ≤ 200`, 정수 | `400 INVALID_REQUEST` |
| `similarity_threshold` | number | `0.0 ≤ x ≤ 1.0` | `400 INVALID_REQUEST` |
| `window_context_size` | number | `0 ≤ x ≤ 10`, 정수 | `400 INVALID_REQUEST` |
| `reranking_enabled` | boolean | — | — |
| `reranking_model` | string\|null | `reranking_enabled=true`이면 필수 | `400 INVALID_REQUEST` |
| `reranking_top_n` | number\|null | `reranking_enabled=true`이면 `1 ≤ x ≤ top_k` | `400 INVALID_REQUEST` |

**aicm-service 사전 검증 (방어적 프로그래밍):**

```typescript
// ConfigService — SearchConfig 변경 시
validateRetrievalConfig(config: UpdateRetrievalConfigRequest): void {
  const errors: string[] = [];
  
  if (config.hybrid_weight_bm25 + config.hybrid_weight_vector < 0.999 ||
      config.hybrid_weight_bm25 + config.hybrid_weight_vector > 1.001) {
    errors.push('hybrid weights must sum to 1.0');
  }
  
  if (config.reranking_enabled && !config.reranking_model) {
    errors.push('reranking_model is required when reranking is enabled');
  }
  
  if (config.reranking_top_n != null && config.reranking_top_n > config.top_k) {
    errors.push('reranking_top_n must not exceed top_k');
  }
  
  if (errors.length > 0) {
    throw new ValidationError('Invalid retrieval config', errors);
  }
}
```

### 결론

검증 규칙을 API 스펙에 명시하고, **양단 검증(aicm-service + retrieval-service 모두)**을 적용한다. aicm-service는 사용자 입력 시점에 검증하여 빠른 피드백을, retrieval-service는 방어적으로 재검증하여 잘못된 설정 적용을 원천 차단한다.

---

## EC-11: hybrid 모드 + ES disconnected

### 문제

하이브리드 검색(`mode: 'hybrid'`)은 Milvus(벡터) + ES(BM25)를 모두 필요로 한다. 헬스체크 `status: 'degraded'`(ES disconnected)일 때 하이브리드 검색 요청의 처리 방식이 정의되지 않았다.

### 권장 방안

**retrieval-service 내부 graceful degradation:**

```
요청: mode=hybrid, ES disconnected
  → 벡터 검색(Milvus)만 수행 (BM25 파트 생략)
  → 응답 metadata.mode = 'semantic' (실제 실행된 모드)
  → 응답 헤더 또는 metadata에 degradation 표시

요청: mode=semantic, ES disconnected
  → 정상 수행 (Milvus만 사용)

요청: mode=hybrid, Milvus disconnected
  → 500 에러 반환 (핵심 인프라 불가)
  → aicm-service Circuit Breaker → 키워드 검색 fallback
```

**aicm-service 검색 결과 표시:**

```typescript
// SearchService
const response = await retrievalClient.search(request);

if (response.metadata?.mode !== request.mode) {
  // 요청한 모드와 실행된 모드가 다르면 degradation 발생
  this.logger.warn(`Search degradation: requested=${request.mode}, actual=${response.metadata.mode}`);
  // UX: 검색 결과에 degradation 안내 포함
}
```

**API 스펙 보완 — SearchResponse.metadata 확장:**

```typescript
interface SearchResponseMetadata {
  mode: 'semantic' | 'hybrid';        // 실제 실행된 모드 (요청과 다를 수 있음)
  reranked: boolean;
  total_candidates: number;
  degraded?: boolean;                  // 추가: degradation 발생 여부
  degradation_reason?: string;         // 추가: 예 'elasticsearch_unavailable'
}
```

### 결론

retrieval-service가 자체적으로 검색 모드를 fallback하고, 응답의 `metadata.mode`에 실제 실행된 모드를 반환한다. aicm-service는 요청 모드와 응답 모드를 비교하여 degradation을 감지하고 사용자에게 안내한다.

---

## EC-12: 검색 결과 0건 처리

### 문제

검색 결과가 없을 때의 정상 응답 형태와, "결과 없음"이 fallback 트리거 조건인지 여부가 명확하지 않다.

### 권장 방안

**"결과 0건"은 정상 응답이다:**

```typescript
// 정상 응답 — 매칭 결과 없음
{
  "results": [],
  "metadata": {
    "mode": "hybrid",
    "reranked": false,
    "total_candidates": 0
  }
}
// HTTP 200 — 빈 결과는 에러가 아님
```

**aicm-service 분기 로직:**

```typescript
// RagSearchService
const semanticResults = await retrievalClient.search(request);

if (semanticResults.results.length === 0) {
  // 시맨틱/하이브리드 결과 0건 → 키워드 검색으로 보완 (NOT fallback)
  // 이는 Circuit Breaker/장애와 무관한 정상 분기
  const keywordResults = await this.keywordSearch(query, filters);
  return this.mergeResults([], keywordResults, 'keyword_supplement');
}

return this.enrichResults(semanticResults.results);
```

**"결과 0건"과 "장애 fallback"의 구분:**

| 상황 | HTTP 상태 | results | 처리 |
|------|:---------:|---------|------|
| 정상이지만 매칭 없음 | `200` | `[]` | 키워드 보완 검색 (선택) |
| retrieval-service 장애 | `5xx` 또는 타임아웃 | — | Circuit Breaker → 키워드 fallback |
| threshold 미달로 전부 필터링됨 | `200` | `[]` | threshold 완화 후 재검색 (선택) |

### 결론

빈 결과는 `200 + results: []`로 정상 반환한다. 키워드 보완 검색은 UX 향상 목적의 **선택적 보완**이며, 장애 시의 fallback과 구분한다. API 스펙에 "결과 없음 시 200 + 빈 배열"을 명시한다.

---

## 종합 — 연동 문서 반영 권장 사항

위 엣지케이스 분석 결과, `retrieval-service-integration.md` 및 `retrieval-service-api-spec.md`에 반영이 필요한 항목:

### API 스펙 변경

| 변경 | 대상 | 관련 EC |
|------|------|---------|
| `IngestEmbedRequest`에 `request_id` 필드 추가 | API 스펙 | EC-02 |
| 에러 응답 공통 구조 (`RetrievalServiceError`) 추가 | API 스펙 | EC-06 |
| `SearchResponse.metadata`에 `degraded`, `degradation_reason` 추가 | API 스펙 | EC-11 |
| `DELETE /sources/{sourceId}` — 미존재 시 200 + count 0 명시 | API 스펙 | EC-09 |
| `PUT /config` 필드별 유효성 제약 명시 | API 스펙 | EC-10 |

### 연동 문서 추가 섹션

| 섹션 | 내용 | 관련 EC |
|------|------|---------|
| 동시성 제어 전략 | source_id 단위 Job 직렬화 (BullMQ group concurrency) | EC-01, EC-08 |
| 배치 분할 실패 처리 | Child Job 부분 실패 시 상태 전이 규칙 | EC-03 |
| 블록 구조 변경 판별 | 추가/삭제/순서변경 시 전체 재임베딩 분기 | EC-04 |
| 빈 블록 문서 처리 | embeddable 블록 0개 시 스킵 로직 | EC-05 |
| 검색 결과 후처리 | RDB 기반 2차 필터, degradation 감지 | EC-07, EC-11, EC-12 |

---

## 관련 문서

- [retrieval-service 연동](./6-3-retrieval-service-integration.md) — 원문
- [retrieval-service API 스펙](./specs/retrieval-service-api-spec.md) — API 상세
- [비동기 처리 아키텍처](../05-async-event-architecture.md) — BullMQ 정책
- [FD-EMB 임베딩파이프라인](../../01-requirements/features/FD-EMB-임베딩파이프라인.md) — 비즈니스 규칙
