# Metadata Schema

## 목적
녹음 앱이 생성한 오디오 파일과 함께 서버로 업로드해야 하는 메타데이터 계약을 정의한다.

## 원칙
1. metadata는 prior이고 최종 truth는 오디오가 결정한다.
2. capture 조건을 설명할 수 있어야 한다.
3. 연구 모드에서는 강한 제약을 검증 가능하게 해야 한다.
4. 앱 raw fields와 서버 derived fields를 분리한다.

## Required Fields
### Identity
- session_id
- room_id
- participant_id
- device_id

### Platform
- platform.os_type
- platform.os_version
- platform.app_version

### Recording
- recording.filename
- recording.container
- recording.codec
- recording.sample_rate
- recording.channels
- recording.duration_seconds

### Timing
- timing.recording_started_at
- timing.recording_stopped_at

### Audio Route
- audio_route.mic_route

### Audio Processing
- audio_processing_flags.agc
- audio_processing_flags.noise_suppression
- audio_processing_flags.echo_cancellation

### Session Events
- session_events.pause_resume_events

## Strongly Recommended Fields
- timing.start_command_received_at
- timing.local_monotonic_start_tick_ms
- timing.local_monotonic_stop_tick_ms
- anchor.anchor_type
- anchor.anchor_expected
- audio_route.bluetooth_connected
- audio_route.wired_headset_connected
- session_events.route_change_events
- session_events.interruption_events
- upload.upload_started_at
- upload.upload_finished_at
- upload.retry_count

## Derived Server Fields
- estimated_offset_seconds
- estimated_drift_ppm
- correction_factor
- alignment_confidence
- loudness_dbfs
- active_speech_lufs
- clipped_samples

## Research Mode Validation
Pass 조건:
- WAV
- PCM
- 48kHz
- mono
- built_in_mic
- no pause/resume
- anchor expected

차단 또는 degraded 조건:
- bluetooth mic
- unsupported format
- pause/resume present
- missing anchor
- missing required metadata
