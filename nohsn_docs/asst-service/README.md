## 프로젝트 소개

[Nest](https://github.com/nestjs/nest) 프레임워크를 기반으로 한 TypeScript 스켈레톤 프로젝트입니다.

### 요구사항

- Node.js >= 20.0.0

### 주요 기술 스택

#### 핵심 프레임워크 및 라이브러리

- [NestJS](https://nestjs.com/) - 메인 프레임워크
- [TypeORM](https://typeorm.io/) - ORM
- [Winston](https://github.com/winstonjs/winston) - 로깅
- [Joi](https://joi.dev/) - 환경변수 유효성 검사
- [class-validator](https://github.com/typestack/class-validator) - DTO 유효성 검사
- [class-transformer](https://github.com/typestack/class-transformer) - 객체 변환
- [Axios](https://axios-http.com/) - HTTP 클라이언트

#### 개발 도구

- [Husky](https://typicode.github.io/husky/) - Git hooks
- [Commitlint](https://commitlint.js.org/) - 커밋 메시지 검사

### CORS 설정

본 프로젝트는 외부 요청을 위한 CORS 설정이 포함되어 있습니다.

#### 환경별 CORS 설정

- **개발 환경**: 모든 origin 허용 (`origin: true`)
- **프로덕션 환경**: 지정된 도메인만 허용

#### CORS 설정 구성

```typescript
// src/common/constants/environment.constant.ts
export const CORS_CONFIG = {
  ALLOWED_ORIGINS_DEV: [
    'http://localhost:3000',
    'http://localhost:3001',
    'http://localhost:8080',
  ],
  ALLOWED_ORIGINS_PROD: [
    'https://yourdomain.com',
    'https://app.yourdomain.com',
  ],
  ALLOWED_METHODS: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'],
  ALLOWED_HEADERS: [
    'Origin',
    'X-Requested-With',
    'Content-Type',
    'Accept',
    'Authorization',
    'X-API-Key',
  ],
  EXPOSED_HEADERS: ['Content-Length', 'X-Total-Count'],
};
```

#### 환경 변수 설정

```bash
# .env 파일에 추가
NODE_ENV=development  # 또는 production
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
```

### Git 커밋 메시지 규칙

본 프로젝트는 [Conventional Commits](https://www.conventionalcommits.org/) 규칙을 따르며,
자세한 커밋 메시지 가이드는 [.gitcommitmsg](.gitcommitmsg)를 참고해 주세요.

### 주요 프로젝트 구조

```bash
.
├── src/
│   ├── common/              # 공통 모듈
│   │   ├── decorators/      # 커스텀 데코레이터
│   │   ├── filters/         # 예외 필터
│   │   ├── guards/          # 가드
│   │   ├── interceptors/    # 인터셉터
│   │   ├── middlewares/     # 미들웨어
│   │   └── pipes/           # 파이프
│   │
│   ├── config/             # 환경 설정
│   │   ├── database.config.ts
│   │   ├── validation.config.ts
│   │   └── winston.config.ts
│   │
│   ├── advisor/           # 어드바이저 모듈
│   │   ├── dto/           # DTO 클래스
│   │   ├── entities/      # 엔티티 클래스
│   │   ├── advisor.controller.ts
│   │   ├── advisor.service.ts
│   │   └── advisor.module.ts
│   ├── app.module.ts      # 루트 모듈
│   └── main.ts           # 애플리케이션 엔트리 포인트
```

### 도메인 모듈 구조 예시

각 도메인 모듈은 다음과 같은 구조를 따릅니다:

```bash
user/                    # 사용자 모듈 예시
├── dto/                  # DTO 클래스
├── entities/             # 엔티티 클래스
├── types/                # 모듈 내부 전용 타입
├── guards/               # 모듈 전용 가드
├── interceptors/         # 모듈 전용 인터셉터
├── filters/              # 모듈 전용 필터
├── middlewares/          # 모듈 전용 미들웨어
├── decorators/           # 모듈 전용 데코레이터
├── user.controller.ts   # 컨트롤러 (또는 services/user.controller.ts)
├── user.service.ts      # 서비스 (또는 services/user.service.ts)
├── user.module.ts       # 모듈 정의
└── user.service.spec.ts # 테스트
```

새로운 도메인 모듈 생성 시 다음 명령어를 사용합니다:

```bash
$ nest g res {name}
$ nest g module {name}
$ nest g controller {name}
$ nest g service {name}
```

추가 요소가 필요한 경우:

```bash
$ nest g guard {name}/{name}
$ nest g interceptor {name}/{name}
$ nest g filter {name}/{name}
$ nest g middleware {name}/{name}
```
