# Controlled-device Protocol

## 1. 목적
통제된 조건에서 실제 스마트폰 녹음 파일을 수집하고, 정렬/드리프트 보정/믹스/STT 품질을 검증한다.

## 2. 공통 조건
- same app version
- same room
- same research mode baseline
- built-in mic only
- start anchor
- end anchor
- pause/resume 금지

## 3. Scenario CD-1
### 조건
- 3명
- 10분
- same app
- start + end anchor

### 목적
- room/join/ready/start/upload/process 흐름 검증
- baseline controlled-device 성공

### 성공 기준
- 모든 파일 업로드 성공
- processing 성공
- artifacts 생성
- metadata 누락 없음

## 4. Scenario CD-2
### 조건
- 5명
- 10분
- start + end anchor

### 목적
- 5인원 환경에서 offset/drift sanity 확인

### 성공 기준
- 5개 track alignment
- mix/export 성공
- obvious sync failure 없음

## 5. Scenario CD-3
### 조건
- 5명
- 1시간
- start anchor mandatory
- end anchor strongly recommended

### 목적
- 장시간 drift 검증
- AC1 evidence 확보

### 성공 기준
- 5명 / 1시간 evidence bundle 생성
- drift summary 생성
- runtime/memory 기록 확보

## 6. 수집 항목
- raw audio files
- metadata JSON
- room/session logs
- processing logs
- manifest.json
- manifest.export.json
- aligned_tracks.zip
- listening_mix.wav
- operator notes
- listening review packet

## 7. 평가 지표
- alignment confidence
- estimated drift ppm
- loudness spread
- clipped samples
- STT 결과
- listening review
