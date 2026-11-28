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
| 0.0.9 | | 화면 언어 한국어·English 두 개로(기본 켬), AI회의록 권한 없음 안내 팝업 → [확인] 앱 종료(권한 확인 API 는 준비 중, 옵션 `ACCESS_CHECK_*`), 녹음 중 미니(축소) 모드 | 0.4.3 | `docs/update_20261109.md` |
| 0.0.10 | | 미니 모드 [확대] 후 파동이 빈 화면부터 다시 차오르던 것 수정 (미니 동안 파동 보관), 시스템 로그인(AM-Tray) 연동 뼈대 — AmHelper.exe·흉내 모드(기본 꺼짐, 옵션 `AMTRAY_*`) | 0.4.3 | `docs/update_20261110.md` |
| 0.0.11 | | 시스템 로그인(AM-Tray) DLL 호출을 AmHelper.exe(C++) → koffi(앱이 별도 작업 프로세스에서 바로 부름)로 변경, DLL 함수 모양 두 방식 선택(옵션 `AMTRAY_DLL_SIGNATURE`), 응답코드 공백 = 509090 처리 | 0.4.3 | `docs/update_20261112.md` |
| 0.0.12 | | 설정 개발/운영 분리 — `app.config.json` 의 `APP_ENV`(dev/prod) + `dev`·`prod` 묶음(URL·SSO 값), 빌드 명령 `build:dev` / `build:prod` | 0.4.3 | `docs/update_20261113.md` |
| 0.0.13 | | 시스템 로그인(AM-Tray) DLL 함수 모양을 C++ 매뉴얼대로 확정 — `Init` → `GetSystemToken`(BOOL + 응답코드), `IsLoginIT`·`CheckLoginUserIT` 추가, DLL 이름 `AmInterface_RT_X64.dll`, 옵션 `AMTRAY_DLL_SIGNATURE`·`AMTRAY_DLL_WIDE` 없앰 → `AMTRAY_DLL_INIT` | 0.4.3 | `docs/update_20261116.md` |
| 0.0.14 | | 시스템 로그인(AM-Tray) 확정값(sid `AIMEETINGdev`/`AIMEETING`, systemID `AIMEETING`, ssoKey `_NF`, 설치 페이지) — 이제 [시스템 로그인]이 DLL 을 부름, 매뉴얼 응답코드 표대로 팝업(설치 안내·접근 불가·SSO 실패), 로그인 뒤 AM-Tray 확인(창 활성화·녹음 전 IsLoginIT, 다른 사용자 CheckLoginUserIT), DLL version 버퍼 64·Init 201011 수정, 인가토큰을 사용자 토큰으로 바로 사용(`AMTRAY_TOKEN_MODE: direct`, `/me` 확인)·토큰 모양 로그, 시작 로그 `appEnvSource`·`packaged`, 빌드 exe 이름 바꾸기 재시도 | 0.4.3 | `docs/update_20261117.md` |
| 0.0.15 | | 메인 창 제목 `SKHynix AIMM` 고정, AM-Tray DLL 을 본체 프로세스에서 부르는 시험 스위치(`AMTRAY_DLL_PROCESS`, 기본 꺼짐), 예전 로그인(사번·MyAccess) 삭제 — 로그인은 시스템 로그인·테스트 로그인만 | 0.4.3 | `docs/update_20261118.md` |
| 0.0.16 | | 시스템 로그인 접근 불가(503031~503034·503036) 때 앱을 끄지 않음(팝업 뒤 로그인 화면), AM 로그인 창 뒤 앱으로 돌아오면 토큰 다시 요청, 녹음 전 사용자 확인(CheckLoginUserIT), 502052 [다시 시도], DLL 로드 실패(500001·500003) 설치 안내, `app.config.json` 회사 실제 값(개발 aimeetingdev / 운영 aimeeting, 운영 설치 주소 install.do, 로그인 화면 ver2) | 0.4.3 | `docs/update_20261119.md` |
| 0.0.17 | | 인증 API 인계문서(11-24) 반영 — 요청 헤더 `timblo-App-OS` 만(모바일 판정 방지, HMP 약관 확인은 4개 그대로), 토큰 헤더 `Authorization: Bearer` + `X-Timblo-Token` 함께, 서버 로그아웃(`DELETE /api/auth/logout`, 옵션 `LOGOUT_PATH`·`LOGOUT_METHOD`), 갱신 거절(529·530·531) 시 AM-Tray 로 조용히 재로그인 → 실패 시 만료 팝업(녹음 중엔 화면 유지), 시스템 로그인 뒤 HMP 약관 재확인 제거(로그인 API 가 확인), `AMTRAY_LOGIN_PATH` `/api/auth/sso/amtray`, 녹음 대상 "내 목소리 + 회의 소리" 제거(기본 "회의 소리만"), 마이크 테스트 창 아래 잘림 수정, 일본어·중국어 문구 파일 채움 | 0.4.3 | `docs/update_20261128.md` |
