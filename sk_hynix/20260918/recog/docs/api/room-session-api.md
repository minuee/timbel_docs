# Room / Session API

## 목적
같은 회의 참여자를 room으로 묶고, ready/start/stop 흐름을 제어하며, file+metadata upload와 processing까지 연결하는 control plane / upload plane API를 정의한다.

## 공통 응답 형식
### Success
```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

### Failure
```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "policy_blocked",
    "message": "Bluetooth microphone is not allowed in research mode"
  }
}
```

## Room은 control plane / Session은 processing plane
- Room: participant / ready / start / stop 관리
- Session: 업로드 파일 / 처리 / 결과물 관리

## Room APIs
- POST /rooms
- GET /rooms/{room_id}
- POST /rooms/{room_id}/join
- POST /rooms/{room_id}/ready
- POST /rooms/{room_id}/start
- POST /rooms/{room_id}/stop

## Session APIs
- POST /sessions/{session_id}/files
- POST /sessions/{session_id}/process
- GET /sessions/{session_id}
- GET /sessions/{session_id}/artifacts
- POST /sessions/{session_id}/close
- GET /sessions/{session_id}/artifacts/{kind}

### POST /sessions/{session_id}/close
세션 사용 종료를 선언하고 작업용 파일을 정리한다. 상태머신 `open → closing → closed`.

**Request body**
```json
{ "join_code": "ABCDEF" }
```

**Behavior**
- `join_code` 미일치 → `403 Forbidden`
- `join_code` 누락 → `400 Bad Request`
- 이미 `closed` 상태 → `200 OK` (멱등, 기존 페이로드 반환)
- 정상 처리: `state=closing` 먼저 영속화(fsync+os.replace) → artifacts를 `archive/sessions/{id}/artifacts/`로 이동, `work/`·`canonical/`·`aligned/`·`uploads/` 제거 → `state=closed` 영속화
- 파일 I/O 실패 시 `state=closing` 유지 + `500 Internal Server Error`. 호스트 cron이 재조정

**Success (200)**
```json
{
  "session_id": "...",
  "state": "closed",
  "closed_at": "2026-04-21T09:30:00Z",
  "archive_dir": "/var/lib/recog/runtime/archive/sessions/<id>"
}
```

### GET /sessions/{session_id}/artifacts/{kind}
아티팩트 파일을 스트리밍 전송한다. `HEAD` 지원, HTTP Range 지원 (단일 범위).

**Supported kinds**
| kind | filename | Content-Type |
|---|---|---|
| `listening_mix` | `listening_mix.wav` | `audio/wav` |
| `aligned_tracks` | `aligned_tracks.zip` | `application/zip` |
| `manifest` | `manifest.json` | `application/json` |
| `manifest_export` | `manifest.export.json` | `application/json` |

**Query**
- `token` (필수) — 세션의 `join_code` 값과 일치해야 함

**Headers (response)**
- `Content-Type`, `Content-Length`, `Accept-Ranges: bytes`, `ETag` (weak, `W/"<size>-<mtime_ns>"`)
- 부분 응답 시 `Content-Range: bytes START-END/TOTAL`

**Status codes**
- `200 OK` — 전체 GET / HEAD
- `206 Partial Content` — 유효한 Range GET
- `403 Forbidden` — token 누락 또는 불일치
- `404 Not Found` — 알 수 없는 `kind` 또는 active/archive 둘 다 없음
- `416 Range Not Satisfiable` — 잘못된 Range (`start>end`, `start>=size`, 비-bytes 단위 등). 응답에 `Content-Range: bytes */TOTAL` 포함

**Streaming**
- 64 KB 청크 iterator. 대용량 파일도 RAM에 전체 적재하지 않음
- active (`runtime/sessions/{id}/artifacts/`) 우선, 없으면 archive (`runtime/archive/sessions/{id}/artifacts/`)로 투명 폴백 — `/close` 이후에도 동일 URL이 유효

## Observability
- `GET /metrics` — Prometheus 텍스트 형식. `recog_proxy_requests_total` (`X-Forwarded-For` 헤더 검출 횟수) 카운터 노출

## Validation Rules
### Research Mode
- WAV / PCM / 48kHz / mono
- built_in_mic only
- no pause/resume
- anchor expected

### 정책 위반 시
- reject
- warning
- degraded
중 하나를 file-level로 기록

## Error Codes
- room_not_found
- room_already_started
- participant_not_found
- not_host
- not_all_ready
- invalid_metadata
- unsupported_format
- unsupported_route
- policy_blocked
- session_not_found
- upload_rejected
- processing_failed
