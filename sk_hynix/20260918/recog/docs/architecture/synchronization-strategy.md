# Synchronization Strategy

## 1. 목적
여러 기기에서 녹음된 파일을 어떻게 정렬할지 전략을 정의한다.

## 2. 핵심 원칙
Metadata는 prior이고, 오디오는 final truth다.

## 3. 동기화 순서
1. server authoritative start
2. metadata prior (`recording_started_at`, `start_command_received_at`)
3. anchor detection
4. audio fine alignment
5. drift correction

## 4. 왜 metadata만으로 부족한가
- 네트워크 지연
- OS 오디오 스택 지연
- 앱 내부 녹음 start latency
- 기기별 편차

## 5. 왜 anchor가 필요한가
- acoustic truth 기준점 확보
- start offset sanity
- end drift sanity

## 6. fallback
anchor 검출 실패 시:
- metadata prior + audio-only alignment
- degraded classification

## 7. 연구 baseline
- start beep
- end beep
- built-in mic only
- WAV / PCM / 48kHz / mono
