# 작업 9 — 로그인 화면 (HTML + CSS)

**손대는 파일** (2개 모두 **신규**, 이미 있으면 통째로 덮어쓰기)
- `src/renderer/pages/login.html`
- `src/renderer/styles/login.css`

**다른 파일은 건드리지 않는다.**

## 화면 구성
```
┌──────────────────────────────┐
│ AI 회의록 녹음기        _  X │
├──────────────────────────────┤
│ 로그인                        │
│ [ 사번                     ]  │
│ [ 비밀번호                 ]  │
│ [        로그인            ]  │  ← 빨간 버튼
│ ─────────── 또는 ───────────  │
│ [     MyAccess 로그인      ]  │  ← 흰 버튼
│ (안내/오류 메시지)            │
└──────────────────────────────┘
```
- 사번 폼(사번~"또는")은 처음에 숨겨져 있다. 설정(`EMPNO_LOGIN_ENABLED`)이 켜져 있을 때만 `login.js` 가 보여준다.
- 공통 스타일(`index.css`)과 아이콘은 기존 것을 그대로 쓴다.

## 할 일

### 9-1. `src/renderer/pages/login.html`
```html
<!DOCTYPE html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>로그인</title>
    <link
      rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@100;300;400;500;700;900&display=swap"
    />
    <link rel="stylesheet" href="../styles/index.css" />
    <link rel="stylesheet" href="../styles/login.css" />
  </head>

  <body>
    <div class="title-area">
      <div class="title-left">
        <div class="title-text">AI 회의록 녹음기</div>
      </div>
      <div class="title-right">
        <button id="minimizeBtn">
          <img src="../assets/icons/minalizeBtn.svg" alt="" />
        </button>
        <button id="closeBtn">
          <img src="../assets/icons/closeBtn.svg" alt="" />
        </button>
      </div>
    </div>

    <main class="login-wrap">
      <div class="login-heading">로그인</div>

      <!-- 사번 직접 로그인. authConfig.EMPNO_LOGIN_ENABLED 가 false 면 숨긴다. -->
      <form id="empnoForm" class="login-form" hidden autocomplete="off">
        <input id="empnoInput" class="login-input" type="text" placeholder="사번" maxlength="20" />
        <input id="passwordInput" class="login-input" type="password" placeholder="비밀번호" maxlength="64" />
        <button id="empnoSubmitBtn" class="login-btn primary" type="submit">로그인</button>
        <div class="login-divider" id="loginDivider"><span>또는</span></div>
      </form>

      <button id="ssoBtn" class="login-btn sso" type="button">MyAccess 로그인</button>

      <div id="loginMessage" class="login-message" role="status" aria-live="polite"></div>
    </main>

    <script src="../scripts/login.js"></script>
  </body>
</html>
```

### 9-2. `src/renderer/styles/login.css`
```css
.login-wrap {
  width: 100%;
  flex: 1;
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
}

.login-heading {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 6px;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.login-form[hidden] {
  display: none;
}

.login-input {
  height: 40px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--dark-gray-500);
  background: #19191a;
  color: var(--white);
  font-size: 14px;
  font-family: inherit;
  outline: none;
}
.login-input:focus {
  border-color: var(--dark-gray-400);
}

.login-btn {
  height: 42px;
  border-radius: 8px;
  border: none;
  font-size: 15px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
}
.login-btn:hover {
  opacity: 0.85;
}
.login-btn:active {
  transform: scale(0.98);
}
.login-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.login-btn.primary {
  background: #f9463b;
  color: var(--white);
}
.login-btn.sso {
  background: var(--white);
  color: var(--black);
}

.login-divider {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--dark-gray-400);
  font-size: 12px;
  margin: 4px 0;
}
.login-divider::before,
.login-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--dark-gray-500);
}

.login-message {
  min-height: 36px;
  font-size: 13px;
  line-height: 1.4;
  color: var(--dark-gray-400);
  white-space: pre-line;
}
.login-message.error {
  color: #f9463b;
}
```

## 확인 방법
```bash
node -e "const fs=require('fs'); const h=fs.readFileSync('src/renderer/pages/login.html','utf8'); console.log(h.includes('empnoForm'), h.includes('ssoBtn'), h.includes('../scripts/login.js'), fs.existsSync('src/renderer/styles/login.css'))"
```
`true true true true` 가 나오면 성공.
