> 📄 문서 보기: https://claude.ai/code/artifact/f06c906e-be4f-4fb9-a20f-d28f2da04d85?via=auto_preview

# 모바일 녹음 업로드 중단 (E2126)

**앱 진행률 66% 고정 · 오류코드 E2126**

음성 파일은 오브젝트 스토리지에 정상 업로드됐으나, **바로 다음 단계인 음성 길이(duration) 추출에서 실패**해 DB 저장 이후 공정이 전혀 실행되지 않았습니다. 스토리지에는 파일이 남고 DB에는 아무 기록도 없는 상태입니다.

---

## 중단 지점

| | 단계 | 상태 |
|---|---|---|
| ① | 앱이 암호화 조각 업로드 (3분치씩) | 정상 |
| ② | 조각 병합 · 복호화 · FLAC 변환 | 정상 |
| ③ | 오브젝트 스토리지 업로드 | 정상 |
| **✕** | **음성 길이(duration) 추출 — ffprobe** | **E2126 실패** |
| ④ | MariaDB `content` 저장 | 미실행 |
| ⑤ | MongoDB `file` 저장 | 미실행 |
| ⑥ | MongoDB `transcribeResult` 생성 | 미실행 |
| ⑦ | STT 엔진 작업 요청 | 미실행 |
| ⑧ | 진행률 폴링 · 앱 푸시 | 미실행 |
| ⑨ | STT 결과 저장 · 요약 | 미실행 |

`src/services/system/drive.service.js:77-78`

③번과 ④번 사이에 음성 길이를 재는 단계가 있습니다. 여기서 예외가 발생하면 이후 공정 전체가 시작되지 않으므로, **DB·STT 어디에도 흔적이 남지 않습니다.** 확인된 세 가지 증상(MariaDB 없음 · MongoDB 없음 · 로그 없음)이 모두 이 하나로 설명됩니다.

---

## 근본 원인

길이 측정 실패 시의 반환값이 잘못돼 있습니다. 호출부는 객체를 기대하는데 숫자 `0`을 돌려줍니다.

```js
// src/utils/file/media.util.js:20
async getFileMeta(path) {
  try {
    const ffprobeResult = await this.ffprobe(path);
    ...
    return { duration: duration * 1000, creationTime };
  } catch (err) {
    log.e('[MediaUtils : getDuration] error : ', err.message);
    return 0;   // ← 객체가 아닌 숫자를 반환
  }
}
```

```js
// src/utils/file/media.util.js:58
const { duration, creationTime } = await this.getFileMeta(tempFilePath);
// 숫자 0을 구조분해 → duration === undefined

data.duration = duration;
if (isNaN(data.duration)) {      // isNaN(undefined) === true
  throw new HttpError(1126);     // E2126 · HTTP 500
}
```

원래 의도는 *"길이를 못 재면 0으로 처리"* 였던 것으로 보이나, 실제 동작은 **업로드 전체 실패**입니다. ffprobe가 한 번이라도 실패하면 무조건 이 경로를 탑니다.

---

## 부수 피해

| 항목 | 상태 |
|---|---|
| 스토리지 음성 파일 | 업로드된 채 **방치**. 롤백 코드가 DB 저장 이후 실패만 처리하므로 이 시점 실패는 정리되지 않습니다 (`drive.service.js:130`) |
| MariaDB / MongoDB | 기록 없음. 관리 화면에서 조회·삭제 불가능한 고아 파일이 됩니다 |
| 사용자 알림 | 실패 알림이 발송되지 않습니다. 알림 코드 역시 DB 저장 이후 경로에만 있습니다 |
| 앱 화면 | 완료도 실패도 받지 못해 진행률이 고정된 채 유지됩니다 |

---

## 확인 방법

서버 로그에서 다음 문구를 검색하면 실패 여부와 실제 사유가 함께 확인됩니다.

```
[MediaUtils : getDuration] error :
```

뒤에 출력되는 메시지가 진짜 원인입니다. 아래 두 갈래로 나뉩니다.

- **ffprobe 실행 자체가 실패** — 바이너리 부재, 권한, 컨테이너 환경 문제
- **변환된 FLAC 파일이 손상** — 조각 병합 또는 복호화 단계의 결함

같은 시각의 `[DriveUtil : put] File Uplaod OK` 로그로 스토리지 업로드 성공 시점을 함께 확인할 수 있습니다. *(코드상 `Upload`가 아닌 `Uplaod` 오타이므로 검색 시 주의)*

---

## 조치 제안

배포 가능 시점에 아래 순서로 처리하는 것을 권장합니다.

1. **원인 제거** — ffprobe 실패 사유를 로그로 확정한 뒤 해소
2. **반환값 정정** — `getFileMeta`의 `return 0`을 `{ duration: 0, creationTime: null }` 형태로 수정
3. **롤백 범위 확대** — 스토리지 업로드 이후 실패 시 업로드된 파일을 정리하도록 보완
4. **실패 통지** — 이 경로의 실패도 앱에 전달되도록 알림 추가

---

## 앱 측 확인 요청

백엔드는 이 건에서 진행률을 전송한 적이 없습니다. 진행률 푸시는 STT 단계(⑧)에서만 발생하는데, 그 단계에 도달하지 못했기 때문입니다. 따라서 **66%는 앱이 자체 계산한 값**입니다. 프론트엔드에 다음 두 가지를 확인해 주십시오.

- 진행률 계산식 — 전송 성공한 조각 수 기준인지 여부
- **HTTP 500 · errorCode E2126 수신 시의 처리** — 에러를 받고도 실패 화면으로 전환하지 않는다면 별도 보완이 필요합니다

---

**근거 파일** — `src/services/system/drive.service.js` · `src/utils/file/media.util.js` · `src/handlers/error.handler.js`
