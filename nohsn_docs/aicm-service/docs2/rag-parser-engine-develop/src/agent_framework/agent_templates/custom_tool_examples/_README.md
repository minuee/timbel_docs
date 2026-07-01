# Custom Tool Examples — Webhook 카탈로그

`/api/v1/custom-tools/examples` (admin+) 가 이 디렉터리의 `*.json` 을 자동 픽업해 admin 콘솔에 노출합니다. admin 은 `/api/v1/custom-tools/from-example/{id}` 로 fixture 를 복사해 자기 tenant 에 등록합니다.

## 카테고리

### 알림 (10)
양방향/단방향 메시징 채널.
- `slack.webhook_send` — Incoming Webhook (URL 시크릿, 단방향).
- `slack.chat_postmessage` — Bot Token (Block Kit / 스레드 / 양방향 송신).
- `discord.webhook_send` — 채널 webhook (단방향). 양방향은 별도 Application + Ed25519.
- `kakaowork.webhook_send` — KakaoWork Incoming Webhook.
- `telegram.bot_send` — Telegram Bot sendMessage. 인바운드는 setWebhook + secret_token.
- `line.push_message` — LINE Messaging API push (quota 추적 필요). 일본/대만/태국 진출.
- `teams.adaptive_card_post` — MS Teams Power Automate Workflow (단방향). 양방향은 Bot Framework.
- `kakao.iopen_skill_response` — 카카오 i 오픈빌더 스킬서버 응답 (5초 SLA + callback).
- `naver.talktalk_send` — 네이버 톡톡 push.
- `whatsapp.template_send` — WhatsApp Cloud API 사전 승인 템플릿 (24h 윈도 외).

### SMS / 메일 (5)
- `aligo.sms_send` — Aligo SMS (한국, 발신번호 사전 등록).
- `coolsms.sms_send` — CoolSMS SMS/LMS/MMS (Solapi 그룹, 개발자 도구 풍부).
- `solapi.alimtalk_send` — Solapi 카카오 알림톡 (사전 승인 템플릿).
- `ncp.sens_sms` — NCP SENS SMS (HMAC-SHA256 서명).
- `mailgun.send` — Mailgun REST API.

### 정보 / 검색 (4)
- `kma.short_forecast` — 기상청 단기예보 (공공데이터포털).
- `kakao.address_search` — Kakao Local 주소→좌표.
- `naver.papago_translate` — Papago NMT 번역.
- `exchangerate.latest` — ExchangeRate-API 환율.

### 협업 / CRM / 자동화 (3)
- `notion.create_page` — Notion API 페이지 생성.
- `trello.create_card` — Trello REST 카드 생성.
- `generic.webhook_trigger` — Zapier / n8n / Make 범용 webhook (자동화 허브).

### 결제 / 사업 (2)
- `toss.payment_confirm` — Toss Payments 결제 승인 (sk 키 + idempotency).
- `biznum.lookup` — 국세청 사업자등록 진위 확인 (공공데이터포털).

## 공통 스키마

각 fixture 의 필드:

| 필드 | 의미 |
|---|---|
| `id` / `name` | 고유 식별자 (dot 구분: `vendor.action`) |
| `display_name` | UI 표시명 (한국어) |
| `description` | 1-3 문장, 운영 핵심·비용·제약 포함 |
| `category` | 알림 / SMS·메일 / 정보·검색 / 협업·CRM / 결제·사업 |
| `vendor` / `vendor_url` | 공식 docs 링크 |
| `endpoint_url` | 호출 URL — 시크릿/도메인 placeholder 는 `<>` 로 표시 |
| `method` | HTTP 메서드 |
| `auth_headers` | 헤더 템플릿 (값은 admin 이 등록 시 채움) |
| `input_schema` | 요청 body / query 의 JSON Schema |
| `output_schema` | 응답 형태 |
| `risk_metadata` | side_effect / scope / requires_confirm 등 (자비스 가드레일) |
| `security` | direction / signature_method / verify_header / replay_protection / tls_required / ip_allowlist_supported / notes |
| `operational_notes` | rate_limit / retry_semantics / response_sla_sec / cost_label / biz_account_required |
| `setup_instructions` | 단계별 설정 가이드 (한국어) |

## 보안 메타 (`security`) 표기 규칙

`signature_method`:
- `HMAC-SHA256` — Slack / LINE / WhatsApp / Mailgun / NCP SENS 등
- `HMAC-SHA1` — Twilio (이 카탈로그에는 아직 없음)
- `Ed25519` — Discord interactions
- `JWT` — Teams Bot Framework / Apple
- `Bearer` — Notion / LINE push / Slack chat / WhatsApp / Naver TalkTalk
- `Basic` — Mailgun / Toss
- `static_secret_token` — Kakao i Skill / Aligo / NCP keys
- `secret_in_url` — Slack/Discord webhook URL, ExchangeRate, Power Automate Workflow
- `token_in_url` — Telegram (`/bot<TOKEN>/`)
- `none` — 미지원

`replay_protection`:
- `timestamp` — Slack / NCP SENS (5분 / 5분)
- `timestamp+salt` — Solapi / CoolSMS
- `idempotency_key` — Toss / Generic webhook
- `update_id` — Telegram (Bot API)
- `none` — 대부분 단방향 webhook

## 운영 메타 (`operational_notes`) 표기 규칙

`cost_label`:
- `free` — 무료 (계정만)
- `freemium` — 무료 티어 + 종량제
- `paid` — 유료 (사용자 충전 또는 정기결제)

`biz_account_required`:
- `true` — 사업자등록증/도메인 인증/통신서비스 가입증명원 필요 (한국 SMS, WhatsApp, Toss live, 카카오 채널, 네이버 톡톡)
- `false` — 개인 계정 가능

## 카탈로그 추가 가이드

새 예시 추가 절차:
1. 이 디렉터리에 `<vendor>.<action>.json` 파일 작성
2. 위 공통 스키마 모두 채우기 (특히 `security` + `operational_notes`)
3. `_index.yaml` 의 적절한 카테고리 섹션에 항목 추가
4. 이 README 의 카테고리 섹션에 한 줄 추가

API endpoint 는 자동 picks up — 별도 코드 변경 불필요.

## 출처

- GPT-5.5 webhook research 보고서: `Doc/research/2026-05-07-telegram-webhook-deep-dive.md` (Telegram 보안 권고)
- GPT-5.5 webhook services expansion: `Doc/research/2026-05-07-webhook-services-expansion.md` (5 시급 채널 + 인프라 보강)
