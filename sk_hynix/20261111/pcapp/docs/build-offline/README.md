# 망분리 PC 에서 `npm run build` (Windows)

electron-builder 는 빌드할 때 GitHub 에서 파일을 받아 온다. 회사는 GitHub 가 막혀 있어서 실패한다.
받아 오는 것은 아래 4개이고, 두 가지 방법으로 다운로드를 없앴다.

| 받아 오던 것 | 해결 |
|---|---|
| `electron-v38.x-win32-x64.zip` (Electron 본체) | `package.json` `build.electronDist` = `node_modules/electron/dist` — 이미 설치된 Electron 을 복사해서 쓴다 |
| `winCodeSign-2.6.0` (exe 아이콘·버전 정보 넣기) | 캐시 폴더 반입 (아래) |
| `nsis-3.0.4.1` (설치 파일 만들기) | 캐시 폴더 반입 |
| `nsis-resources-3.4.1` (설치 파일 플러그인) | 캐시 폴더 반입 |

그리고 `build.npmRebuild` = `false` — 빌드 중 better-sqlite3 를 다시 컴파일하려고 GitHub/electronjs.org 에서
파일을 받는 단계를 끈다. `npm run dev` 가 되는 PC 면 `node_modules` 의 better-sqlite3 가 이미 Electron 용이라 다시 만들 필요가 없다.

> 집(인터넷 되는 Mac)에서 2026-10-13 에 같은 설정으로 Windows 설치 파일까지 만들어
> **다운로드가 한 건도 없는 것**을 확인했다(electron-builder 24.13.3).

---

## 1. 가져갈 것

`docs/build-offline/dist/electron-builder-Cache.zip` (약 15MB) — git 에 없음(`dist/` 제외). **따로 복사**

- SHA-256: `fa6a84deb73276f80bdc8d899d55ff9b56555b3bf45737664de2e3032836df55`
- 안에 든 것
  ```
  Cache/
    nsis/nsis-3.0.4.1/
    nsis/nsis-resources-3.4.1/
    winCodeSign/winCodeSign-2.6.0/
  ```

## 2. 회사 PC 에 풀기 (한 번만)

1. 탐색기 주소창에 `%LOCALAPPDATA%\electron-builder` 입력 (없으면 `electron-builder` 폴더를 만든다)
2. zip 을 풀어 **`Cache` 폴더째** 넣는다. 결과가 이렇게 되어야 한다
   ```
   C:\Users\<나>\AppData\Local\electron-builder\Cache\nsis\nsis-3.0.4.1\...
   C:\Users\<나>\AppData\Local\electron-builder\Cache\nsis\nsis-resources-3.4.1\...
   C:\Users\<나>\AppData\Local\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0\...
   ```
   `Cache\Cache\...` 처럼 한 단계 더 들어가면 못 찾는다.
3. 이미 `Cache` 폴더가 있으면 덮어써도 된다.

> 위치를 바꾸고 싶으면 환경변수 `ELECTRON_BUILDER_CACHE` 로 지정할 수 있다
> (예: `set ELECTRON_BUILDER_CACHE=D:\eb-cache` 후 `npm run build`). 그 폴더 안에 `nsis`, `winCodeSign` 이 바로 있어야 한다.

## 3. 빌드

```bash
npm run build
```
- 결과: `dist/SKHynixRecApp-Setup-<버전>.exe`, `SKHynixRecApp-Setup-latest.exe`, `latest.yml`, `.blockmap`
- 로그에 `downloading url=https://github.com/...` 가 **나오지 않으면** 성공

## 막혔을 때

| 증상 | 원인 / 할 일 |
|---|---|
| `downloading ... electron-v38...win32-x64.zip` | `package.json` 의 `electronDist` 가 빠졌다. 이번 `package.json` 으로 교체 |
| `downloading ... winCodeSign` / `nsis` | 캐시 위치가 틀렸다. 2번 경로 다시 확인 (`Cache\Cache` 여부) |
| `electronDist ... not found` 류 | `node_modules\electron\dist\electron.exe` 가 있는지 확인. 없으면 Electron 설치가 덜 된 것 |
| `downloading ... prebuild` / `node-gyp` / `headers` | `npmRebuild: false` 가 빠졌다. 이번 `package.json` 으로 교체 |
| 그 외 `downloading` | 그 줄의 url 을 가져오면 집에서 받아 같은 방식으로 묶어 준다 |
