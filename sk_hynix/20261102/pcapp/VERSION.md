# 배포 이력

앱을 빌드해서 배포할 때마다 한 줄씩 추가한다.

- 앱 버전은 `package.json` 의 `version`. 빌드 전에 올린다(설치 파일 이름·자동 업데이트 비교에 쓰인다).
- 자세한 변경 내용·회사 확인 결과는 `docs/update_YYYYMMDD.md`.

| 버전 | 배포일 | 내용 | 헬퍼 | 관련 문서 |
|---|---|---|---|---|
| 0.0.1 | | 최초 배포 | | |
| 0.0.2 | | 시스템 사운드 적용 — 시스템 소리 파형·무음 경고 기준 조정 | 0.4.3 | `docs/update_20261019.md` ① |
| 0.0.3 | | 다국어 적용 — 한국어/English/日本語/简体中文 (옵션 `MULTI_LANG_ENABLED`) | 0.4.3 | `docs/update_20261019.md` ② |
| 0.0.4 | | 세션 유지 적용 — 로그인 유지 (옵션 `SESSION_PERSIST_ENABLED`), 녹음 이름 `A.Biz_p_rec_` | 0.4.3 | `docs/update_20261021.md` |
| 0.0.5 | | 약관 동의 확인 적용 — 미동의 시 로그아웃 + 안내 팝업 (옵션 `TERMS_CHECK_ENABLED`), 테스트 로그인도 로그인 유지 | 0.4.3 | `docs/update_20261022.md` |
| 0.0.6 | | 요약 언어 일본어(`ja`)·중국어(`zh`) 추가, `timblo-App-OS` 헤더 OS 자동 (`AOS-WINDOWS` / `IOS-MAC` / `AOS-ETC`) | 0.4.3 | `docs/update_20261023.md` |
| 0.0.7 | | 약관 미동의 팝업에 재동의 안내 문구, 로그인 화면 [시스템 로그인] 버튼(화면만, 옵션 `SYSTEM_LOGIN_ENABLED`) | 0.4.3 | `docs/update_20261030.md` |
| 0.0.8 | | API 요청 헤더·로그에 `x-device-timezone`/`timezone` 추가 (PC 시간대, 예: `Asia/Seoul`), 업로드 누락 조각만 자동 재전송·유실 안내·실패 시 파일 보존, 사용자에게 보이는 이름 `SKHynixRecApp`(설치 파일 `SKHynixRecApp-Setup-<버전>.exe` + `-latest.exe`, exe 파일 설명, 설치 화면) | 0.4.3 | `docs/update_20261102.md` |
