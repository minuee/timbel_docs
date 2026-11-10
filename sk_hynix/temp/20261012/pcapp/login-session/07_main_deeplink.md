# 작업 7 — 딥링크 중복 처리 수정 + 로그인 후 화면 전환

**손대는 파일**: `src/main/main.js` — **수정 3곳**
**다른 파일은 건드리지 않는다.**
**선행 작업**: 작업 5 (`onAuthenticated` 를 불러오는 줄이 있어야 한다)

## 왜 필요한가
1. **기존 버그 수정**: 앱이 꺼진 상태에서 딥링크로 실행되면 같은 딥링크가 `processDeepLink()` 를 두 번 탄다.
   `code` 는 1회용이라 두 번째 교환이 실패하고, 로그인 성공 직후 "실패" 통지가 화면에 날아간다.
   이미 처리한 `code` 는 건너뛴다.
2. **화면 전환**: MyAccess 로그인 후 토큰 교환이 성공하면, 로그인 화면에서 메인 화면으로 넘긴다.

## 할 일

### 7-1. 처리한 code 기록용 변수 추가
`// 딥링크 처리 설정` 아래(176번째 줄 근처).

**[찾을 코드]**
```js
const PROTOCOL_SCHEME = "timbloRecApp";
let deepLinkQueue = [];
```

**[바꿀 코드]**
```js
const PROTOCOL_SCHEME = "timbloRecApp";
let deepLinkQueue = [];
// 이미 교환을 시도한 code. 창 로딩 중에 들어온 딥링크는 sendDeepLinkToRenderer 와
// flushDeepLinks 양쪽에서 processDeepLink 를 타는데, code 는 1회용이라 두 번째 교환이
// 실패하면서 "로그인 성공 직후 실패 통지"가 날아가던 문제를 막는다.
const handledDeepLinkCodes = new Set();
```

### 7-2. 같은 code 는 한 번만 처리
`processDeepLink()` 함수 안(243번째 줄 근처).

**[찾을 코드]**
```js
    try { logger.logInfo('deeplink_received', { route, code_present: !!code, host_present: !!hostB64 }); } catch (_) {}
```

**[바꿀 코드]**
```js
    try { logger.logInfo('deeplink_received', { route, code_present: !!code, host_present: !!hostB64 }); } catch (_) {}
    if (code && handledDeepLinkCodes.has(code)) return;
    if (code) handledDeepLinkCodes.add(code);
```

### 7-3. 교환 성공 후 화면 전환
같은 함수 안, 아래쪽(275번째 줄 근처).

**[찾을 코드]**
```js
    broadcastAuthExchanged({ success: true, endpoint });
```

**[바꿀 코드]**
```js
    broadcastAuthExchanged({ success: true, endpoint });
    // 로그인 화면에서 기다리던 중이면 메인 화면으로 넘긴다.
    onAuthenticated();
```

## 확인 방법
```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/main/main.js','utf8')); console.log('문법OK')"
node -e "const s=require('fs').readFileSync('src/main/main.js','utf8'); console.log(s.includes('const handledDeepLinkCodes = new Set();'), s.includes('handledDeepLinkCodes.has(code)'), s.includes('    onAuthenticated();'))"
```
문법OK 와 `true true true` 가 나오면 성공.
