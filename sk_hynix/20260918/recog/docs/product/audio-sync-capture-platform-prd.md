# Audio Sync Capture Platform PRD

## 프로젝트 한 줄 정의
모바일 녹음 앱, 세션 제어 서버, 오디오 처리 엔진을 결합해 다중 스마트폰 회의 녹음을 정렬·보정·믹스하고 STT 품질을 개선하는 플랫폼.

## 문제 정의
중앙 마이크 기반 회의 녹음은 작은 목소리, 먼 거리 발화, overlap 구간에서 STT 누락이 발생한다. 각자 스마트폰으로 녹음하면 자기 음성은 더 잘 잡히지만, 시작 시점 차이, 장시간 drift, 포맷 차이, route 차이, 오디오 처리 차이, mix 품질 문제가 생긴다. 따라서 핵심 문제는 파일을 합치는 것이 아니라 정렬 가능한 입력 조건을 통제하고 설명 가능한 방식으로 후처리하는 것이다.

## 현재 구현과 한계
현재 구현은 backend processing engine 중심이다.
- canonicalization
- alignment / drift correction 일부
- mix / export / manifest
- synthetic verification scaffold

하지만 아래가 부족하다.
- 녹음 앱
- room/session 제어
- metadata contract
- anchor 정책
- controlled-device / field validation evidence

## 목표
같은 세션 규칙 아래 수집된 파일과 metadata를 바탕으로 정렬/드리프트 보정/믹스/STT 품질을 개선한다.

## 시스템 구성
### Mobile Recording App
- room create/join
- ready
- host start
- baseline recorder
- metadata capture
- anchor UX
- upload/retry

### Session / Control Server
- room lifecycle
- readiness tracking
- start / stop control
- metadata persistence
- policy validation

### Processing Engine
- canonicalization
- metadata prior
- anchor detection
- audio fine alignment
- drift correction
- mix/export/manifest

## 비목표
- 실시간 처리
- 화자 분리 / 화자 식별
- 수동 편집 UI
- 영상 동기화

## 연구 baseline
- WAV
- PCM
- 48kHz
- mono
- built-in mic only
- pause/resume 금지
- start anchor mandatory
- end anchor mandatory or strongly recommended

## 로드맵
- Sprint 1: 계약 고정
- Sprint 2: end-to-end MVP
- Sprint 3: controlled-device baseline
- Sprint 4: 5-device / 1-hour
- Sprint 5: field validation / release decision

## Release Gate
- AC1: 5명 / 1시간 evidence
- AC7: human listening sign-off

## 결론
이 프로젝트의 핵심은 아무 녹음 파일을 마법처럼 맞추는 것이 아니라, 앱이 통제한 규칙 아래서 수집된 다중 스마트폰 녹음 파일을 기반으로 재현 가능한 방식으로 STT 품질을 개선하는 플랫폼을 만드는 것이다.
