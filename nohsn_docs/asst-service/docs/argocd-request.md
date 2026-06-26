# ArgoCD 환경변수 추가 요청 가이드

asst-service(aicc) 배포 환경변수를 추가/변경할 때의 구조와 절차를 정리한 문서.
(예시: CE 연동용 `CE_API_LLM_URL`, `CE_API_KEY` 추가 건)

---

## 핵심 한 줄 요약

배포된 Pod의 환경변수는 **`.env.development` 파일이 아니라 k8s Deployment가 주입**한다.
그 정의는 **이 코드 레포가 아니라 DevOps 소유 Helm 차트 레포(GitOps)** 에 있다.
→ `.env.development` 수정은 배포에 **아무 효과 없음**. DevOps에 요청해야 한다.

---

## 왜 코드 레포 수정으로는 안 되나

- `.dockerignore` 가 `.env.*` 를 제외 → **이미지에 .env 파일이 안 들어감**
- Dockerfile은 `NODE_ENV=production`, k8s manifest가 `NODE_ENV=development` 로 덮어씀
- 앱은 `ConfigModule(envFilePath)` 로 읽지만 파일이 없으면 **`process.env`(=k8s 주입값)** 사용
- `configService.get('CE_API_KEY')` = 결국 `process.env.CE_API_KEY` 를 읽음
- 이 코드 레포 안엔 k8s/helm manifest가 **하나도 없음**

> ❌ `.dockerignore` 에서 `.env.development` 빼서 이미지에 굽기 = **금지**.
> 그 파일엔 실제 비밀(CE_API_KEY, DB_PASSWORD, REDIS_PASSWORD)이 있어 이미지/git에 노출됨.
> (현재 `.env.development` 가 git에 커밋돼 있는 것도 별도 정리 대상)

---

## env 주입 구조 (Deployment manifest 기준)

`asst-service-deploy` 의 `spec.template.spec.containers[].env` 에 직접 나열된다. `envFrom`/ConfigMap 안 씀.

| 종류 | 방식 | 예시 |
|------|------|------|
| 평문 값 | `value:` 직접 | `REDIS_HOST`, `LOG_LEVEL`, `NODE_ENV=development` |
| 비밀 값 | `valueFrom.secretKeyRef` → Secret 참조 | `REDIS_PASSWORD` (key: `redis-password`) |

### 비밀값이 흐르는 체인 (CSI SecretProviderClass)

```
[외부 비밀저장소]              ← 실제 값(company_..sk-..)이 진짜로 사는 곳
  (Vault / AWS Secrets Manager 등)
        │  SPC(asst-service-spc-v{no}) 의 objects 가 끌어옴
        ▼
[SecretProviderClass]  asst-service-spc-v{no}
        │  secretObjects 가 'ce-api-key' 키로 매핑
        ▼
[k8s Secret]  asst-service-secret-v{no}
   data: { ce-api-key: <값> }
        │  secretKeyRef 가 이 키를 가리킴
        ▼
[Deployment env]  CE_API_KEY  → 런타임 주입 → process.env.CE_API_KEY
```

- `secrets-store.csi.k8s.io` 드라이버, `/mnt/secrets` 마운트, ServiceAccount `secrets-sa`
- **중요:** `value:` 와 `valueFrom:` 은 **택일** — 같이 쓰면 에러.
  `secretKeyRef` 는 값이 아니라 "주소(포인터)"이고, 실제 값은 Secret/외부저장소에만 존재.

---

## GitOps 소스 (진짜 원본)

ArgoCD App `asst-service` → DETAILS → SOURCE:

- **repoURL:** `https://gitlab.timbel.dev/apps/devops/langsa/chart.git` (DevOps 소유 공용 차트)
- **path:** `ecp/chart/apps`
- **targetRevision:** `main`
- **공용 Helm 차트 + 계층형 values** (뒤 파일이 앞을 덮어씀):
  1. `values.yaml`
  2. `values/common/dev-values.yaml`
  3. `values/common/dev-aicc-values.yaml`
  4. `values/aicc/asst-service/base-values.yaml`  ← asst-service 공통
  5. `values/aicc/asst-service/dev-values.yaml`   ← asst-service dev 전용(최우선)

→ Deployment env / SecretProviderClass 는 위 **4·5번 values 파일**에서 렌더링됨. 고칠 곳도 거기.

> Secret/SPC/이미지 이름이 전부 `-v{BUILD_NO}` (예 v147) → **빌드마다 CI가 템플릿 자동생성**.
> 그래서 **Argo UI에서 Live Manifest 직접 EDIT 금지** (다음 sync/빌드에 덮어써짐).

---

## 절대 하면 안 되는 방법

| 방법 | 문제 |
|------|------|
| ❌ `.dockerignore` 에서 `.env` 빼서 이미지에 굽기 | 비밀이 이미지/git에 노출 |
| ❌ Argo UI Live Manifest 직접 EDIT | sync/빌드 때 사라짐(임시) |
| ✅ GitOps 차트 레포 values 수정 → MR → Sync | 정석(영구) |

---

## 절차

1. **권한 확인** — 차트 레포(`apps/devops/langsa/chart`)는 DevOps 소유. 직접 push 권한 없으면 DevOps에 요청.
2. **요청문 전달** (아래 템플릿).
3. **비밀값은 본문에 쓰지 말고** 안전한 채널(Slack DM/암호화)로 별도 전달.
4. DevOps가 values 수정 + 외부저장소 등록 → **Argo Sync** (App `asst-service`, ns `aicc`, Manual sync).
5. 롤아웃 끝나면 새 Pod `process.env` 에 반영 → 동작 확인.

---

## DevOps 전달용 요청문 템플릿

> **[요청] asst-service(aicc/dev) 환경변수 추가 — CE 연동**
>
> 대상 차트: `apps/devops/langsa/chart` → `ecp/chart/apps`,
> values: `values/aicc/asst-service/` (base-values.yaml / dev-values.yaml)
>
> 현재 asst-service Deployment `env` 에 CE 관련 변수가 빠져 있어 CE 연동이 동작하지 않습니다.
> 아래 2개를 기존 REDIS 변수와 동일한 방식으로 추가 부탁드립니다.
>
> **① 평문 env (REDIS_HOST 와 같은 `value:` 방식)**
> ```yaml
> - name: CE_API_LLM_URL
>   value: https://ecpad.etaas.co.kr/aicc/ce-service
> # (CE_HOST 도 빠져 있으면 같이)
> - name: CE_HOST
>   value: http://ce-service-svc
> ```
>
> **② 비밀키 env (REDIS_PASSWORD 와 같은 secretKeyRef + SecretProviderClass 방식)**
> 외부 비밀저장소에 값 등록 → SPC(`asst-service-spc`)의 `secretObjects` 에 `ce-api-key` 매핑 → Deployment env 참조:
> ```yaml
> - name: CE_API_KEY
>   valueFrom:
>     secretKeyRef:
>       name: asst-service-secret   # 현재 빌드 기준 asst-service-secret-v{no}
>       key: ce-api-key
> ```
> CE_API_KEY 실제 값은 별도 채널로 전달드리겠습니다.
>
> 반영 후 Argo Sync 부탁드립니다. (App: `asst-service`, ns: `aicc`, Manual sync)

---

## 참고: 코드 쪽은 이미 준비됨

- `src/advisor/summary/services/summary.service.ts` — `configService.get('CE_API_LLM_URL')`, `get('CE_API_KEY')`
- `src/advisor/emotion/controllers/emotion.controller.ts` — CE 호출 URL/인증 헤더 설명
- → 배포 env만 주입되면 추가 코드 작업 없이 바로 동작.
