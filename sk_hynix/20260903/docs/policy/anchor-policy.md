# Anchor Policy

## 목적
다중 기기 녹음 정렬과 드리프트 검증을 위한 acoustic reference 정책을 정의한다.

## 원칙
- server start signal만으로는 acoustic truth를 보장할 수 없다
- anchor는 연구 단계에서 실험 기준점을 만든다
- 최종 정렬은 audio fine alignment가 확정한다

## Start Anchor
### 기본
- short beep

### 목적
- 시작 시점 기준점
- coarse offset correction

### 정책
- Research Mode: mandatory
- Pilot Mode: optional

## End Anchor
### 기본
- short beep

### 목적
- 장시간 drift sanity check
- 종료 기준점

### 정책
- Research Mode: mandatory 또는 strongly recommended
- Pilot Mode: optional

## Periodic Anchor
### 용도
- 장시간 연구용 drift 측정 강화

### 정책
- research-only option
- pilot/service 기본 비활성

## Fallback
anchor 검출 실패 시:
- metadata prior + audio-only alignment fallback
- session / track에 degraded classification 부여

## 추천 baseline
- host start
- 3초 countdown
- start beep
- recording 시작
- end beep
