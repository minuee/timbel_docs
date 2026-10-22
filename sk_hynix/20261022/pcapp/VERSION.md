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
