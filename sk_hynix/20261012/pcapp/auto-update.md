# 자동 업데이트 (Windows)

> 작성일: 2026-10-12
> 코드: `src/main/services/updateService.js`, 화면: `src/renderer/pages/update.html`

## 1. 동작

```
앱 실행 (Windows 설치본만. 개발 모드·macOS 는 건너뜀)
  └─ UPDATE_SERVER_URL/latest.yml 의 버전과 현재 버전 비교 (최대 15초)
       ├─ 같음 / 확인 실패 / 주소 비어 있음 → 아무것도 안 함
       └─ 새 버전 → 메인 창을 "업데이트 중" 화면으로 바꾸고 다운로드 (닫기 버튼 없음 = 강제)
            ├─ 다운로드 실패 → 3초 안내 후 원래 화면, 다음 실행 때 재시도
            └─ 완료 → 조용히 설치 → 앱 자동 재실행
                 └─ "모든 사용자"로 설치된 PC 는 Windows 관리자 권한 창(UAC)이 뜬다
```

- 확인은 **앱을 켤 때 한 번만.** 녹음 중에 끼어들지 않는다
- 녹음 화면에 있으면 화면을 바꾸지 않고 다음 실행으로 미룬다
- 서버 장애가 녹음을 막지 않도록, 실패는 전부 "건너뜀"으로 처리한다

## 2. 설정

| 값 | 어디에 | 설명 |
|---|---|---|
| `UPDATE_SERVER_URL` | `src/config/app.config.json` | 파일을 올려 둘 폴더 주소. **비우면 업데이트 기능 꺼짐** |
| `UPDATE_ENABLED` | 〃 | `false` 면 꺼짐 |

> `.env` 는 설치본에 들어가지 않는다. 운영 값은 반드시 `app.config.json` 에.

## 3. 릴리스 절차

1. `package.json` 의 `version` 을 올린다 (예: `1.0.1`). **이 값으로 새 버전 여부를 판단한다**
2. `src/config/app.config.json` 의 `UPDATE_SERVER_URL` 확인
3. Windows 에서 빌드
   ```bash
   npm run build        # npm install 불필요 — electron-updater 는 src/main/vendor 에 묶여 있음
   ```
4. `dist/` 에서 3개를 업데이트 서버 폴더에 올린다
   ```
   latest.yml
   timbloRecApp Setup 1.0.1.exe
   timbloRecApp Setup 1.0.1.exe.blockmap
   ```
   `latest.yml` 은 **마지막에** 올린다 (먼저 올리면 exe 가 없는 상태에서 앱이 내려받으려 한다)
5. 아무 PC 에서 이전 버전을 실행해 업데이트 화면이 뜨는지 확인

### 업데이트 서버 요구사항
- 위 3개 파일을 HTTPS(또는 HTTP)로 그대로 내려주는 폴더면 된다. 별도 API 불필요
- 앱이 `GET {UPDATE_SERVER_URL}/latest.yml` 과 `GET {UPDATE_SERVER_URL}/<exe 이름>` 을 요청한다
- nginx 예: `location /download/pcapp/ { alias /data/timblo/pcapp-update/; }`

## 4. 알아둘 것

| 항목 | 내용 |
|---|---|
| 관리자 권한 | "모든 사용자"로 설치했으면 업데이트 때마다 UAC 창. 사용자가 거부하거나 관리자 비밀번호를 모르면 설치 안 되고 다음 실행 때 재시도 |
| 코드 서명 | 인증서 없음. SmartScreen/백신 경고가 뜰 수 있다 — 문제 생기면 대응 |
| macOS | 대상 아님 (고객 요청). Mac 은 서명·공증이 필수라 별도 작업 |
| `package.json` `publish` | `generic` + 자리표시 주소. `latest.yml` 을 만들게 하려는 것이고, 실제 주소는 실행 시 `UPDATE_SERVER_URL` 이 덮어쓴다 |
| 빌드 명령 | `npm run build` 가 `--publish never` 를 쓴다 (빌드가 어딘가로 업로드를 시도하지 않게) |
| electron-updater | npm 패키지가 아니라 `src/main/vendor/electron-updater.js`(6.3.9, 의존성 포함 한 파일). 망분리 PC 에서 설치 없이 빌드하기 위함. 다시 만드는 법은 `src/main/vendor/README.md` |
| 버전 비교 | 서버 버전이 **더 높을 때만** 업데이트 (`1.2.10 > 1.2.9`). 서버에 옛 버전이 있어도 내려가지 않는다 |

## 5. 로그

`update_check_begin` → `update_not_available` 또는 `update_available` → `update_downloaded` → (재실행)
실패: `update_check_failed` / `update_download_failed` / `update_install_failed` / `update_skipped`(reason)

## 6. 검증 상태

- 가짜 업데이터로 흐름 7건 확인 (최신이면 유지, 새 버전이면 화면 전환·진행률·조용히 설치+재실행, 녹음 화면 보호, 다운로드 실패 시 복귀), 버전 비교 6건
- 실제 Electron 에서 번들(`vendor/electron-updater.js`)이 로컬 서버의 yml 을 받아 새 버전을 읽어내는 것 확인 (macOS 라 `latest-mac.yml` 요청 — Windows 는 `latest.yml`)
- ⚠️ **실제 Windows 설치본으로는 미확인.** 첫 릴리스 때 위 3장 5번으로 반드시 확인할 것
