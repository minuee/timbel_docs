# 포털 인증서비스 — 참고 구현 (FastAPI)

`auth_architecture_v4.pptx` **슬라이드 25 「인증서버 담당에게 요청할 것」** 의 참고 구현입니다.
요청 내용·배경·우선순위는 PPT를 보시면 되고, 이 폴더는 **"그래서 코드로는 대략 이런 모양"** 을 보여주는 용도입니다.

> ⚠️ 그대로 도입하라는 코드가 아닙니다. 현행 인증서버(`AUTH_HOST` / `USER_HOST`) 소스를 보지 못한 상태에서
> 작성했으므로, 실제 반영은 기존 코드 구조에 맞춰 담당자께서 판단해 주세요.
> 특히 rotation·재사용 감지·grace 윈도우의 **동작 규칙**을 참고 지점으로 봐주시면 됩니다.

---

## 1. PPT 요청 항목 ↔ 코드 위치

| # | PPT 슬라이드 25 요청 항목 | 구현 위치 |
|---|---|---|
| 1 | `/auth/refresh` 재발급 엔드포인트 (현재 부재) | `app/routers/auth.py` → `app/service.py: AuthService.refresh()` |
| 2 | JWKS 공개키 배포 (`/.well-known/jwks.json`) | `app/routers/jwks.py`, `app/keys.py` |
| 3 | Refresh Rotation + 재사용 감지 | `app/service.py: _rotate()` / `_replay_or_detect_reuse()` |
| 4 | Grace 윈도우 (동일 refresh 재요청 → 동일 토큰 쌍) | `app/service.py: _replay_or_detect_reuse()`, `app/store.py: mark_rotated()` |
| 5 | TTL 실설정 확인·정정 (정책 60분/14일 ≠ 실측 20분/65분) | `app/config.py`, `.env.example` — 수명은 전부 설정값 |
| 6 | 쿠키 세팅 주체·방식 협의 | `app/cookies.py` — `COOKIE_ENABLED=false` 면 인증서버는 JSON만 주고 앱 백엔드가 Set-Cookie |

부록 C(세션 정책: 유휴 타임아웃·절대 만료·세션/지속 쿠키)도 전부 **코드가 아니라 `.env` 설정값**으로 빠져 있습니다.
정책이 합의되면 값만 바꾸면 됩니다.

## 2. 돌려보기

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python scripts/gen_keys.py keys/private.pem   # RS256 키쌍 생성
cp .env.example .env                                    # 필요시 값 조정
.venv/bin/uvicorn app.main:app --port 8000              # Redis 필요 (REDIS_URL)
```

```bash
# 로그인 (데모 계정)
curl -i -X POST localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"account":"agent01","password":"password"}'

# 갱신 — 구 refresh 는 즉시 폐기(rotation)되고 새 쌍이 나온다
curl -X POST localhost:8000/auth/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refreshToken":"<위에서 받은 refreshToken>"}'

# 공개키 — 각 앱 백엔드가 이걸 캐시해서 자체 검증
curl localhost:8000/.well-known/jwks.json
```

Swagger: <http://localhost:8000/docs>

테스트는 Redis 없이(fakeredis) 돕니다:

```bash
.venv/bin/pytest          # rotation·재사용감지·grace·동시성·CSRF·JWKS 검증
```

## 3. 기존 인증서버에 붙일 때 갈아끼울 곳

**`app/users.py` 하나입니다.** 나머지는 사용자 저장소를 모릅니다.

```python
class UserAuthenticator(Protocol):
    async def authenticate(self, account: str, password: str) -> UserIdentity | None: ...
    async def get_by_sub(self, sub: str) -> UserIdentity | None: ...
```

기존 인증서버의 계정 조회/비밀번호 검증을 이 두 메서드로 감싸서
`create_app(authenticator=...)` 에 넣으면 나머지 흐름은 그대로 동작합니다.
(`DemoUserAuthenticator` 는 말 그대로 데모용이라 운영 사용 금지)

## 4. 동작 규칙 (이 부분이 진짜 참고 포인트)

**Rotation + 재사용 감지 + Grace 는 한 세트로 움직입니다.**

```
refresh R1 사용
  → 새 쌍(A2, R2) 발급, R1 은 "폐기(rotated)" 로 표시하고 발급한 쌍을 붙여둠
  → R1 이 다시 나타나면
       ├ grace(기본 20초) 이내  → 앱 간 동시 갱신 경합으로 보고 (A2, R2) 를 그대로 반환
       └ grace 이후            → 탈취로 간주, 그 세션(sid) 계보 전체 무효화 → 재로그인
```

- **폐기된 기록을 지우지 않고 남겨두는 게 핵심**입니다. 일찍 지우면 "폐기된 토큰의 재등장"과
  "모르는 토큰"을 구분할 수 없어 재사용 감지 자체가 성립하지 않습니다.
  (`store.py` 의 `rt:{jti}` TTL = refresh 만료 시각)
- `sid`(세션 패밀리)로 rotation 계보를 묶습니다. 무효화 단위가 토큰 1개가 아니라 **세션 전체**여야
  탈취자가 갈아탄 토큰까지 같이 끊깁니다.
- 같은 refresh 로 **동시에** 요청이 몰리면 Redis 락으로 1회만 회전시키고, 나머지는 같은 쌍을 받습니다.
  (앱 내부의 single-flight 는 각 앱 백엔드 몫 — 이건 서버 측 보험)

**access 는 저장하지 않습니다.** 각 앱이 JWKS로 자체 검증하므로 서버 상태가 필요 없습니다.
대신 로그아웃해도 이미 발급된 access 는 만료(수 분) 전까지 유효합니다 — access 수명을 짧게 두는 이유입니다.

## 5. 파일

```
app/
  config.py      설정 — TTL·쿠키·세션 정책 전부 여기 (부록 C)
  keys.py        RS256 키 로드 + JWKS 직렬화
  tokens.py      JWT 발급/검증 (kid 헤더)
  store.py       Redis — refresh 상태·세션 패밀리·grace·회전 락
  service.py     ★ 핵심 로직: 로그인/rotation/재사용 감지/grace
  cookies.py     httpOnly 쿠키 + CSRF(double-submit)
  users.py       ★ 사용자 저장소 연동 지점 (교체 대상)
  routers/       HTTP 엔드포인트
scripts/gen_keys.py
tests/           동작 규칙 검증
```
