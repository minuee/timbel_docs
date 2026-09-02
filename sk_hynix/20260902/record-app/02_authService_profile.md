# 작업 2 — authService 에 사용자 프로필 보관 기능 추가

**손대는 파일**: `src/main/services/authService.js` — **수정**
**다른 파일은 건드리지 않는다.**

---

## 왜 필요한가

로그인 성공 후 서버에서 내려받은 사용자 정보(이름, 이메일 등)를
앱이 살아있는 동안 들고 있어야 한다. 타이틀에 이름을 표시하거나,
업로드 시 참고하는 데 쓴다.

토큰과 같은 생명주기(앱 실행 중에만 유지, 로그아웃 시 소멸)를 가지므로
**토큰을 이미 관리하고 있는 authService 에 같이 둔다.**

> 주의: accessToken 은 렌더러로 절대 보내지 않는다(파일 상단 주석 참고).
> 하지만 **프로필은 화면에 표시해야 하므로 렌더러로 보내도 된다.**

---

## 할 일 — 3군데 수정

### 2-1. 상태 변수 추가

**[찾을 코드]** (파일 상단, 8~10번째 줄 근처)
```js
let accessToken = null;
let refreshToken = null;
let endpoint = '';
```

**[바꿀 코드]**
```js
let accessToken = null;
let refreshToken = null;
let endpoint = '';
// 로그인 사용자 정보. 화면 표시용이라 렌더러로 내보내도 되는 값만 담는다
// (토큰은 절대 여기 넣지 않는다).
let profile = null;
```

---

### 2-2. clearSession 에서 프로필도 비우기

**[찾을 코드]**
```js
function clearSession() {
  accessToken = null;
  refreshToken = null;
  endpoint = '';
}
```

**[바꿀 코드]**
```js
function clearSession() {
  accessToken = null;
  refreshToken = null;
  endpoint = '';
  profile = null;
}
```

---

### 2-3. 프로필 get/set 함수 추가 + export

**[찾을 코드]**
```js
function isAuthenticated() {
  return !!accessToken;
}
```

**[바꿀 코드]**
```js
function isAuthenticated() {
  return !!accessToken;
}

// 사용자 정보 저장. 로그인 직후 내 정보 조회에 성공하면 호출한다.
function setProfile(nextProfile) {
  profile = nextProfile || null;
}

// 사용자 정보 조회. 아직 조회 전이거나 실패했으면 null.
function getProfile() {
  return profile;
}
```

그리고 **파일 맨 아래 `module.exports` 에 두 개를 추가한다.**

**[찾을 코드]**
```js
  isAuthenticated,
  exchangeToken,
  refreshAccessToken,
};
```

**[바꿀 코드]**
```js
  isAuthenticated,
  setProfile,
  getProfile,
  exchangeToken,
  refreshAccessToken,
};
```

---

## 확인 방법

```bash
node -e "const a=require('./src/main/services/authService'); a.setProfile({userName:'홍길동'}); console.log(a.getProfile()); a.clearSession(); console.log(a.getProfile());"
```

출력:
```
{ userName: '홍길동' }
null
```
