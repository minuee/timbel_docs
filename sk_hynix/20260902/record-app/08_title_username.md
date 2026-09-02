# 작업 8 — 타이틀에 로그인 사용자 이름 표시 (부가 작업)

**손대는 파일**
- `src/renderer/index.html` — **수정**
- `src/renderer/index.js` — **수정**

**다른 파일은 건드리지 않는다.**

> 이 작업은 로그인 기능과 무관한 부가 작업이다. 작업 1~7이 끝난 뒤에 한다.

---

## 왜 필요한가

`src/renderer/index.html` 22번째 줄에 개발자 이름이 하드코딩되어 있다.

```html
<div class="title-text">AI 회의록 녹음기(노성남)</div>
```

이걸 **로그인한 사용자 이름**으로 바꾼다.
이름을 못 가져오면 괄호 없이 `AI 회의록 녹음기` 만 나오게 한다
(하드코딩된 이름이 남는 것보다 낫다).

---

## 할 일 — 2군데 수정

### 8-1. `src/renderer/index.html` — 이름 자리 비우기

**[찾을 코드]** (22번째 줄)
```html
        <div class="title-text">AI 회의록 녹음기(노성남)</div>
```

**[바꿀 코드]**
```html
        <div class="title-text">AI 회의록 녹음기<span id="userNameLabel"></span></div>
```

> `<span>` 은 비워둔다. 값을 못 받으면 아무것도 안 보이는 게 정상이다.

---

### 8-2. `src/renderer/index.js` — 이름 채우기

**파일 맨 아래에** 아래 코드를 추가한다. (기존 코드는 건드리지 않는다)

```js
// --- 타이틀 사용자 이름 ---------------------------------------------------
// 로그인한 사용자 이름을 타이틀에 붙인다.
// 이름을 못 가져오면 아무것도 표시하지 않는다(빈 괄호가 남지 않도록).
(async () => {
  const label = document.getElementById("userNameLabel");
  if (!label) return;

  try {
    const res = await window.authAPI.getProfile();
    const userName = res && res.success && res.profile ? res.profile.userName : "";
    if (userName) label.textContent = `(${userName})`;
  } catch (_) {
    // 조회 실패는 무시한다. 이름 표시는 녹음 기능과 무관하다.
  }
})();
```

---

## 확인 방법

```bash
node -e "new (require('vm').Script)(require('fs').readFileSync('src/renderer/index.js','utf8')); console.log('문법 OK')"
grep -n "노성남" src/renderer/index.html
```

- `문법 OK` 출력
- `grep` 결과가 **아무것도 안 나오면** 성공 (하드코딩 제거됨)

앱 실행 후 로그인하면 타이틀이 `AI 회의록 녹음기(로그인한이름)` 으로 보인다.

---

## 이름이 안 나올 때

이름 표시는 아래가 모두 맞아야 동작한다. 순서대로 확인한다.

1. **작업 3의 `ME_PATH`** 가 실제 API 경로인가?
   → 로그에 `fetch_my_info_success` 가 찍히는지 확인
2. **작업 3의 `toProfile()`** 이 이름 필드를 찾고 있는가?
   → 서버 응답의 실제 필드명이 `userName`/`name`/`userNm`/`nickName` 중에 없으면
     `toProfile()` 의 후보 목록에 실제 필드명을 추가한다

**서버 스펙 확인이 안 되면** 이 작업은 8-1만 적용해도 된다.
그러면 타이틀이 `AI 회의록 녹음기` 로만 나오고, 하드코딩된 이름은 사라진다.
