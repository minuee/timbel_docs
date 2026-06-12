# Git 서버 정렬 & 인증 가이드 (192 / Cursor 서버 기준)

> 192 개발기는 **CI/CD 없이 서버에서 직접 git 으로 코드를 받아** 도커로 띄운다.
> 이때 자주 겪는 **GitLab 인증 401** 문제와, **로컬 push → 서버 강제 정렬** 워크플로우를 정리했다.
> (실제로 겪은 케이스 기반)

---

## 0. 한눈에 보는 흐름

```
로컬(맥)에서 commit + push
        │
        ▼
서버(192)에서 fetch → reset --hard origin/<브랜치>   ← pull 아님!
        │
        ▼
변경된 게 코드면 재빌드, 설정/모니터링이면 해당 컨테이너만 up
```

**왜 `pull` 이 아니라 `reset --hard` 인가?**
- 서버에 직접 수정한 미커밋 변경이 있으면 `git pull`(=fetch+merge)은 **충돌**나거나 꼬인다.
- `reset --hard origin/<브랜치>`는 서버를 원격과 **100% 동일하게 강제 정렬** → 충돌 없음.
- 단, **서버의 미커밋 수정은 날아간다**(되돌릴 수 없음). 그래서 아래 "안전 순서"를 지킨다.

---

## 1. GitLab 인증 401 문제 (제일 많이 막힘)

### 증상
```
Missing or invalid credentials.
Error: Bad status code: 401
  at ... /.cursor-server/.../extensions/git/dist/askpass-main.js ...
remote: HTTP Basic: Access denied. ... you're required to use a token instead of a password
fatal: Authentication failed for 'https://gitlab.timbel.dev/.../asst-service.git/'
```
그리고 **예전처럼 ID/PW 입력창이 안 뜬다.**

### 원인 (2가지가 겹침)
1. **Cursor 서버의 `GIT_ASKPASS`(`askpass-main.js`)가 가로챔** — git 이 사용자에게 묻는 대신, Cursor 가 캐시해둔 **만료/틀린 자격증명을 자동 제출** → 입력창도 없이 바로 401.
2. **GitLab 이 비밀번호 대신 PAT(Personal Access Token)를 요구** — 일반 비번 인증은 막혀 있음.

### 해결 — PAT 를 URL 에 직접 박고 askpass 우회

#### PAT 발급
GitLab(`https://gitlab.timbel.dev`) → 우상단 프로필 → **Preferences / Edit profile → Access Tokens**
- scope: **`read_repository`** (fetch/pull 만 필요) / push 까지면 **`write_repository`** 추가
- 만료일 설정, 토큰 문자열 복사 (한 번만 보임)

#### 방법 A — 일회성 (토큰이 설정파일에 안 남음, 보안상 권장)
```bash
GIT_ASKPASS= git fetch \
  'https://oauth2:<PAT>@gitlab.timbel.dev/apps/langsa/asst-service.git' \
  develop_nohsn:refs/remotes/origin/develop_nohsn

git reset --hard origin/develop_nohsn
```

#### 방법 B — remote 에 토큰 박아두기 (편하지만 `.git/config` 에 평문 저장)
```bash
git remote set-url origin 'https://oauth2:<PAT>@gitlab.timbel.dev/apps/langsa/asst-service.git'
git fetch origin
git reset --hard origin/develop_nohsn
```

**포인트:**
- `GIT_ASKPASS=` 를 앞에 붙이면 Cursor askpass 를 끄고 **URL 에 박은 토큰**을 쓴다. (방법 A 핵심)
- URL 형식은 **`oauth2:<PAT>`** — GitLab 은 username 자리에 `oauth2`, password 자리에 토큰을 넣는 방식이 제일 호환 잘 됨.
- 방법 B 는 `.git/config` 에 토큰이 평문으로 남으니, **공용 서버면 주의**. 토큰 만료/회수 시 `git remote set-url` 로 다시 교체.

---

## 2. 로컬 → 서버 정렬 안전 순서 (서버 직접수정이 있을 때)

서버에서 급하게 직접 고친 게 있을 수 있으니, 날리기 전에 **확인 + 백업**부터.

### 1) 로컬(맥)에서 push
```bash
git add <파일들>
git commit -m "<type>: <한글 메시지>"
git push origin develop_nohsn
```

### 2) 서버에서 — 날리기 전에 뭐가 바뀌었나 확인 + 백업
```bash
git status        # 서버에서 뭐가 수정됐나
git diff          # 구체적으로 뭘 고쳤나 (q 로 나옴)
git stash         # ★ 미커밋 변경 백업 (나중에 git stash pop 으로 복구 가능)
```
> **판단 기준:** 서버에서 고친 내용이 *로컬에도 이미 있으면* 그냥 덮어써도 안전.
> 서버에만 있으면 → `git stash` 로 백업 후, 필요한 부분만 나중에 회수.

### 3) 서버를 원격으로 강제 정렬
```bash
git fetch origin                          # 원격 최신 받아오기 (먼저!)
git reset --hard origin/develop_nohsn     # 원격과 100% 동일하게
# git clean -fd                           # (선택) 추적 안 되는 새 파일/폴더까지 청소 — ⚠️ git 에 없는 파일 삭제됨
```
> `clean -fd` 는 **untracked 파일까지 삭제**한다. monitor 설정처럼 서버에만 있는 파일을 살리려면 **치지 말 것.**

---

## 3. 정렬 후 — 무엇이 바뀌었냐에 따라

| 바뀐 것 | 반영 방법 |
|---------|-----------|
| **코드** (`src/**`, 예: `main.ts` CORS) | asst-service **재빌드**: `docker compose -f docker-compose.dev.yml up -d --build` |
| **설정만** (`.env.development`, compose) | 재빌드 없이 재생성: `docker compose -f docker-compose.dev.yml up -d --force-recreate` |
| **모니터링 추가** (`docker-compose.monitor.yml`) | 해당 컨테이너만: `docker compose -f docker-compose.monitor.yml up -d` (기존 서비스 영향 0) |

> ⚠️ 코드 변경은 `reset` 만으로 컨테이너에 반영 안 된다 — 이미 빌드된 `dist` 가 도니까 **재빌드 필수**.

---

## 4. 자주 쓰는 명령 모음

```bash
# 인증 막힐 때 — 토큰으로 강제 fetch (askpass 우회)
GIT_ASKPASS= git fetch 'https://oauth2:<PAT>@gitlab.timbel.dev/apps/langsa/asst-service.git' \
  develop_nohsn:refs/remotes/origin/develop_nohsn

# 서버 강제 정렬 (원격 기준)
git fetch origin && git reset --hard origin/develop_nohsn

# 현재 브랜치 / 상태 확인
git branch
git status -sb

# 토큰 remote 교체 (만료/회수 시)
git remote set-url origin 'https://oauth2:<새PAT>@gitlab.timbel.dev/apps/langsa/asst-service.git'

# 백업 / 복구
git stash          # 미커밋 변경 임시 백업
git stash list     # 백업 목록
git stash pop      # 마지막 백업 복구
```

---

## 5. 체크리스트 (서버 정렬할 때마다)

1. 로컬에서 `commit` + **`push`** 했는가? (커밋만 하면 원격에 없음 → 서버에서 받아도 옛날 버전)
2. 서버 브랜치가 맞는가? `git branch` 로 확인 (브랜치 함정 주의)
3. 서버에 살릴 미커밋 수정 없는가? → 있으면 `git stash` 백업
4. `git fetch` **먼저**, 그 다음 `git reset --hard origin/<브랜치>`
5. 인증 401 뜨면 → `GIT_ASKPASS=` + `oauth2:<PAT>` URL (1번 섹션)
6. 코드 바뀌었으면 `--build` 재빌드, 설정만이면 `--force-recreate`

---

**관련 문서:** 도커 배포/트러블슈팅은 [`docker-deploy-guide.md`](./docker-deploy-guide.md), 브라우저 로그 뷰어(Dozzle)는 같은 문서 10번 섹션 참고.
