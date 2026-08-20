# 08. 회의록 상세 로딩 지연 분석

회의록 목록에서 상세로 진입했을 때 **"데이터를 불러오는 중이에요"가 10초 이상 유지되는** 현상을 코드 기준으로 추적한 결과다. 2026-08-20, `release` 브랜치 정적 코드 리딩.

**대상**: `src/Pages/Contents/ContentDetail.jsx` (1235줄) / 라우트 `/content/:contentId` (`src/App.js:102`)

---

## 한 줄 결론

상세 페이지는 **전사 전문까지 포함한 단일 API 한 방**에 전부 의존하고, 그 응답 뒤에 **재생 쿠키 발급 POST가 직렬로 한 번 더** 붙은 뒤에야 로딩이 해제된다. 게다가 마운트 시 이 왕복이 **최대 3회 중복** 발사되며, axios 타임아웃이 없어 둘 중 하나라도 늦으면 로딩 화면이 그대로 고정된다.

1. 재생 쿠키 발급을 로딩 해제 경로에서 분리 — 왕복 1회 즉시 단축
2. axios 타임아웃 지정 — 무한 로딩 차단
3. 마운트 중복 호출 제거 — 무거운 GET 3회 → 1회
4. (BE 협의) 세그먼트 분리 제공 — 근본 해법

---

## 1. 호출 API

탭(전체 요약·북마크·메모·노트)과 우측 음성기록 패널은 **별도 호출 없이** ① 응답을 props로 쪼개 쓰기만 한다. 노트만 탭 진입 시 따로 가져온다.

| | 요청 | 역할 | 정의 위치 |
|---|---|---|---|
| ① | `GET /api/contents/{id}?source=none` | **상세 전량.** meta · file · aiResult · **segments / mergedSegments(전사 전문)** · bookmarks · memos · highlights · contentLifecycleActions | `ContentsStore.js:114-167` |
| ② | `POST /api/contents/{id}/stream-grant` | 오디오 재생용 콘텐츠별 grant 쿠키 발급. **①의 200 응답 안에서 `await`로 호출** | `requestUtil.js:188-199`<br>`ContentDetail.jsx:296` |
| ③ | `GET /api/contents/{id}/note` | 노트 탭 진입 시에만 지연 호출. 초기 로딩과 무관 | `ContentsStore.js:1013` |

즉 **회의가 길수록(세그먼트 수천 개) ①의 응답 크기와 시간이 그대로 화면 대기 시간**이 된다. 화면을 부분적으로라도 먼저 그릴 수 있는 분할 지점이 API 레벨에 존재하지 않는다.

전사 패널이 ① 응답을 그대로 받아 쓰는 지점:

```jsx
// ContentDetail.jsx:1152
<Transcription
  data={content?.mergedSegments ?? content?.segments}
  bookmarks={content?.bookmarks?.filter(b => b.key === 'mergedSegments')?.[0]?.data}
  speakerInfo={content?.speakerInfo}
  isMemo={content?.memos}
  ...
/>
```

---

## 2. 렌더 구조 — 페이지 전체가 하나의 로딩 게이트에 묶여 있다

```
ContentDetail
├─ {content && <Header/>}          ← :765  content 없으면 헤더·제목조차 안 그림
└─ <Stack>
   └─ {isReSummarizing || isLoading      ← :941  단일 전역 게이트
        ? <PageLoading/>                 "데이터를 불러오는 중이에요"
        : status.code === 200
            ? <본문 전체 · 탭 · 전사 패널>
            : drawContentStatus()}       ← :683  422 처리중 / 에러 / 빈 화면
```

스켈레톤이나 부분 렌더 개념이 없다. `isLoading`은 `useState(true)`로 시작해 **오직 `refreshContent`의 `.finally()`에서만 해제**되고(`:112`, `:333`), 그때까지 헤더를 포함한 화면 100%가 `PageLoading` 한 장으로 대체된다.

> **참고**: `PageLoading`은 노출 자체가 1초 지연이다(`PageLoading.js:39-46`). 따라서 "10초 노출"은 실제로는 **11초 이상의 대기**를 뜻한다.

---

## 3. 마운트 한 번에 벌어지는 일

```
useLayoutEffect []      ├──── GET contents/{id} (전사 전문) ────┤──grant──┤
  :176

useEffect [권한]        ├──── GET contents/{id} · 중복 ────────┤──grant──┤
  :181 (마운트 시 동시)

권한 플립 재발사                                                ├──── GET · 중복 ────┤──grant──┤
  :202 → :181
                                                    ↑                    ↑
                                            데이터 도착           setLoading(false)
                                          (화면은 아직 로딩)        여기서야 해제
```

막대는 실측이 아니라 **직렬/병렬 관계**를 나타낸다. 핵심은 상세 데이터가 도착한 뒤에도 `stream-grant` 왕복이 끝나야 로딩이 풀린다는 점, 그리고 같은 무거운 GET이 마운트 한 번에 최대 3회 나간다는 점이다.

---

## 4. 원인

### 🔴 4-1. 재생 쿠키 POST가 로딩 해제 경로에 직렬로 끼어 있음

`ContentDetail.jsx:296`, `:333`

```js
case 200:
  await request.ensureStreamGrant(...);   // :296 ← 왕복 1회 추가
  setStatus({ code: 200 }); setContent(data.data);
  ...
.finally(() => setLoading(false));        // :333
```

상세 데이터는 이미 도착했는데도, **오디오 재생용 쿠키 발급 POST가 끝날 때까지 로딩 화면이 유지**된다. 요약·전사 텍스트를 읽는 데는 전혀 필요 없는 요청이다.

**영향**: 모든 상세 진입에 네트워크 왕복 1회분이 무조건 가산된다.

### 🔴 4-2. axios 타임아웃이 어디에도 설정돼 있지 않음

`requestUtil.js:59-111`

`GET`·`POST` 등 모든 헬퍼가 `timeout` 옵션 없이 axios를 직접 호출한다. 상세 GET이든 `stream-grant`든 **하나가 응답하지 않으면 `.finally`가 영원히 실행되지 않아 로딩이 무한 유지**된다.

**영향**: "10초 이상"이 특정 회의록에서만 재현된다면 이쪽일 가능성이 크다. 사실상 무한 대기이고, 사용자에게 실패를 알릴 방법도 없다.

### 🟠 4-3. 마운트 시 상세 API가 2~3회 중복 호출

`ContentDetail.jsx:176-178`, `:181-183`, `:202`

```js
useLayoutEffect(() => { loadContent(); }, []);                    // :176
useEffect(() => { loadContent(); }, [auth.isContentPermission]);  // :181 ← 마운트 때도 실행
```

두 이펙트가 마운트 시 **동시에** 발사된다. 더해서 `[content]` 이펙트가 `updateContentPermission(...)`을 호출하고(`:202`), `auth.isContentPermission`이 초기값 `false`(`AuthStore.js:14`)에서 뒤집히면 두 번째 이펙트가 **한 번 더** 재발사된다.

결과적으로 무거운 GET 최대 3회 + `stream-grant` 3회. 인플라이트 가드도 `AbortController`도 없어 응답 경합이 발생한다.

**영향**: 서버 부하 3배, 네트워크 경합으로 첫 응답 자체가 느려진다.

### 🟡 4-4. 모든 상호작용이 전체 페이로드를 재조회

`ContentDetail.jsx:392`, `:723`, `:1163`

북마크 토글, 하이라이트 추가·삭제, 메모 저장, 전사 편집이 전부 `refreshContent(contentId)` → **전사 전문 포함 전체 재조회**로 이어진다. `isLoading`을 다시 세우진 않아 로딩 화면이 뜨진 않지만, 매 동작마다 대용량 왕복이 발생한다.

**영향**: 초기 진입 이후의 체감 반응성 저하, 불필요한 트래픽.

### 🔵 4-5. 단일 게이트 — 먼저 보여줄 수 있는 것도 함께 막힌다

`ContentDetail.jsx:765`, `:941`

제목·생성일·최종수정일 같은 `meta` 정보는 응답 앞부분에 이미 있음에도, 헤더 자체가 `{content && ...}`로 막혀 있어 **아무것도 그려지지 않는다**. 사용자에게는 "클릭했는데 빈 화면 + 로딩"으로만 보인다.

**영향**: 실제 지연보다 체감 지연이 더 크게 느껴지는 직접적 원인.

---

## 5. 부수 발견

### 도달하지 않는 `case 413` — 삭제된 회의록이 일반 에러로 표시

`drawContentStatus()`의 `case 413`(`:688`)은 스토어가 반환하지 않는 코드다. 삭제 콘텐츠는 `423`으로 오는데(`ContentsStore.js:154-156`), `423`은 `default`로 빠져 "삭제된 회의록" 대신 **일반 에러 화면**이 노출된다.

### UUID가 아닌 `contentId` → 영구 로딩

```js
const loadContent = () => {
  const contentId = location.pathname.split('/')[2];
  if (contentId && isUUID(contentId)) {   // :171
    refreshContent(contentId);
  }
  // else: 아무 일도 일어나지 않는다 → isLoading이 true로 고정
};
```

`isUUID`가 false면 `refreshContent`를 아예 호출하지 않아 **영영 "데이터를 불러오는 중이에요"만 노출**된다. 에러 화면으로도 빠지지 않는다.

---

## 6. 개선 우선순위

| | 조치 | 대상 | 기대 효과 | 비용 |
|---|---|---|---|---|
| 1 | **stream-grant를 로딩 해제 경로에서 분리** — `await` 제거(fire-and-forget) 또는 `setContent` 이후로 이동 | `ContentDetail.jsx:296` | 모든 진입에서 왕복 1회분 단축 | FE · 2줄 |
| 2 | **axios 인스턴스에 `timeout` 지정** — 초과 시 에러 화면 전환 | `requestUtil.js:59-111` | 무한 로딩 차단, 실패를 사용자에게 노출 | FE · 소 |
| 3 | **마운트 중복 호출 제거** — 진입 로드는 `useLayoutEffect` 하나로 통합, 권한 이펙트는 `useRef`로 초기 마운트 스킵 | `ContentDetail.jsx:176-183` | 무거운 GET 3회 → 1회 | FE · 소 |
| 4 | **전역 로딩 게이트 해체** — `content?.meta` 도착 시 헤더·탭 먼저 렌더, 전사 패널만 개별 로딩 | `ContentDetail.jsx:765`, `:941` | 체감 지연 대폭 감소 (실효는 5번 선행 필요) | FE · 중 |
| 5 | **세그먼트 분리 제공 요청** — `GET contents/{id}`에서 전사 세그먼트를 별도 엔드포인트 또는 페이징으로 | BE 협의 | **근본 해법.** 응답 크기 자체를 줄임 | BE · 대 |
| 6 | **부수 수정** — `423` → 삭제 화면 매핑, 비-UUID 시 에러 화면 전환 | `ContentDetail.jsx:171`, `:688` | 잘못된 화면·영구 로딩 제거 | FE · 소 |

**1~3번은 FE 단독으로 즉시 적용 가능**하며, 이것만으로 "데이터를 불러오는 중"이 걸리는 시간이 한 왕복 + 경합만큼 줄어든다. 4번은 5번이 선행되어야 실효가 있으므로 BE 협의를 함께 시작하는 편이 좋다.

---

## 남은 확인 사항

본 분석은 정적 코드 리딩 기준이다. **실제 지연의 구성비(① 응답 시간 vs ② 직렬 왕복 vs 중복 호출 경합)는 측정하지 않았다.** 브라우저 Network 탭에서 상세 진입 1회를 캡처하면 바로 확정할 수 있다.

관련 문서: [03-data-flow.md](./03-data-flow.md) · [07-risks-todo.md](./07-risks-todo.md)
