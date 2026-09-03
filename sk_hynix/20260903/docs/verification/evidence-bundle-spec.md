# Evidence Bundle Spec

## 1. 목적
실험 1회마다 필요한 evidence를 동일한 구조로 저장하기 위한 규격을 정의한다.

## 2. 디렉토리 구조
```text
verification/evidence/<timestamp>/
  room.json
  session.json
  participants.json
  uploads/
  processing.log
  manifest.json
  manifest.export.json
  aligned_tracks.zip
  listening_mix.wav
  benchmark.json
  drift-summary.json
  listening-review.md
  operator-notes.md
  release-checklist.md
```

## 3. 필수 파일
- room.json
- session.json
- processing.log
- manifest.json
- manifest.export.json
- aligned_tracks.zip
- listening_mix.wav
- operator-notes.md

## 4. 권장 파일
- benchmark.json
- drift-summary.json
- listening-review.md
- release-checklist.md

## 5. 규칙
- directory는 UTC timestamp 기준으로 생성
- 동일 세션 결과는 한 directory 안에 저장
- raw outputs와 summary를 함께 저장
- file naming은 deterministic해야 함

## 6. 목적
- synthetic / controlled-device / field validation 결과를 같은 구조로 비교 가능하게 한다.
