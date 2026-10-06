# 업로드 2단계(1차 업로드 → 2차 변환) SSE 수신 구조 분석

- 대상 브랜치: `develop` (9670767 기준)
- 관련 코드
  - `lib/views/main/main_container_controller.dart` — SSE 연결 (`listenMeetingMinutesStatus`)
  - `lib/services/file_upload_services/uploaded_listener.dart` — 변환 상태 처리/보관 (`isProcessingMap`)
  - `lib/services/file_upload_services/upload_service.dart` — 1차 업로드
  - `lib/models/response/response_meeting_minutes_status.dart` — SSE 이벤트 모델
  - `lib/widgets/upload_progress_widget.dart` — 업로드/변환 팝업 UI
- 상태 요약: 1차 업로드(HTTP multipart)와 2차 변환(서버 → 앱 SSE 푸시)은 **서로 연결되지 않은 독립 경로**다. 앱은 업로드 완료 후 변환 상태를 직접 조회하지 않고, 서버가 SSE로 보내주는 이벤트에만 의존한다.

---

## 1. 전체 흐름

```
[1차 업로드]                                    [2차 변환]
UploadService.processUploadQueue                 서버 STT/LLM 파이프라인
  └ POST /m/api/contents/upload/encryption/files        │
      (Android·Hynix: Dio / SKT·Timblo iOS: URLSession)  │ 상태 변화 발생
  └ 성공 → upload_yn='Y', uploadList 에서 제거            ▼
                                                 GET {host}/events/   (SSE, 상시 연결)
                                                        │
                           MainContainerController.listenMeetingMinutesStatus
                                                        │ type=='message'
                                                        ▼
                                  UploadedListener.handleStatusEvent(data)
                                                        │
                                  isProcessingMap[contentId] 갱신/삭제
                                                        │ (RxMap)
                                                        ▼
                                  UploadProgressWidget "변환 중 N건" 영역
```

| 단계 | 방식 | 상태 저장소 | UI |
|---|---|---|---|
| 1차 업로드 | HTTP POST multipart, 누락 파일(`missingFiles`) 재전송 최대 3회 | `UploadService.uploadList`, `tStorage[upload_list]` | 업로드 진행률 영역 |
| 2차 변환 | SSE(서버 푸시) | `UploadedListener.isProcessingMap` (메모리 전용) | 변환 진행 영역 |

---

## 2. SSE 연결 (`main_container_controller.dart:419`)

| 항목 | 내용 |
|---|---|
| 라이브러리 | `eventflux: ^2.2.1` (`EventFlux.instance` 싱글톤) |
| URL | `baseUrl.replaceAll('/m', '') + '/events/'` → 예: `https://skt.timblo.io/events/` (`api_const.dart:124`) |
| 메서드/헤더 | GET, `Authorization: Bearer <accessToken>` (연결 시점 토큰) |
| SSL | `useSSL == false`면 `UnsafeHttpClientAdapter` |
| 재연결 | `autoReconnect: true`, linear 5초 간격, **최대 5회** |
| 중복 방지 | `_isConnecting` 플래그 + 연결 전 기존 연결 `disconnect()` 후 100ms 대기 |
| 연결 시점 | `onReady()` (`:118`), 포그라운드 복귀(`resumed`) 300ms 후 (`:211`) |
| 종료 시점 | `onClose()` (`:131`) |

- 앱이 백그라운드로 가도 명시적으로 끊지 않는다(OS가 소켓을 끊을 수 있음). 복귀 시 무조건 재연결한다.
- 모든 서비스 타입(SKT/Hynix/Timblo)에서 연결한다.

---

## 3. 이벤트 포맷과 상태 매핑

### 3-1. 수신 페이로드 (`response_meeting_minutes_status.dart`)

```json
{
  "type": "message",
  "message": "...", "httpCode": 200, "timestamp": "...",
  "data": { "uuid": "...", "contentId": "...", "status": "PROGRESS", "percentage": 42, "fileName": "..." }
}
```

`type == 'message'`인 이벤트만 처리한다(`:455`). 그 외 type(heartbeat 등)은 무시한다.

### 3-2. 상태 → 표시 매핑 (`uploaded_listener.dart:79`)

| status | processStatus | 진행률 | 동작 |
|---|---|---|---|
| (기타: WAITING/RUNNING 등) | 음성 인식 중... | 0% | 맵에 추가/갱신 |
| `PROGRESS` | 음성 인식 중... | `percentage × 0.7` (0~70%) | 맵 갱신 |
| `STT_DONE` | 요약 진행 중... | 80% | 맵 갱신 |
| `LLM-RUNNING` | 요약 진행 중... | 90% | 맵 갱신 |
| `SUMMARY_DONE` | 요약 진행 완료 | 100% | 맵 갱신 (아직 제거 안 함) |
| `DONE` / `ERROR` | – | – | 맵에서 제거 → 300ms 후 `refreshData()`로 홈/목록/캘린더/알림 새로고침 |

- 맵 키는 **서버 `contentId`**. `contentId`가 비어 있으면 무시한다.
- 진행률 구간: STT 0~70 → 요약 80/90 → 100.

---

## 4. 1차 → 2차 연결 지점 (핸드오프)

| 플랫폼/경로 | 업로드 성공 직후 `isProcessingMap` 처리 |
|---|---|
| Android / Hynix iOS (Dio) | **아무것도 넣지 않음** (`upload_service.dart:1150` 이후). 첫 SSE 이벤트가 올 때 비로소 변환 영역에 나타남 |
| SKT·Timblo iOS (네이티브 URLSession) | 로컬 `file['id']`를 키로 임시 항목(“업로드 완료”, 100%) 추가 후 **3초 뒤 삭제** (`:1249~1264`) |

즉, 업로드 완료 → 첫 SSE 이벤트 수신 사이에는 팝업에 해당 파일이 보이지 않는 공백 구간이 있을 수 있다.

---

## 5. 누락 이벤트 보정

| 보정 수단 | 위치 | 하는 일 | 한계 |
|---|---|---|---|
| 포그라운드 복귀 동기화 | `uploaded_listener.dart` `syncProcessingStatus()` | 맵에 **이미 있는** 항목만 `getContentDetail`로 조회, `DONE/ERROR`면 제거 | 맵에 없는 항목은 추가하지 않음. 진행률도 갱신하지 않음 |
| 업로드 후 목록 폴링 | `requestUploadedContents()` / `receivedContents()` | 5초 간격 3회 목록 조회 | **호출부가 주석 처리되어 현재 미사용** (`:40`) |

`isProcessingMap`은 메모리 전용이라 앱 재시작 시 비어 있고, 진행 중 변환은 다음 SSE 이벤트가 와야 다시 보인다.

---

## 6. 확인된 특이점 / 잠재 이슈

| # | 내용 | 영향 | 위치 |
|---|---|---|---|
| 1 | SSE `Authorization`은 연결 시점 토큰으로 고정. 토큰 자동 갱신(fc2d250) 후에도 SSE는 재연결하지 않음 | 서버가 끊은 뒤 eventflux 자동 재연결 시 만료 토큰 → 401 반복 가능. 복귀 전까지 변환 이벤트 미수신 | `main_container_controller.dart:436,443` |
| 2 | 자동 재연결 최대 5회(약 25초) 소진 후에는 포그라운드 복귀 외에 재연결 트리거가 없음 | 앱을 켜둔 채 네트워크가 30초 이상 끊기면 SSE 영구 단절 (connectivity 복구 시 재연결 없음) | `:476~484` |
| 3 | iOS 임시 항목 키는 로컬 `file['id']`, SSE 키는 서버 `contentId` | 두 값이 다르면 3초 동안 같은 파일이 2줄로 보이거나, 임시 항목이 사라진 뒤 공백 발생. 서버가 동일 ID를 쓰는지 확인 필요 | `upload_service.dart:1253` |
| 4 | Android/Dio 경로는 업로드 성공 직후 변환 영역에 아무것도 없음 | 서버 첫 이벤트가 늦으면 “업로드 완료 → 팝업 사라짐 → 나중에 변환 표시” 깜빡임 | `upload_service.dart:1150~` |
| 5 | 복귀 동기화가 제거만 하고 추가·진행률 갱신은 안 함 / 앱 재시작 시 맵 초기화 | 백그라운드 중 시작된 변환, 재시작 후 진행 중 변환이 표시되지 않음 | `uploaded_listener.dart` `syncProcessingStatus` |
| 6 | `SUMMARY_DONE`은 100% 표시 후 `DONE`까지 남아 있음 | `DONE` 이벤트 유실 시 100% 항목이 복귀 동기화 전까지 계속 남음 | `uploaded_listener.dart:99` |
| 7 | `onDone`/`onError`에서 `_isConnecting=false`만 처리, 로그 외 사용자 알림 없음 | 연결 상태를 앱에서 알 수 없음 (디버깅 시 `appLog` 미기록 — `debugPrint`만 사용) | `:463~477` |
| 8 | URL 생성이 `replaceAll('/m', '')` | 현재 호스트들은 문제없으나, 호스트가 `m`으로 시작하면(`https://m...`) `//m`까지 치환되어 URL 깨짐 | `:442` |
| 9 | 상태 문구 하드코딩(`'음성 인식 중...'` 등) | 다국어 규칙 위반, 영어/일본어 등에서도 한글 표시 | `uploaded_listener.dart:94~110` |

---

## 7. 추가 확인이 필요한 사항 (서버 측)

- SSE 이벤트의 `contentId`와 업로드 시 앱이 가진 로컬 `id`의 관계 (#3)
- 서버의 heartbeat 전송 여부와 유휴 타임아웃 (연결이 조용히 끊기는지)
- 토큰 만료 시 SSE 연결을 서버가 끊는지, 유지하는지 (#1)
- 사용자 단위 브로드캐스트인지 (다른 기기에서 올린 파일 이벤트도 오는지)

---

## 8. SSE 재연결 가능 여부 (eventflux 2.2.1 소스 확인)

**결론: 재연결은 가능하다.** `disconnect()` 후 `connect()`를 다시 부르면 재연결 카운터(`_maxAttempts`)와 명시적 종료 플래그가 초기화되므로, `listenMeetingMinutesStatus()`를 다시 호출하는 방식으로 언제든 새로 연결할 수 있다. 다만 라이브러리 자동 재연결에만 기대면 아래 이유로 영구 단절이 생긴다.

| # | 라이브러리/앱 동작 | 결과 | 근거 |
|---|---|---|---|
| A | 재연결 횟수가 `connect()` 한 번 기준 **누적**. 재연결이 성공해도 초기화되지 않음 | 연결 후 5번 끊기면(각각 복구됐더라도) 이후 자동 재연결 없음 | `client.dart` `_attemptReconnectIfNeeded` (`_maxAttempts--`, 성공 시 리셋 없음) |
| B | 응답이 2xx가 아니면(401 등) `onError`만 호출하고 **재연결하지 않음** | 토큰 만료 상태에서 재연결 → 401 → 그대로 종료 | `client.dart` `_start` (`statusCode < 200 \|\| >= 300` → `return`) |
| C | 재연결 헤더는 최초 헤더 재사용. `ReconnectConfig.reconnectHeader`로 최신 토큰을 줄 수 있으나 **미사용** | 재연결 시 만료 토큰 사용 → B로 이어짐 | `main_container_controller.dart:479` |
| D | 스트림 유휴 타임아웃/하트비트 감시 없음. `:` 주석 라인(서버 ping)은 파서가 무시해 앱에 전달되지 않음 | 조용히 죽은 연결(Wi-Fi↔LTE 전환 등)은 `onDone`/`onError`가 오지 않아 **앱은 연결된 것으로 인식** | `client.dart` 라인 파서 (`field.isEmpty → return`) |
| E | 앱 `_isConnecting`은 성공/에러 콜백에서만 해제. 요청이 응답 없이 걸리면 `true`로 고착 | 이후 포그라운드 복귀 등의 `listenMeetingMinutesStatus()` 호출이 모두 skip | `main_container_controller.dart:421` |
| F | `disconnect()`해도 이미 예약된 재연결(`Future.delayed` 5초)은 취소되지 않고, 실행 시 `_isExplicitDisconnect=false`로 되돌림. 싱글톤(`EventFlux.instance`)이라 필드 공유 | 앱이 재연결하는 타이밍과 겹치면 연결 2개가 경쟁하거나 이전 연결이 살아남음 | `client.dart` `disconnect`/`_start` |

### 재연결을 앱이 주도하려면

- 연결마다 세대 번호(run 토큰)를 두고 이전 세대의 콜백은 무시한다. 또는 `EventFlux.spawn()`으로 연결마다 새 인스턴스를 쓴다(F 대응).
- `reconnectHeader`로 매번 저장소의 최신 토큰을 읽는다(C 대응). 401이면 토큰을 갱신한 뒤 앱이 직접 재연결한다(B 대응).
- `onError`/`onDone`에서 앱이 직접 백오프 재연결하고 횟수 제한을 없앤다(A 대응).
- 연결 요청에 타임아웃을 두어 `_isConnecting` 고착을 막는다(E 대응).
- D는 앱만으로 완전히 감지할 수 없다. 서버가 `data:`가 있는 heartbeat 이벤트를 주기적으로 보내면 유휴 감시가 가능하다. 서버 협의가 필요하므로 **변환 중 상태 폴링(안전망)은 재연결 개선과 별개로 반드시 필요하다.**

---

## 관련 문서

- [업로드-66퍼센트-정체-원인분석.md](업로드-66퍼센트-정체-원인분석.md)
- [업로드-실패-원인-정리.md](업로드-실패-원인-정리.md)
- [업로드-중단-원인분석.md](업로드-중단-원인분석.md)
- [녹음-업로드-테스트-시나리오.md](녹음-업로드-테스트-시나리오.md)
