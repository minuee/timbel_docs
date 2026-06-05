> **문서 상태**
> | 항목 | 값 |
> |------|-----|
> | 상태 | `draft` |
> | 검수 | `unreviewed` |
> | 작성일 | 2026-03-26 |
> | 최종 수정 | 2026-03-26 |

# 집계 및 피드 흐름

## 1. 범위

홈 대시보드 위젯 데이터 수집, 인기·트렌딩 문서 계산, 피드 구독 갱신의 흐름을 다룬다.

## 2. 기능정의서 참조

- [FD-AGG](../../features/FD-AGG-집계피드.md) §1: 문서 집계 데이터
- [FD-AGG](../../features/FD-AGG-집계피드.md) §2: 피드 및 구독
- [FD-AGG](../../features/FD-AGG-집계피드.md) §3: 홈 대시보드 위젯

## 3. 집계 파이프라인 조감도

```mermaid
flowchart TD
  subgraph 이벤트_소스["이벤트 소스"]
    document_published["document.published"]
    document_viewed["document.viewed"]
    comment_created["comment.created"]
    like_toggled["like.toggled"]
  end

  이벤트_소스 --> EventBus["EventBus"]
  EventBus --> AggregationModule["AggregationModule"]

  subgraph 실시간_개인["실시간 데이터 (개인)"]
    draft["드래프트"]
    pending["승인대기"]
    recent["최근열람"]
    db_direct["DB 직접 조회"]
    draft --> db_direct
    pending --> db_direct
    recent --> db_direct
  end

  subgraph 배치_공용["배치 데이터 (공용)"]
    popular["인기문서"]
    trending["트렌딩"]
    stats["통계"]
    bullmq["BullMQ 배치 Job"]
    redis_cache["Redis 캐시"]
    popular --> bullmq
    trending --> bullmq
    stats --> bullmq
    bullmq --> redis_cache
  end

  AggregationModule --> 실시간_개인
  AggregationModule --> 배치_공용

  widget_api["위젯 API"]
  widget_api --> redis_cache
  widget_api --> db_direct
```

## 4. 인기·트렌딩 문서 계산 흐름

```mermaid
flowchart TD
  scheduler["BullMQ 스케줄러 (1시간 단위)"]

  subgraph 인기_계산["인기 스코어 계산"]
    formula["score = (조회수 × W1) + (좋아요 × W2) + (댓글 × W3)"]
    system_config["가중치 W1~W3: SystemConfig에서 조회"]
    period_filter["기간별 필터 (일간/주간/월간)"]
    popular_zset["Redis sorted set (인기)"]
    scheduler --> formula
    system_config --> formula
    formula --> period_filter
    period_filter --> popular_zset
  end

  subgraph 트렌딩_계산["트렌딩 계산"]
    rate["최근 N시간 조회수 증가율 계산"]
    threshold["임계값 200% 이상"]
    min_views["최소 조회수 10건 필터"]
    trending_zset["Redis sorted set (트렌딩)"]
    scheduler --> rate
    rate --> threshold
    threshold --> min_views
    min_views --> trending_zset
  end
```

## 5. 피드·구독 갱신 흐름

```mermaid
sequenceDiagram
  participant Event as document.published
  participant Agg as AggregationModule
  participant Sub as 구독자 목록
  participant Store as Redis 목록 또는 DB
  participant Ntf as NotificationModule
  participant Client as 클라이언트

  Event->>Agg: 문서 게시 이벤트
  Agg->>Sub: 해당 게시판 구독자 목록 조회
  loop 각 구독자
    Agg->>Store: 구독자 피드에 문서 추가
    Agg->>Ntf: 구독자에게 알림 발송
  end
  Client->>Agg: 사용자 피드 조회 요청
  Agg->>Agg: 권한 필터
  Agg->>Agg: 정렬
  Agg->>Client: 피드 반환
```

## 6. 홈 대시보드 위젯 로딩 흐름

```mermaid
flowchart LR
  login["사용자 로그인"]
  home["홈 요청"]
  layout["위젯 레이아웃 조회 (사용자 개인 설정)"]
  parallel["각 위젯별 데이터 병렬 로딩"]
  personal["개인 데이터 위젯 → DB 직접 조회"]
  aggregate["집계 데이터 위젯 → Redis 캐시 조회"]
  combine["응답 조합"]
  render["렌더링"]

  login --> home
  home --> layout
  layout --> parallel
  parallel --> personal
  parallel --> aggregate
  personal --> combine
  aggregate --> combine
  combine --> render
```

## 7. 관련 문서

| 문서 | 설명 |
|------|------|
| [FD-AGG-집계피드.md](../../features/FD-AGG-집계피드.md) | 집계·피드 기능 정의 |
| [UC-PER-개인영역.md](../../usecases/user/UC-PER-개인영역.md) | UC-PER-05 홈 대시보드 |
| [UC-ADM-시스템운영.md](../../usecases/admin/UC-ADM-시스템운영.md) | UC-ADM-11 통계, UC-ADM-17 위젯 카탈로그 |
| [비동기 이벤트 아키텍처](../../../02-architecture/04-async-event-architecture.md) | 이벤트 버스·비동기 처리 |
| [데이터 아키텍처 — AggregationModule](../../../03-module-design/aggregation/data.md) | RDB 집계 모듈 |
| [데이터 아키텍처 — Redis](../../../02-architecture/data/aicm/redis.md) | Redis 캐시·구조 |
