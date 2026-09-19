# Flutter App Requirements

## 1. 목적
이 앱은 단순 녹음기가 아니라, room/session 참여, 녹음 규칙 강제, metadata 수집, 파일 업로드를 수행하는 capture client이다.

## 2. 핵심 역할
- room create/join
- ready
- host start
- baseline recorder
- metadata capture
- anchor UX
- upload/retry

## 3. 모드
### Research Mode
- WAV / PCM / 48kHz / mono
- built-in mic only
- pause/resume 금지
- start/end anchor required

### Pilot Mode
- 일부 제약 완화
- anchor optional
- warning 중심 정책

## 4. 주요 화면
- Home
- Create Room
- Join Room
- Lobby
- Recording
- Upload
- Error

## 5. 필수 기능
- room join / ready / host start
- baseline recording
- metadata JSON 생성
- multipart upload
- retry
- 정책 위반 차단

## 6. 핵심 UX 원칙
- host / participant 역할이 명확해야 한다
- 녹음 시작/종료 시점을 사용자에게 명확히 알려야 한다
- 연구 모드 정책 위반은 조용히 넘어가면 안 된다
- 업로드 실패는 retry 가능해야 한다
