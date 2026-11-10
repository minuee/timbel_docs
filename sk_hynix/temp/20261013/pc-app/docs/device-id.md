# 디바이스 ID

> 작성일: 2026-10-12 · 코드: `src/main/services/deviceService.js`

```js
const { getDeviceId } = require('./services/deviceService');
getDeviceId(); // 'pc-e27907f77995ef6e57092b2e891fd482' — 같은 PC 면 항상 같은 값
```

## 만드는 방법
1. OS 기기 고유값을 읽는다 — Windows `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid`, macOS `IOPlatformUUID`
2. 앱 고유 문자열과 섞어 SHA-256 → 앞 32자리, `pc-` 접두어. 원래 하드웨어 값은 밖으로 나가지 않는다
3. 1번 실패 시 무작위 UUID 를 앱 데이터 폴더(`device-id` 파일)에 저장해 계속 쓴다

## 특성
- 앱을 재설치해도 같은 값. Windows 재설치 시에는 바뀐다
- ⚠️ PC 를 같은 디스크 이미지로 복제 배포하면서 sysprep 을 안 했다면 여러 대가 같은 값일 수 있다

## 지금 쓰는 곳
- 로그 서버로 보내는 모든 로그의 `deviceId`
- **업로드의 `deviceId` 는 아직 `'1'` 그대로**(`authService.getDeviceId()`). 바꾸려면 그 함수가 이 값을 돌려주게 하면 된다

## 헤더와 구분
`timblo-Device` 헤더는 모바일에서도 고유 ID 가 아니라 **기기 모델명**이다. PC 는 `Windows_NT 10.0.xxxxx` 를 보낸다(`apiService.js`).
