# Recording Policy

## 목적
연구 모드와 파일럿 모드에서 어떤 조건으로 녹음을 허용할지 정의한다.

## Research Mode Baseline
- format: WAV
- codec: PCM
- sample rate: 48kHz
- channels: mono
- mic route: built-in mic only
- pause/resume: not allowed
- anchor: required

## Pilot Mode
- 일부 포맷 허용 가능
- anchor optional
- route mismatch는 warning
- metadata는 계속 기록

## Blocking Conditions
- bluetooth mic 사용
- unsupported baseline format
- pause/resume 발생
- required anchor missing
- microphone permission 없음
- storage 부족

## Warning Conditions
- route changed
- unknown audio processing flags
- interruption detected
- weak anchor

## 서버 재검증
앱이 정책을 강제하더라도 서버는 아래를 다시 검사한다.
- format
- codec
- sample_rate
- channels
- mic_route
- pause_resume_events
- anchor_expected

## 목적
연구 단계에서는 재현 가능한 실험 조건을 보장하고, 파일럿 단계에서는 제약 완화에 따른 품질 저하를 측정한다.
