# Upload Contract

## 1. 목적
오디오 파일과 metadata를 함께 session에 업로드하기 위한 계약을 정의한다.

## 2. 방식
- `multipart/form-data`

## 3. 필드
- `audio_file` — binary
- `metadata` — JSON string
- `participant_id`
- `device_id`

## 4. metadata 핵심 항목
- session_id
- room_id
- participant_id
- device_id
- recording_started_at
- recording_stopped_at
- start_command_received_at
- local_monotonic_start_tick
- sample_rate
- channels
- codec
- duration_seconds
- mic_route
- anchor_type
- audio_processing_flags
- pause_resume_events

## 5. 서버 검증
### Research Mode
- WAV / PCM / 48kHz / mono
- built-in mic only
- no pause/resume
- anchor expected

### 공통
- metadata schema valid
- participant/session 매칭 valid
- 파일 무결성 basic check

## 6. 성공 응답 예시
```json
{
  "ok": true,
  "data": {
    "file_id": "file_abc",
    "session_id": "session_123",
    "participant_id": "p_02",
    "status": "uploaded",
    "uploaded_at": "2026-04-09T11:05:18Z"
  },
  "error": null
}
```

## 7. 실패 응답 예시
```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "unsupported_route",
    "message": "Bluetooth microphone is not allowed in research mode"
  }
}
```
