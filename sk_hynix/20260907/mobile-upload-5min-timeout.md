# 모바일 업로드 5분 타임아웃 점검

**Node `requestTimeout` 기본값 300초 · 대용량 녹음 업로드 예방 점검**

모바일 앱의 간헐적 업로드 실패(broken pipe)에 대한 **확정 원인은 아직 규명 중**입니다. 이 문서는 그와 별개로, 현재 이 백엔드에 **요청 하나당 5분 상한**이 걸려 있는 상태를 기록하고 예방 조치를 정리한 것입니다.

대상 API — `POST /contents/upload/encryption/files`

---

## 1. 현재 상태

`src/app.js:69`

```js
app.listen(process.env.PORT ?? 9010, '0.0.0.0', async () => {
```

서버 타임아웃 설정이 없습니다. `ecosystem.config.cjs`와 환경변수에도 없습니다. 따라서 **Node.js 기본값이 그대로 적용**됩니다.

| 항목 | 값 | 근거 |
|---|---|---|
| 런타임 | Node 20 | `Dockerfile.public:51` (`node:20-alpine`) |
| **`server.requestTimeout`** | **300초 (5분)** | Node 18+ 기본값 |
| `server.headersTimeout` | 60초 | Node 기본값 |
| multer 업로드 타임아웃 | 3시간 | `src/utils/file/multer.util.js:5` |
| multer 파일 크기 제한 | 2GB | `src/utils/file/multer.util.js:104` |

> **주의** — Node 16까지 `requestTimeout` 기본값은 `0`(무제한)이었습니다. **Node 18에서 300초로 변경**되었습니다. 애플리케이션 코드 변경 없이 **런타임 업그레이드만으로 이 제한이 생깁니다.**

---

## 2. `requestTimeout`의 의미

**요청 본문 전체를 수신 완료하는 데 허용되는 총 시간**입니다.

- 유휴(idle) 시간이 아닙니다. **데이터가 계속 흐르고 있어도** 300초가 지나면 종료됩니다.
- 초과 시 Node가 소켓을 종료하며, 전송 중이던 클라이언트는 **broken pipe(EPIPE)** 를 받습니다.
- **파일 크기 제한이 아니라 전송 시간 제한**입니다. 크기가 아무리 커도 5분 안에 끝나면 통과하고, 작아도 5분을 넘기면 끊깁니다.

### multer의 3시간 타임아웃은 동작하지 않습니다

`src/utils/file/multer.util.js:189-207`의 3시간 타이머는 **도달할 수 없습니다.** Node가 300초에 먼저 연결을 끊기 때문입니다.

또한 이 타이머는 만료되더라도 연결을 끊지 않고 정상 응답을 보냅니다.

```js
// src/utils/file/multer.util.js:194-199
if (!res.headersSent) {
    res.status(200).json({
        message: '업로드 시간이 초과되었습니다.',
        httpCode: 408,
    });
}
```

즉 **애플리케이션 코드에는 연결을 강제 종료하는 경로가 존재하지 않으며**, 이 백엔드가 연결을 끊을 수 있는 유일한 조건은 **Node 기본 `requestTimeout` 300초 초과**입니다.

---

## 3. 회의 길이별 필요 최소 업로드 속도

**전제** — 3분 조각 1개 ≈ 17MB (분당 약 5.67MB). 실측이 아닌 추정치입니다.

**5분(300초) 안에 전송을 끝내려면 아래 속도를 300초 내내 유지**해야 합니다.

| 회의 길이 | 조각 수 | 전송량 | **필요 최소 속도** | 모바일 데이터 환경 |
|---|---:|---:|---:|---|
| 10분 | 4 | 57 MB | **1.5 Mbps** | 여유 |
| 20분 | 7 | 113 MB | **3.0 Mbps** | 여유 |
| 30분 | 10 | 170 MB | **4.5 Mbps** | 대체로 가능 |
| 51분 | 17 | 289 MB | **7.7 Mbps** | **경계선** |
| 1시간 | 20 | 340 MB | **9.1 Mbps** | 빠듯함 |
| 1시간 30분 | 30 | 510 MB | **13.6 Mbps** | 어려움 |
| 2시간 | 40 | 680 MB | **18.1 Mbps** | 양호한 5G에서만 |
| 2시간 30분 | 50 | 850 MB | **22.7 Mbps** | 어려움 |
| **3시간 (최대)** | 60 | 1,020 MB | **27.2 Mbps** | 사실상 불가 |

### 참고 — 모바일 데이터 업로드 속도 통상치

업로드(상향)는 다운로드보다 통상 1/3~1/5 수준입니다.

| 환경 | 업로드 속도 |
|---|---|
| 5G 실외 양호 | 20~40 Mbps |
| 5G 실내 | 5~20 Mbps |
| LTE 실외 양호 | 10~20 Mbps |
| **LTE 실내 / 혼잡** | **1~5 Mbps** |
| 지하·건물 안쪽·이동 중 | 1 Mbps 이하 |

### 해석

- **30분 이하** 회의는 대부분의 모바일 환경에서 5분 안에 완료됩니다.
- **50분~1시간** 구간이 경계선입니다. 회선 상태에 따라 성공과 실패가 갈립니다.
- **1시간 30분 이상**은 모바일 데이터로 5분 내 완료가 현실적으로 어렵습니다.

사내 폐쇄망은 WiFi를 사용할 수 없어 **모바일 앱은 전량 셀룰러로 업로드**합니다. 반면 웹은 유선랜을 사용하므로 289MB 기준 5~30초면 전송이 끝나 300초에 도달할 여지가 없습니다.

또한 같은 건물에서 여러 명이 동시에 업로드하면 **같은 기지국 셀의 상향 용량을 나눠 쓰게 되어 개인당 속도가 떨어집니다.** 월요일 오전처럼 회의가 몰리는 시간대에 실패가 집중되는 현상과 방향이 일치합니다.

---

## 4. 미확정 사항

아래는 아직 확인되지 않았으며, 원인 확정을 위해 필요한 항목입니다.

### 4-1. 웹 트래픽도 DMZ WAF를 경유하는가

현재 확인된 경로는 다음과 같습니다.

| 구분 | 회선 | DMZ WAF | 증상 |
|---|---|---|---|
| **모바일 앱** | 셀룰러 (WiFi 불가) | **경유** | 간헐적 실패 |
| **웹** | 유선랜 | **미확인** | 정상 |

모바일만 실패하는 원인이 **회선 속도** 때문인지 **WAF 경유** 때문인지, 두 변수가 겹쳐 있어 현재 데이터로는 분리되지 않습니다.

**웹이 DMZ WAF를 경유하는지 여부**가 확인되면 이 구분에 도움이 됩니다.

- 웹도 경유하는데 정상 → 속도(시간) 요인 쪽에 무게
- 웹이 미경유 → 두 요인 분리 불가, 별도 실험 필요

### 4-2. WAF `http overflow` 룰의 실제 임계값

인프라팀 모니터링에서 해당 API가 `http overflow`로 차단된 기록이 캡쳐되었으나, **임계값과 차단된 요청의 크기(bytes)는 아직 공유되지 않았습니다.**

다만 **2시간 회의(약 680MB)가 단일 요청으로 같은 경로를 통과한 사례**가 있어, 단순 body size 임계값으로는 설명되지 않습니다. 191MB 지점에서 끊긴 건과 양립할 수 없기 때문입니다.

**인프라팀 확인 요청 항목**

1. `http overflow`로 차단된 요청의 **크기(bytes)** 와 **해당 룰의 임계값**
2. L4/WAF의 **세션 타임아웃** 설정값
3. 웹 트래픽의 DMZ WAF 경유 여부

### 4-3. 실패까지 걸린 시간

가장 결정적인 데이터입니다. 앱에서 **업로드 시작부터 broken pipe까지의 소요 시간**이 확인되면 판별됩니다.

- **300초 부근에 집중** → 본 문서의 `requestTimeout`이 원인
- **300초와 무관하게 분포** → 이 백엔드는 연결을 끊을 수단이 없으므로 중간 구간 요인

### 4-4. 분리 실험

변수를 하나만 바꾸는 방법입니다.

> **사외에서 WiFi에 연결한 모바일 앱으로 대용량 회의를 업로드한다.**

경로는 동일하게 DMZ WAF를 거치고 **회선 속도만 빨라집니다.**

- 성공 → 전송 시간 요인
- 실패 → WAF 요인

---

## 5. 조치 방안

원인 확정 여부와 무관하게, 대용량 업로드를 받는 API에 5분 상한이 걸려 있는 것은 **요구사항과 맞지 않으므로** 조정이 필요합니다.

### 5-1. 서버 타임아웃 명시 — 수정 1건

수정 파일 — `src/app.js:69-72`

#### 변경 전

```js
app.listen(process.env.PORT ?? 9010, '0.0.0.0', async () => {
	log.i(`Listening on ${process.env.PORT}`);
	await discovery.registerService();
});
```

#### 변경 후

```js
const server = app.listen(process.env.PORT ?? 9010, '0.0.0.0', async () => {
	log.i(`Listening on ${process.env.PORT}`);
	await discovery.registerService();
});

// 대용량 업로드 대응: 요청 수신 제한시간 확대 (기본 30분)
server.requestTimeout = Number(process.env.REQUEST_TIMEOUT ?? 30 * 60 * 1000);
server.headersTimeout = 65 * 1000;
```

`app.listen(` 앞에 `const server = `를 붙이고, 닫는 `});` 뒤에 두 줄을 추가하는 것이 전부입니다.

#### 설정값 선택 기준

최대 케이스인 **3시간 회의(1,020MB)** 를 기준으로, 각 설정이 요구하는 최소 업로드 속도입니다.

| `requestTimeout` | 3시간 회의 전송에 필요한 속도 | 판단 |
|---|---|---|
| **5분** (현재 기본값) | 27.2 Mbps | 모바일에서 사실상 불가 |
| **30분** | **4.5 Mbps** | 대부분의 환경에서 통과 |
| **60분** | **2.3 Mbps** | 혼잡한 환경에서도 통과 |

- **30분이면 최악 케이스까지 커버**됩니다. 여유를 두려면 60분도 무리 없습니다.
- `0`(무제한)은 권장하지 않습니다. 끊기지 않는 연결이 누적될 수 있습니다.
- `headersTimeout`은 `requestTimeout`보다 작아야 합니다.
- 환경변수 `REQUEST_TIMEOUT`으로 재배포 없이 조정할 수 있도록 해두었습니다.

> **memoryStorage 상태에서 타임아웃만 늘릴 경우 주의** — 느린 업로드가 메모리를 그만큼 오래 점유하게 되어, 아래 5-2의 PM2 3GB 제한에 닿을 여지가 커집니다. 5-2를 함께 적용하면 이 문제는 사라집니다.

### 5-2. 디스크 스토리지 전환 — 수정 2건

#### 현재 상태

multer에 storage 지정이 없어 **memoryStorage로 동작**하며, 업로드 파일 전체가 프로세스 메모리에 적재됩니다. `src/utils/file/media.util.js:84`가 `fileList[i].buffer`를 사용하는 것으로 확인됩니다.

한편 `ecosystem.config.cjs`는 다음과 같습니다.

```js
instances: 1,
exec_mode: 'fork',
max_memory_restart: '3G',
```

**단일 프로세스**이므로 동시 업로드 용량 합계가 3GB를 넘으면 PM2가 프로세스를 재시작하고, **진행 중이던 모든 업로드가 동시에 끊깁니다.** 1시간 회의(340MB) 기준 8건 정도가 겹치면 도달 가능한 수치입니다.

#### 영향 범위

`uploadFiles()`는 **`src/routes/content.router.js:10` 한 곳에서만** 사용됩니다. 단일 파일·썸네일·텍스트·연락처 업로드는 각각 별도의 multer 인스턴스를 사용하므로 **영향받지 않습니다.**

이 흐름에서 `.buffer`를 참조하는 지점도 `media.util.js:84` 하나뿐입니다. 따라서 **수정 파일은 2개**입니다.

#### 수정 ① — `src/utils/file/multer.util.js`

**변경 전** (`101-107행`)

```js
uploadFiles() {
	return multer({
		limits: {
			fileSize: 2 * 1024 * 1024 * 1024,
		},
	}).array('files');
}
```

**변경 후**

```js
// 파일 상단
import fs from 'fs';

const UPLOAD_TMP_DIR = process.env.UPLOAD_TMP_DIR ?? '/usr/src/app/tmp/upload/';
fs.mkdirSync(UPLOAD_TMP_DIR, { recursive: true });   // multer는 폴더를 생성하지 않음
```

```js
uploadFiles() {
	return multer({
		storage: multer.diskStorage({
			destination: (req, file, cb) => cb(null, UPLOAD_TMP_DIR),
			filename: (req, file, cb) =>
				cb(null, `${Date.now()}-${Math.random().toString(36).slice(2)}`),
		}),
		limits: {
			fileSize: 2 * 1024 * 1024 * 1024,
		},
	}).array('files');
}
```

#### 수정 ② — `src/utils/file/media.util.js:77-91`

**변경 전**

```js
async parsePcmFile(filePath, fileList, num = null, totalNum, originalnames) {
	try {
		for (let i = 0; i < fileList.length; i++) {
			const fragmentFilePath = path.join(
				filePath,
				num ? `${num}_${totalNum}_${originalnames[i]}` : originalnames[i]
			);
			await fs.promises.writeFile(fragmentFilePath, fileList[i].buffer);
		}
	} catch (err) {
		await fs.promises.rm(fragmentFilePath, { force: true }).catch(() => {});
		log.e('[MediaUtil : parsePcmFile] error : ', err.message);
		throw err;
	}
}
```

**변경 후**

```js
async parsePcmFile(filePath, fileList, num = null, totalNum, originalnames) {
	let fragmentFilePath;
	try {
		for (let i = 0; i < fileList.length; i++) {
			fragmentFilePath = path.join(
				filePath,
				num ? `${num}_${totalNum}_${originalnames[i]}` : originalnames[i]
			);
			await fs.promises.rename(fileList[i].path, fragmentFilePath);
		}
	} catch (err) {
		if (fragmentFilePath) await fs.promises.rm(fragmentFilePath, { force: true }).catch(() => {});
		log.e('[MediaUtil : parsePcmFile] error : ', err.message);
		throw err;
	}
}
```

버퍼를 파일로 쓰는 대신, multer가 이미 디스크에 저장한 파일을 **이동(rename)** 시킵니다.

> **함께 해결되는 기존 결함** — 변경 전 코드의 `catch` 블록이 참조하는 `fragmentFilePath`는 `for` 루프 안에서 `const`로 선언되어 **스코프 밖**입니다. 예외 발생 시 `ReferenceError`가 발생하며 원래 오류가 가려집니다. 위와 같이 선언을 밖으로 빼면 해소됩니다.

#### 수정 ③ (선택) — `Dockerfile.public:84`

```dockerfile
RUN mkdir -p /usr/src/app/tmp/pcm /usr/src/app/tmp/flac /usr/src/app/tmp/upload
```

위 `mkdirSync`로도 처리되지만 명시해두는 편이 안전합니다.

#### 주의 — 동일 파일시스템에 배치

`fs.rename`은 파일시스템이 다르면 `EXDEV` 오류로 실패합니다. `PCM_DIR=/usr/src/app/tmp/pcm/` 과 같은 볼륨인 `/usr/src/app/tmp/upload/` 를 사용하면 안전하며, 복사가 아닌 이동이므로 즉시 완료됩니다.

#### 남는 메모리 사용처

조각 병합 이후 `createUploadContentFile`(`drive.service.js:165-179`)이 변환된 FLAC 파일을 메모리로 읽어 스토리지에 업로드합니다. 다만 이는 **업로드 순간에만 점유**되므로, 원본 PCM 전체를 전송 시간 내내(수 분간) 들고 있는 현재 구조와는 부담이 다릅니다.

참고로 같은 함수의 `Buffer.from(data)`는 `fs.promises.readFile`이 이미 Buffer를 반환하므로 **불필요한 복제**입니다. 순간적으로 FLAC 크기의 2배를 점유합니다.

#### 참고 — 현재 상태 확인 방법

운영 서버에서 `pm2 list`의 재시작 횟수(↺)가 배포 횟수보다 크게 높다면 메모리 초과로 인한 재시작을 의심할 수 있습니다. `pm2 describe master-api`로 재시작 시각까지 확인 가능합니다.

### 5-2-1. 서버 메모리 구성 참고

운영 서버는 **32GB RAM · swap 없음** 구성입니다.

| 항목 | 평가 |
|---|---|
| **swap 없음** | **문제 없습니다.** 서버 용도에서는 오히려 권장됩니다. swap이 걸리면 응답 지연이 급격히 악화되므로, 스와핑에 의존하느니 빠르게 실패하는 편이 낫습니다. |
| **32GB** | 충분합니다. |
| **PM2 `max_memory_restart: '3G'`** | **실질적인 제약은 여기입니다.** 서버에 32GB가 있어도 이 프로세스는 3GB에서 재시작됩니다. |

즉 메모리 부족의 원인이 있다면 그것은 서버 사양이 아니라 **PM2 설정값**입니다. 커널 OOM Killer가 개입하기 훨씬 이전에 PM2가 먼저 프로세스를 재시작하므로, swap 부재로 인한 위험은 사실상 없습니다.

디스크 스토리지로 전환하면 업로드 크기가 메모리에 영향을 주지 않으므로 `max_memory_restart` 조정도 불필요해집니다. 전환하지 않고 타임아웃만 늘릴 경우에는, 다른 컨테이너의 사용량을 확인한 뒤 이 값을 상향하는 방안을 함께 검토할 수 있습니다.

### 5-3. 앱 측 보완 (중기)

- 조각을 **여러 요청으로 나누어 전송** — 서버는 이미 이를 지원합니다. `src/services/system/drive.service.js:220-224`에서 조각을 `pcmDir`에 누적하고 부족분을 `missingFiles`로 응답합니다. 요청당 전송 시간이 짧아져 타임아웃 위험이 줄어듭니다.
- **재시도 로직** — 실패 시 이미 전송된 조각을 건너뛰고 이어서 전송

---

## 관련 파일

| 파일 | 내용 |
|---|---|
| `src/app.js:69` | 서버 기동, 타임아웃 미설정 |
| `src/utils/file/multer.util.js:5` | 업로드 타임아웃 상수 |
| `src/utils/file/multer.util.js:101-107` | `uploadFiles` — storage 미지정 |
| `src/utils/file/multer.util.js:189-207` | `uploadFilesWithTimeout` |
| `src/routes/content.router.js:8-12` | 대상 라우트 |
| `src/controller/content/upload.controller.js:125-168` | `uploadEncryptionFilesContent` |
| `src/services/system/drive.service.js:196-243` | 조각 누적·병합 처리 |
| `src/utils/file/media.util.js:77-91` | `parsePcmFile` — 버퍼 사용 |
| `ecosystem.config.cjs` | PM2 설정 |
| `Dockerfile.public:51` | Node 20 |
