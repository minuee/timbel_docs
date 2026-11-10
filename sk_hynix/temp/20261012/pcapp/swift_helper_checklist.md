# Swift Helper implementation checklist

## Events (ev)
- [x] version_info
- [x] devices
- [x] helper_info
- [x] output_dir_set
- [x] debug_files_set
- [x] segment_config_set
- [x] test_started
- [x] test_stopped
- [x] recording_started
- [x] paused
- [x] start_test
- [x] stop_test
- [x] resumed
- [x] recording_stopped
- [x] mute_state
- [x] set_mute
- [x] mute_state
- [x] level_meter_state
- [x] level
- [ ] waveform(앱에서 안씀)
- [x] progress
- [x] disk_status
- [x] segment_ready
- [x] device_reconnected
- [x] silence
- [x] error
- [x] mic_state

## Error codes

### 초기화 및 시스템 오류
- [ ] `COM_INIT_FAILED`: COM 초기화 실패 (Windows 전용)
- [x] `ENUMERATOR_FAILED`: 장치 열거자 초기화 실패 (명세에만 존재, macOS에서는 실제로 발생 안 함)
- [x] `MIC_INIT_FAILED`: 마이크 초기화 실패
- [x] `SYS_INIT_FAILED`: 시스템 오디오 초기화 실패
- [x] `START_TEST_ERROR`: 테스트 시작 실패

### 장치 관련 오류
- [ ] `MIC_DEVICE_CHANGED`: 마이크 장치 변경으로 녹음 중단
- [x] `DEVICE_RECONNECT_FAILED`: 장치 재연결 실패
- [x] `MIC_DEVICE_LOST`: 마이크 장치 연결 끊김 (macOS 전용)

### 파일 및 디스크 오류
- [x] `SEGMENT_SAVE_FAILED`: 세그먼트 저장 실패(암호화/쓰기 오류 포함)
- [x] `ENCRYPT_FAILED`: 암호화 실패로 세그먼트 저장 불가
- [x] `DISK_SPACE_CRITICAL`: 디스크 여유 공간 50MB 미만(세그먼트 경계에서 중지 예약)
- [x] `DISK_SPACE_LOW_STOP`: 디스크 여유 공간 부족으로 안전 중지
- [x] `DISK_WRITE_OPEN_FAILED`: 세그먼트 파일 열기 실패(쓰기 불가)

### 명령 처리 오류
- [x] `JSON_PARSE_ERROR`: JSON 파싱 오류
- [x] `UNKNOWN_COMMAND`: 알 수 없는 명령
- [x] `COMMAND_ERROR`: 명령 처리 오류
- [x] `BAD_PARAM`: 잘못된 파라미터
- [x] `NOT_IMPLEMENTED`: 미구현 기능 호출

### 설정 관련 오류
- [x] `GET_VERSION_ERROR`: 버전 정보 조회 오류
- [x] `SET_OUTPUT_DIR_ERROR`: 출력 디렉터리 설정 오류
- [x] `SET_DEBUG_FILES_ERROR`: 디버그 파일 설정 오류 (명세에만 존재, macOS에서는 실제로 발생 안 함)
- [x] `SET_SEGMENT_CONFIG_ERROR`: 세그먼트 설정 오류
- [x] `SET_MUTE_ERROR`: 음소거 설정 오류
- [x] `SET_LEVEL_METER_ERROR`: 레벨미터 설정 오류

## Notes
- Keep event payloads aligned with `docs/electron_helper_interface.md`.
- All events must use the `ev` key, not `type`.
- Update this file as new events/errors are introduced.

## Payload schema checks (must match helper_interface)
- devices: `{ ev, devices:[{ id, name, isDefault }], renderDevices? }`
- paused: `{ ev }`
- resumed: `{ ev }`
- recording_stopped: `{ ev, totalSamples, micSamplesWritten, sysSamplesWritten }`
- progress: `{ ev, seconds, samples, mic_samples, mic_seconds }`
- segment_ready: `{ ev, index, path, samples, duration_ms, size_bytes, encrypted }`
- device_reconnected: `{ ev, type, aec_reset? }` (macOS는 `type:"mic"` 사용, aec_reset 생략 가능)
- error: `{ ev, code, message }`
 - mic_state: `{ ev, state }`
 - version_info: `{ ev, version, version_full, product_name, description, webrtc_aec, noise_suppression, gain_control, build_date, build_time, copyright }`
 - level_meter_state: `{ ev, enabled }`
 - mute_state: `{ ev, mic, system }`
