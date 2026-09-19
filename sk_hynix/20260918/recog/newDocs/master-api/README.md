# Be Master Service

Timblo의 마스터 서비스 백엔드 애플리케이션입니다.

## API Docs

> https://docs.timblo.io/

## Get Started

```Shell
$ git clone https://github.com/timbel-timblo-onpremise/master-api.git
$ npm install

$ 환경 변수는 타겟 시스템의 consul 자료를 참고

$ npm start
```

## 프로젝트 구조

### 디렉토리 구조

```
src/
├── app.js                    # Express 애플리케이션 진입점
├── app.module.js            # 애플리케이션 모듈 설정
├── app.handle.js            # 애플리케이션 핸들러
│
├── controller/              # 컨트롤러 레이어 (HTTP 요청/응답 처리)
│   ├── base.controller.js  # 기본 컨트롤러 클래스
│   ├── content/            # 콘텐츠 관련 컨트롤러
│   │   ├── content.controller.js    # 통합 컨트롤러
│   │   ├── detail.controller.js      # 상세 조회
│   │   ├── upload.controller.js      # 업로드
│   │   └── features/                 # 콘텐츠 기능별 컨트롤러
│   │       ├── attendee.controller.js
│   │       ├── bookmark.controller.js
│   │       ├── correction.controller.js
│   │       ├── memo.controller.js
│   │       ├── merge.controller.js
│   │       ├── note.controller.js
│   │       ├── share.controller.js
│   │       ├── summary.controller.js
│   │       └── transcription.controller.js
│   ├── engine/              # AI/LLM 엔진 관련
│   │   ├── chatbot.controller.js
│   │   └── integrate.controller.js
│   ├── feature/            # 기능별 컨트롤러
│   │   ├── calendar.controller.js
│   │   ├── keyword.controller.js
│   │   └── template.controller.js
│   ├── notification/       # 알림 관련
│   │   ├── inbox.controller.js
│   │   └── notice.controller.js
│   ├── system/              # 시스템/인프라
│   │   ├── queue.controller.js
│   │   ├── recycle.controller.js
│   │   └── search.controller.js
│   └── user/               # 사용자 관련
│       ├── user.controller.js       # 통합 컨트롤러
│       ├── contact.controller.js
│       ├── corpus.controller.js
│       ├── folder.controller.js
│       ├── home.controller.js
│       ├── notification.controller.js
│       ├── terms.controller.js
│       ├── usage.controller.js
│       └── workspace.controller.js
│
├── services/               # 서비스 레이어 (비즈니스 로직)
│   ├── base.service.js     # 기본 서비스 클래스
│   ├── index.js            # 서비스 통합 export
│   ├── content/            # 콘텐츠 관련 서비스
│   │   ├── content.service.js
│   │   ├── contentCapture.service.js
│   │   ├── contentDetail.service.js
│   │   ├── demoContent.service.js
│   │   └── features/       # 콘텐츠 기능별 서비스
│   │       ├── attendee.service.js
│   │       ├── bookmark.service.js
│   │       ├── correction.service.js
│   │       ├── highlight.service.js
│   │       ├── memo.service.js
│   │       ├── note.service.js
│   │       ├── proofreading.service.js
│   │       └── share.service.js
│   ├── engine/             # AI/LLM 엔진 관련
│   │   ├── chatbot.service.js
│   │   ├── llm.service.js
│   │   ├── recog.service.js
│   │   └── summary.service.js
│   ├── feature/            # 기능별 서비스
│   │   ├── calendar.service.js
│   │   ├── corpus.service.js
│   │   ├── keyword.service.js
│   │   └── template.service.js
│   ├── notification/       # 알림 관련
│   │   ├── inbox.service.js
│   │   └── notice.service.js
│   ├── system/             # 시스템/인프라
│   │   ├── drive.service.js
│   │   ├── queue.service.js
│   │   ├── recycle.service.js
│   │   └── search.service.js
│   └── user/              # 사용자 관련
│       ├── dashboard.service.js
│       └── user.service.js
│
├── routes/                 # 라우터 정의
│   ├── bookmark.router.js
│   ├── calendar.router.js
│   ├── chatbot.router.js
│   ├── content.router.js
│   ├── home.router.js
│   ├── inbox.router.js
│   ├── integrate.router.js
│   ├── keyword.router.js
│   ├── notice.router.js
│   ├── queue.router.js
│   ├── search.router.js
│   ├── template.router.js
│   └── user.router.js
│
├── models/                 # 데이터 모델 (Prisma 기반)
├── handlers/               # 미들웨어 핸들러
│   ├── auth.handler.js
│   ├── authenticate.handler.js
│   ├── authorize.handler.js
│   ├── error.handler.js
│   └── lifecycle.handler.js
│
├── utils/                  # 유틸리티 함수
│   ├── engines/           # 음성 인식 엔진 관련
│   ├── summarizer/        # 요약 관련
│   ├── convert/           # 변환 유틸
│   ├── file/              # 파일 처리
│   └── ...
│
├── configs/               # 설정 파일
│   ├── discovery-config.js
│   ├── i18n-config.js
│   ├── swagger.js
│   └── swaggerComponents.js
│
├── prompts/               # LLM 프롬프트
└── docs/                  # API 문서
```

### 아키텍처 패턴

이 프로젝트는 **계층형 아키텍처(Layered Architecture)**를 따릅니다:

1. **Controller Layer** (`controller/`)

    - HTTP 요청/응답 처리
    - 요청 검증 및 인증/인가 처리
    - Service Layer 호출

2. **Service Layer** (`services/`)

    - 비즈니스 로직 구현
    - 데이터 처리 및 변환
    - Model Layer 호출

3. **Model Layer** (`models/`)

    - 데이터베이스 접근 (Prisma ORM)
    - 데이터 모델 정의

4. **Utils Layer** (`utils/`)
    - 공통 유틸리티 함수
    - 외부 서비스 연동

### 폴더 구조 설계 원칙

-   **기능별 그룹화**: 관련 기능들을 동일한 폴더에 배치
-   **Controller-Service 일치**: Controller와 Service의 폴더 구조를 동일하게 유지하여 일관성 확보
-   **확장성**: 새로운 기능 추가 시 적절한 폴더에 배치 가능
-   **명확한 책임 분리**: 각 폴더가 명확한 도메인을 담당

## 주요 기능

### Content (콘텐츠)

-   콘텐츠 업로드 및 관리
-   콘텐츠 상세 조회 및 편집
-   북마크, 메모, 노트, 하이라이트 기능
-   교정 및 교열 기능
-   참석자 관리
-   콘텐츠 공유

### Engine (AI/LLM)

-   음성 인식 및 전사
-   요약 생성
-   챗봇 기능
-   LLM 작업 처리

### User (사용자)

-   사용자 프로필 관리
-   주소록 관리
-   폴더 관리
-   약관 동의
-   사용량 통계
-   대시보드

### System (시스템)

-   파일 저장소 관리
-   작업 큐 관리
-   휴지통/삭제 처리
-   검색 기능

### Feature (기능)

-   캘린더 연동
-   키워드 부스팅
-   템플릿 관리
-   말뭉치 관리

### Notification (알림)

-   공지사항
-   인박스

## 스크립트

```bash
# 개발 서버 실행
npm run dev

# 빌드
npm run build

# Prisma 동기화
npm run prisma:sync
```

## Branch Push

### main

> Develop 브런치에 개발 이후 공동 개발자의 MR 기준일 TAG를 설정 후 사용
>
> CI / CD 구성 이전 조율 단계 필요
>
> `Develop` -> `main` MR 시 Develop 브런치는 Delete 금지

### Develop

> 각자 개발 브런치로 `feature`, `fix`, `refector`, `dependency`, `document` 등의 하위 브런치를 작성 후 MR 되는 브런치 (MR 시 하위 브런치는 Delete 필수)
>
> 별도의 하위 브런치로 분리되지 않은 경우 `COMMIT` 문구에 위 5개 태그 표기 후 commit
>
> 공동 개발자 코드와 영향이 없는 경우 직접 MR 허용 그 외 리뷰 및 `approved` 통과 후 진행
>
> `Develop` 브런치는 직접 PUSH 도 일부 허용
