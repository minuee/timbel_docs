# recog 백엔드 소스 분석 (2026-09-03)

## 한 줄 요약
회의 참가자 여러 명(최대 5명)이 각자 기기로 녹음한 오디오를 서버가 시간축 정렬(offset + drift 보정)해서, 정렬된 트랙 묶음 + 검수용 믹스다운 + STT 핸드오프 매니페스트를 만들어 로컬에 보관하고 HTTP로 내려주는 **전처리 API 서버**. STT/전사, S3 업로드, 녹음 클라이언트(모바일 앱)는 이 레포에 없음.

## 전체 흐름
```
[모바일/설치형/웹 클라이언트 녹음] (레포 밖, 별도 구현)
      ↓ 업로드 (파일 통째로 1회, multipart/form-data)
[recog 서버] ← 이 레포
   POST /rooms → join/preflight/ready/start/stop
   POST /sessions → recordings → file → process → close
   ffmpeg로 48kHz mono PCM 정규화
   앵커(비프/박수) + 상호상관으로 offset 추정, drift 보정
   정렬 트랙 + listening_mix.wav + manifest 생성, 로컬 디스크 보관
      ↓ HTTP GET (Range/206 스트리밍 지원)
[다운스트림 시스템] ← 이 레포에 없음 (STT 전사, S3 저장 등)
```

## 코드 구조 (~4,900 LOC, stdlib + ffmpeg subprocess만 사용, pip 의존성 없음)
| 위치 | 역할 |
|---|---|
| `src/recog/api.py` (898줄) | stdlib WSGI 서버, 라우팅 직접 파싱 |
| `src/recog/store.py` (673줄) | 파일시스템 기반 세션 스토어, 원자적 쓰기 |
| `src/recog/pipeline.py` (419줄) | 정렬 파이프라인 오케스트레이션 |
| `src/recog/contracts.py` / `protocol_models.py` | 업로드 메타데이터 검증, capture policy (research/pilot 모드) |
| `src/audio_sync/dsp/` | 앵커 탐지, 정렬(정규화 상호상관), drift, 캐노니컬라이즈 |
| `src/audio_sync/export/` | manifest, mixdown, 패키징, 검증 |
| `tools/`, `testkit/`, `scripts/` | 합성 코퍼스 생성, 부하 프로브, 증거 번들 |
| `tests/` | unittest 141개 (138 통과, 3개는 없는 mobile_app/ 검사 도구라 실패) |

## API 엔드포인트
- `POST /rooms` → `/rooms/{id}/join|preflight|ready|start|stop`, `GET /rooms/{id}`
- `POST /sessions` → `/sessions/{id}/recordings` → `.../file` → `/process` → `/close`
- `GET /sessions/{id}/artifacts`, `GET /sessions/{id}/artifacts/{filename}` (Range/206, HEAD 지원)
- `/health`, `/metrics`

## STT 관련 (전사 기능 자체는 없음)
- `export_stt_track()` (`src/recog/audio.py:75`) — ffmpeg로 16kHz/mono/16bit 사본 생성. **리샘플링만** 하고 실제 전사는 안 함
- 매니페스트에 `recommendedSttInput: "tracks" | "mixdown"` — 트랙 2개 이상이면 "tracks" 권고 (믹스하면 화자분리 정보 소실되므로)
- `scope_audit.speaker_diarization: false` — 화자분리 기능 명시적으로 미지원 선언. 대신 트랙을 분리 유지해서 정렬만으로 화자분리 효과를 얻는 설계

## "머지"의 의미 — 기존 업로드 시스템과 축이 다름
| | 기존 업로드 시스템(사용자 언급) | recog |
|---|---|---|
| 입력 | 한 소스의 3분 단위 조각들 | 참가자 5명의 통짜 녹음 |
| 합치는 방식 | 시간순 연결(concatenation) | 시간축 정렬(alignment, offset+drift) |
| 출력 | 병합된 단일 파일 | 정렬된 개별 트랙 + 믹스 + 매니페스트 |
| 저장 | S3 업로드 | 로컬 디스크, HTTP GET pull 방식 |
| 분할 녹음 | 전제 | **정책상 거부** (`pause_resume_not_allowed`) |

- S3/boto/presign 코드 전체 검색 결과 없음. 문서 2줄에만 "object storage" 언급, 구현 없음
- 청크 업로드/멀티파트(S3 의미의)/재개(resume) 없음. `multipart/form-data`는 그냥 "metadata + 파일 1개"를 한 요청에 보내는 HTTP 표준 방식
- close 시 `archive/sessions/{id}/`로 파일 이동 + 작업 디렉터리 정리. 최신 커밋에 호스트 cleanup 스크립트 + systemd 타이머 + logrotate 추가됨

## 클라이언트 3종(모바일/설치형/웹) 관점에서 본 제약
- `validate_join_room_payload`가 `os_type in {"ios","android"}`만 허용 — **mode 무관하게 무조건** 웹/설치형 앱의 방 입장을 막음. 붙이려면 여기부터 수정 필요
- Research 모드는 매우 엄격: WAV, 48kHz, mono, `built_in_mic`, AGC/노이즈억제/에코제거 전부 off, 정밀 타이밍 필드(`local_monotonic_start_tick` 등) 필수 — 브라우저 getUserMedia 기본 동작과 정면 충돌
- `mode: "pilot"`으로 방을 만들면 위 엄격한 검사들이 스킵됨 — 3종 클라이언트를 붙인다면 현실적으로 pilot 경로. 단, `os_type` 검사만은 mode 무관하게 그대로 걸림
- 모든 클라이언트 공통: `start_strategy: "server_authoritative_beep"` — 서버가 시작 신호를 보내고 각 클라이언트가 동기화용 비프를 녹음에 포함해야 함 (정렬 기준점)

## 완성도 평가
**되어 있는 것**
- 백엔드 DSP/파이프라인 로직은 실제 동작, 테스트 141개 중 138개 통과
- Docker + GitLab CI 배포 파이프라인 구성됨, `skHynix` 브랜치 푸시 시 자동 빌드/배포/헬스체크
- 문서량 많음 (PRD, 프로토콜, 정책, 검증 매트릭스 등)

**안 되어 있는 것 / 없는 것**
- 녹음 클라이언트(모바일 앱) 자체가 레포에 없음. `STATUS.json`: `"state": "blocked_on_flutter_poc"`, Flutter 미설치 상태로 기록
- **인증 없음** — `api.py`에 토큰/JWT/API키 검증 전무. `join_code` 대조가 유일한 접근 통제
- STT/전사 연동 없음, S3 연동 없음
- 문서-코드 불일치: `HANDOFF_STATUS.md`는 "room/session API 미구현"이라 되어 있으나 실제로는 구현됨 / `mobile_app/`, `apps/`, `mobile/` 디렉터리가 문서·AGENTS.md에 언급되지만 실제로는 존재하지 않음 (관련 검사 도구 테스트 3개 실패 원인)
- git 커밋 8개, 전부 2026-04-21 하루에 생성 — 최근에 한 번에 만들어진 신규 프로젝트

**결론**: 오디오 정렬 엔진 + API 서버(중간 토막)는 실제로 완성되어 배포까지 되지만, 양쪽 끝(녹음 클라이언트 ↔ STT/저장 시스템)이 비어 있어 End-to-End로는 아직 돌지 않는 상태. 프로젝트 스스로도 이를 인지하고 있음(`BLOCKED_ON_POC.md`, `NEXT_ACTION.md`).
