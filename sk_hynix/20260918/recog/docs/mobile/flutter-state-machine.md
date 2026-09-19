# Flutter State Machine

## 1. 목적
녹음 앱의 상태 전이와 이벤트 흐름을 정의한다.

## 2. 주요 상태
- IDLE
- ROOM_CREATED
- ROOM_JOINED
- WAITING_IN_LOBBY
- READY
- START_PENDING
- PRE_RECORD_CHECK
- ANCHOR_PENDING
- RECORDING
- STOPPING
- STOPPED
- PACKAGING_METADATA
- UPLOADING
- UPLOADED
- DONE

## 3. 에러 상태
- POLICY_BLOCKED
- RECORDING_FAILED
- UPLOAD_FAILED

## 4. 이벤트
### 사용자 이벤트
- create_room
- join_room
- tap_ready
- tap_start
- tap_stop
- retry_upload

### 서버 이벤트
- room_created
- room_joined
- all_ready
- start_command_received
- stop_command_received
- processing_completed

### 디바이스 이벤트
- route_changed
- interruption_detected
- recording_started
- recording_stopped

## 5. 주요 상태 전이
IDLE → ROOM_CREATED / ROOM_JOINED  
ROOM_JOINED → WAITING_IN_LOBBY  
WAITING_IN_LOBBY → READY  
READY → START_PENDING  
START_PENDING → PRE_RECORD_CHECK  
PRE_RECORD_CHECK → ANCHOR_PENDING  
ANCHOR_PENDING → RECORDING  
RECORDING → STOPPING  
STOPPING → STOPPED  
STOPPED → PACKAGING_METADATA  
PACKAGING_METADATA → UPLOADING  
UPLOADING → UPLOADED  
UPLOADED → DONE

## 6. 연구 모드 요구사항
- built-in mic가 아니면 POLICY_BLOCKED
- unsupported format이면 POLICY_BLOCKED
- pause/resume 금지
- anchor required
