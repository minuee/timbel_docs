# Release Gate

## 1. 목적
이 프로젝트가 다음 단계로 넘어가도 되는지 판단하는 기준을 정의한다.

## 2. Gate A — Engineering Ready
### 요구 조건
- room/session 흐름 동작
- synthetic baseline pass
- artifact generation 성공

## 3. Gate B — Research Ready
### 요구 조건
- controlled-device baseline 성공
- evidence bundle 생성 가능
- metadata / anchor / alignment 설명 가능

## 4. Gate C — Pilot Ready
### 요구 조건
- 5명 / 1시간 evidence 확보
- human listening sign-off 확보
- release checklist 완료

## 5. 핵심 blocker
- AC1: 5명 / 1시간 evidence
- AC7: human listening sign-off

## 6. 기준
release-ready는 단순 코드 완료가 아니라, 재현 가능한 evidence와 실제 청취 평가가 있을 때만 성립한다.
