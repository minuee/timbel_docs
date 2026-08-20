# Windows 개발 환경 세팅 가이드

> 작성일: 2026-08-20
> 대상: Windows + PowerShell 환경
> 포함: PowerShell 실행 정책 / Git / Java(Scoop) / Python(uv) / 폐쇄망 대비

---

## 목차

1. [PowerShell 실행 정책](#1-powershell-실행-정책)
2. [Git 설치 및 설정](#2-git-설치-및-설정)
3. [Java 멀티 버전 관리 (Scoop)](#3-java-멀티-버전-관리-scoop)
4. [Python 멀티 버전 관리 (uv)](#4-python-멀티-버전-관리-uv)
5. [트러블슈팅 모음](#5-트러블슈팅-모음)
6. [폐쇄망(망분리) 대비](#6-폐쇄망망분리-대비)
7. [빠른 참조 치트시트](#7-빠른-참조-치트시트)

---

## 1. PowerShell 실행 정책

### 증상

```
npm : 이 시스템에서 스크립트를 실행할 수 없으므로 C:\nvm4w\nodejs\npm.ps1 파일을 로드할 수 없습니다.
    + CategoryInfo          : 보안 오류: (:) [], PSSecurityException
    + FullyQualifiedErrorId : UnauthorizedAccess
```

### 원인

PowerShell 실행 정책이 `Restricted`라서 `.ps1` 스크립트를 로드하지 못함. npm 자체 문제가 아님.

### 해결 (권장)

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

- 확인 메시지에 `Y` 입력
- 관리자 권한 불필요 (`CurrentUser` 범위)
- 적용 후 PowerShell 창 새로 열기

### 정책 확인

```powershell
Get-ExecutionPolicy -List
```

`MachinePolicy` / `UserPolicy`가 그룹 정책으로 잠겨 있으면 변경 불가 → 아래 우회 방법 사용.

### 우회 방법

```powershell
# 방법 1: .cmd 실행 파일 직접 호출
npm.cmd i --force

# 방법 2: cmd.exe에서 실행 (실행 정책 영향 없음)
```

> VS Code 사용 시 터미널 기본 셸을 Command Prompt로 변경하는 것도 방법.

### 정책 종류 참고

| 정책 | 설명 |
|---|---|
| `Restricted` | 모든 스크립트 차단 (Windows 기본값) |
| `RemoteSigned` | 로컬 스크립트 허용, 인터넷 다운로드 스크립트는 서명 요구 **← 개발 환경 권장** |
| `Unrestricted` | 모두 허용 (권장하지 않음) |

---

## 2. Git 설치 및 설정

### 증상

```
git : 'git' 용어가 cmdlet, 함수, 스크립트 파일 또는 실행할 수 있는 프로그램 이름으로 인식되지 않습니다.
    + FullyQualifiedErrorId : CommandNotFoundException
```

### 설치

```powershell
winget install --id Git.Git -e --source winget
```

대안:
- Chocolatey: `choco install git -y`
- 직접 다운로드: https://git-scm.com/download/win

### 설치 마법사 주요 선택 항목 (직접 설치 시)

| 항목 | 선택할 값 |
|---|---|
| Adjusting your PATH environment | **Git from the command line and also from 3rd-party software** |
| Configuring the line ending conversions | **Checkout Windows-style, commit Unix-style** (기본값) |
| Choose a credential helper | **Git Credential Manager** |

> PATH 옵션을 잘못 고르면 `CommandNotFoundException`이 계속 발생함.

**설치 후 PowerShell 창을 새로 열어야 PATH가 반영됨.**

```powershell
git --version
```

### 기본 설정

```powershell
git config --global user.name "홍길동"
git config --global user.email "hong@timbel.net"
git config --global init.defaultBranch main
git config --global core.autocrlf true
git config --global credential.helper manager
git config --global core.quotepath false
```

| 설정 | 이유 |
|---|---|
| `core.autocrlf true` | Windows 줄바꿈(CRLF) ↔ Unix(LF) 자동 변환. 없으면 파일 전체가 변경된 것으로 잡힘 |
| `core.quotepath false` | 한글 파일명 깨짐 방지 |
| `credential.helper manager` | 인증 정보 저장 (재입력 방지) |

설정 확인:

```powershell
git config --global --list
```

### GitLab 인증 (HTTPS)

GitLab은 비밀번호 대신 **Personal Access Token**을 요구하는 경우가 대부분.

1. GitLab 로그인 → 우측 상단 프로필 → **Edit profile** → **Access Tokens**
2. Scope 체크: `read_repository`, `write_repository`
3. 토큰 생성 후 복사 (재확인 불가하므로 보관 필수)
4. clone 시:
   - Username: GitLab 아이디
   - Password: **토큰 값**

Credential Manager가 설치되어 있으면 최초 1회만 입력.

### GitLab 인증 (SSH)

```powershell
ssh-keygen -t ed25519 -C "hong@timbel.net"
Get-Content ~\.ssh\id_ed25519.pub | clip
```

- 복사된 공개키를 GitLab **Preferences → SSH Keys**에 등록
- 연결 테스트 및 clone:

```powershell
ssh -T git@gitlab.timbel.dev
git clone git@gitlab.timbel.dev:apps/timblo/recording-pc-app.git
```

---

## 3. Java 멀티 버전 관리 (Scoop)

macOS의 `jenv` / SDKMAN에 대응. nvm4w처럼 명령 하나로 전환됨.

### Scoop 설치

일반 PowerShell에서 실행 (**관리자 권한 아님**):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression
```

### Java 설치

```powershell
scoop bucket add java
scoop install temurin8-jdk temurin11-jdk temurin17-jdk temurin21-jdk
```

### 버전 전환

```powershell
scoop reset temurin17-jdk
java -version
```

`scoop reset`이 심볼릭 링크를 교체하므로 `JAVA_HOME`과 PATH가 자동으로 따라옴. 환경변수 수동 설정 불필요.

### 기타 명령

```powershell
scoop list                    # 설치 목록
scoop update                  # scoop 자체 업데이트
scoop update *                # 설치된 앱 전체 업데이트
scoop uninstall temurin8-jdk  # 삭제
scoop cache rm *              # 캐시 정리
```

### IDE 연동 참고

IDE는 셸의 `JAVA_HOME`과 무관하게 자체 JDK 경로를 사용함.

- **IntelliJ**: `File → Project Structure → SDKs`에 설치한 JDK 등록 후 프로젝트별 선택
- **Gradle**: `gradle.properties`에 `org.gradle.java.home` 지정 가능

Scoop 설치 경로 예시:
```
C:\Users\<사용자>\scoop\apps\temurin17-jdk\current
```

---

## 4. Python 멀티 버전 관리 (uv)

Rust 기반 도구. Python 설치 + 가상환경 + 패키지 설치를 한 번에 처리. pip 대비 체감 10배 이상 빠름.

### 설치

```powershell
winget install --id=astral-sh.uv -e
uv --version
```

### Python 버전 설치

```powershell
uv python install 3.10 3.11 3.12 3.13
uv python list
```

### 중요: uv가 설치한 Python은 기본적으로 PATH에 없음

uv는 Python을 `%LOCALAPPDATA%\uv\python\`에 넣고 PATH에 노출하지 않음.
따라서 `uv python install` 직후 `python --version`이 인식되지 않거나 엉뚱한 버전이 잡힐 수 있음.

**해결 A — 가상환경 생성 후 activate (권장)**

```powershell
uv venv --python 3.12
.\.venv\Scripts\activate
python --version
```

**해결 B — 전역 PATH 등록**

```powershell
uv python install 3.12 --default --preview
```

> 가상환경 없이 전역 Python을 쓰는 습관은 권장하지 않음.

### 기본 워크플로우

```powershell
cd 프로젝트폴더
uv venv --python 3.12
.\.venv\Scripts\activate
uv pip install -r requirements.txt
```

`.gitignore`에 `.venv/` 추가 필수.

### pip → uv 명령어 대응표

| 기존 방식 | uv 방식 | 비고 |
|---|---|---|
| `python -m venv .venv` | `uv venv` | uv 쪽이 훨씬 빠름 |
| `pip install requests` | `uv pip install requests` | 문법 동일 |
| `pip install -r requirements.txt` | `uv pip install -r requirements.txt` | 그대로 |
| `pip freeze > requirements.txt` | `uv pip freeze > requirements.txt` | 그대로 |
| `pip list` | `uv pip list` | 그대로 |
| `pip uninstall requests` | `uv pip uninstall requests` | 그대로 |
| `python script.py` | `uv run script.py` | activate 불필요 |

### activate 없이 실행

```powershell
uv run python script.py
uv run pytest
uv run uvicorn main:app --reload
```

`uv run`은 가상환경을 자동으로 찾아 그 안에서 실행. 터미널을 새로 열 때마다 activate 하는 번거로움 해소.

### 주의사항

- activate 안 한 상태에서 `uv pip install` 실행 시 "가상환경을 못 찾음" 오류 발생 가능. 폴더에 `.venv`가 있으면 자동 인식됨
- activate 후에는 기존 `pip` 명령도 동작하지만, 속도 차이가 크므로 `uv pip`로 통일 권장

### 세팅 검증

```powershell
uv --version
uv python list
uv venv --python 3.12
.\.venv\Scripts\activate
uv pip install requests
python -c "import requests; print(requests.__version__)"
```

여기까지 통과하면 정상.

---

## 5. 트러블슈팅 모음

### 5-1. Git schannel TLS 오류

**증상**

```
fatal: unable to access 'https://gitlab.timbel.dev/...':
schannel: next InitializeSecurityContext failed: SEC_E_UNSUPPORTED_FUNCTION (0x80090302)
```

**원인**

`schannel`은 Git for Windows 기본 TLS 스택(Windows 내장). 서버가 요구하는 TLS 버전/암호 스위트를 협상하지 못할 때 발생. 서버가 TLS 1.3만 허용하거나 특정 cipher만 열어둔 경우 자주 발생.

**1순위 해결 — SSL 백엔드를 OpenSSL로 전환**

```powershell
git config --global http.sslBackend openssl
git clone https://gitlab.timbel.dev/apps/timblo/recording-pc-app.git
```

Git for Windows에 OpenSSL이 포함되어 있어 별도 설치 불필요. 대부분 이걸로 해결됨.

> 백엔드 전환 시 Windows 인증서 저장소를 참조하지 않게 되므로,
> 사내 루트 CA 사용 중이면 `unable to get local issuer certificate` 오류가 이어질 수 있음.

**사내 CA 인증서 지정**

```powershell
git config --global http.sslCAInfo "C:\certs\timbel-ca.pem"
```

> `http.sslVerify false`로 검증을 끄는 방법이 검색에 많이 나오지만,
> 중간자 공격에 노출되므로 사내 저장소라도 권장하지 않음.

**추가 확인 사항**

```powershell
# Git 버전 확인 (구버전 schannel은 TLS 1.3 지원 불완전)
git --version
winget upgrade --id Git.Git -e

# HTTP/2 협상 문제 배제
git config --global http.version HTTP/1.1
```

**서버 TLS 상태 확인** (Git Bash에서):

```bash
openssl s_client -connect gitlab.timbel.dev:443 -servername gitlab.timbel.dev < /dev/null 2>&1 | grep -E "Protocol|Cipher"
```

여기서 연결 자체가 실패하면 Git 설정 문제가 아니라 프록시/방화벽 이슈. 사내 TLS 인터셉션 프록시가 있으면 이런 증상이 나오므로 인프라 담당자 확인 필요.

**최종 대안 — SSH 사용**

HTTPS가 계속 막히면 SSH가 확실한 우회로. TLS 스택을 타지 않음. (2장 SSH 섹션 참조)

### 5-2. 오류 메시지 한글 깨짐

```
SEC_E_UNSUPPORTED_FUNCTION (0x80090302) - û Լ  ʽ��ϴ.
```

Git 영문 메시지에 한글 시스템 메시지가 섞이며 인코딩이 깨진 것. **원인과 무관.**

```powershell
$env:LC_ALL = "C"
```

### 5-3. venv activate 실행 정책 오류

```
.\.venv\Scripts\Activate.ps1 : 이 시스템에서 스크립트를 실행할 수 없으므로...
```

1장의 실행 정책 설정으로 해결됨.

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 5-4. nvm4w 버전 전환 후 npm 오류

Node 버전을 전환할 때마다 npm 관련 스크립트가 재배치됨. 실행 정책을 `RemoteSigned`로 한 번 풀어두면 반복 문제 방지.

---

## 6. 폐쇄망(망분리) 대비

### 6-1. 사내 프록시 / 미러 설정

**uv (Python)**

```powershell
# 환경변수 방식
$env:UV_DEFAULT_INDEX = "https://nexus.timbel.dev/repository/pypi/simple"

# 영구 설정
[Environment]::SetEnvironmentVariable("UV_DEFAULT_INDEX", "https://nexus.timbel.dev/repository/pypi/simple", "User")

# 일회성 옵션
uv pip install requests --index-url https://nexus.timbel.dev/repository/pypi/simple
```

`pip.ini` 위치: `%APPDATA%\pip\pip.ini`

```ini
[global]
index-url = https://nexus.timbel.dev/repository/pypi/simple
trusted-host = nexus.timbel.dev
```

**npm**

```powershell
npm config set registry https://nexus.timbel.dev/repository/npm/
npm config set strict-ssl false   # 사내 CA 미등록 시 임시 조치
```

**Git 프록시**

```powershell
git config --global http.proxy http://proxy.timbel.dev:8080
git config --global https.proxy http://proxy.timbel.dev:8080

# 해제
git config --global --unset http.proxy
git config --global --unset https.proxy
```

**Gradle** (`~/.gradle/gradle.properties`)

```properties
systemProp.http.proxyHost=proxy.timbel.dev
systemProp.http.proxyPort=8080
systemProp.https.proxyHost=proxy.timbel.dev
systemProp.https.proxyPort=8080
```

### 6-2. 망분리 전 미리 받아둘 것

| 항목 | 준비 방법 |
|---|---|
| Git 설치 파일 | https://git-scm.com/download/win 에서 `.exe` 다운로드 |
| JDK | Scoop 캐시(`~\scoop\cache`) 백업 또는 Temurin `.zip` 직접 다운로드 |
| Python | `uv python install` 후 `%LOCALAPPDATA%\uv\python\` 폴더 백업 |
| uv 실행 파일 | https://github.com/astral-sh/uv/releases 에서 `uv-x86_64-pc-windows-msvc.zip` |
| Node/npm | nvm4w 설치 파일 + 필요 Node 버전 |
| Python 패키지 | `uv pip download -r requirements.txt -d ./wheels` |
| npm 패키지 | `npm pack` 또는 `node_modules` 통째로 백업 |
| 사내 CA 인증서 | 인프라 담당자에게 요청 |

**오프라인 Python 패키지 설치**

```powershell
# 인터넷 환경에서
uv pip download -r requirements.txt -d ./wheels

# 폐쇄망에서
uv pip install --no-index --find-links=./wheels -r requirements.txt
```

**오프라인 npm 설치**

```powershell
# 인터넷 환경에서 node_modules 생성 후 통째로 복사
npm ci
```

### 6-3. Scoop 오프라인 대응

Scoop은 온라인 의존성이 크므로, 폐쇄망에서는 JDK를 직접 배치하는 방식이 안전함.

`C:\Java\jdk-17`, `C:\Java\jdk-21` 형태로 압축 해제 후 PowerShell 프로파일에 전환 함수 등록:

```powershell
notepad $PROFILE
```

```powershell
function jdk {
    param([string]$v)
    $path = "C:\Java\jdk-$v"
    if (-not (Test-Path $path)) { Write-Host "없는 버전: $v"; return }
    $env:JAVA_HOME = $path
    $env:Path = "$path\bin;" + (($env:Path -split ';' | Where-Object { $_ -notlike "C:\Java\*" }) -join ';')
    java -version
}
```

사용:

```powershell
jdk 17
jdk 21
```

현재 세션에만 적용됨. 영구 반영이 필요하면:

```powershell
[Environment]::SetEnvironmentVariable("JAVA_HOME", $path, "User")
```

### 6-4. 사내 인증서 등록

```powershell
# Git
git config --global http.sslCAInfo "C:\certs\timbel-ca.pem"

# Node
$env:NODE_EXTRA_CA_CERTS = "C:\certs\timbel-ca.pem"

# Python (requests 계열)
$env:REQUESTS_CA_BUNDLE = "C:\certs\timbel-ca.pem"
$env:SSL_CERT_FILE = "C:\certs\timbel-ca.pem"
```

영구 등록:

```powershell
[Environment]::SetEnvironmentVariable("NODE_EXTRA_CA_CERTS", "C:\certs\timbel-ca.pem", "User")
```

---

## 7. 빠른 참조 치트시트

### PowerShell

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser   # 실행 정책 변경
Get-ExecutionPolicy -List                                              # 정책 확인
notepad $PROFILE                                                       # 프로파일 편집
```

### Git

```powershell
git --version
git config --global --list
git config --global http.sslBackend openssl        # schannel 오류 시
git config --global http.version HTTP/1.1          # HTTP/2 문제 배제
git clone git@gitlab.timbel.dev:그룹/저장소.git     # SSH clone
```

### Java (Scoop)

```powershell
scoop bucket add java
scoop install temurin17-jdk
scoop reset temurin17-jdk      # 버전 전환
scoop list
java -version
```

### Python (uv)

```powershell
uv python install 3.12         # Python 설치
uv python list                 # 설치 목록
uv venv --python 3.12          # 가상환경 생성
.\.venv\Scripts\activate       # 활성화
deactivate                     # 비활성화
uv pip install -r requirements.txt
uv pip freeze > requirements.txt
uv run python script.py        # activate 없이 실행
```

### Node (nvm4w)

```powershell
nvm list
nvm install 20.11.0
nvm use 20.11.0
npm.cmd i --force              # 실행 정책 우회
```

---

## 주요 경로 정리

| 항목 | 경로 |
|---|---|
| PowerShell 프로파일 | `$PROFILE` (보통 `~\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`) |
| Git 전역 설정 | `~\.gitconfig` |
| SSH 키 | `~\.ssh\id_ed25519` |
| Scoop 앱 | `~\scoop\apps\` |
| Scoop 캐시 | `~\scoop\cache\` |
| uv Python | `%LOCALAPPDATA%\uv\python\` |
| pip 설정 | `%APPDATA%\pip\pip.ini` |
| npm 설정 | `~\.npmrc` |

---

*이 문서는 실제 세팅 과정에서 발생한 오류와 해결 과정을 정리한 것입니다.
환경(사내 정책, 프록시, 인증서)에 따라 일부 명령은 조정이 필요할 수 있습니다.*
