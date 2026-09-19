# @timbel-timblo-onpremise/prisma

Timblo Prisma Database Module - MariaDB와 MongoDB를 위한 통합 Prisma 클라이언트

## 📦 설치

```bash
npm install @timbel-timblo-onpremise/prisma
```

## 🚀 사용법

### 기본 사용법

```javascript
import BaseDatabase, { Enums } from '@timbel-timblo-onpremise/prisma';

// 데이터베이스 클라이언트 생성
const db = new BaseDatabase('MyService');

// MariaDB 사용
const users = await db.mariaDB.user.findMany();

// MongoDB 사용
const files = await db.mongoDB.file.findMany();

// Enum 사용
console.log(Enums.YesNo.YES); // MariaDB YesNo enum
console.log(Enums.MongoYesNo.YES); // MongoDB YesNo enum
```

### Enum 사용

```javascript
import { Enums } from '@timbel-timblo-onpremise/prisma';

// MariaDB Enums
const { YesNo, CorrectionStatus, ContentType } = Enums;

// MongoDB Enums
const { MongoYesNo, TranslateType, MongoSupportLang } = Enums;
```

## 🏗️ 개발

### Prisma 스키마 빌드

```bash
# MariaDB + MongoDB Prisma 클라이언트 생성 및 Enum 업데이트
npm run prismaBuild

# 개별 빌드
npm run prismaBuild:maria  # MariaDB만
npm run prismaBuild:mongo  # MongoDB만
```

### 패키지 빌드

```bash
# 전체 패키지 준비 (Prisma 빌드 + 빌드)
npm run package

# 개별 빌드
npm run build              # 전체 빌드
npm run build:rollup       # Rollup 번들링만
npm run build:types        # TypeScript 선언 파일만
```

### 배포

```bash
# GitHub 패키지 레지스트리에 배포
npm run publish:github
```

### 개발용 로컬 동기화

이 명령어는 다음 작업을 수행합니다:

1. Prisma 빌드 (MariaDB + MongoDB + Enum 업데이트)
2. 전체 빌드 (ESM + CJS + TypeScript)
3. TypeScript 선언 파일 이름 변경
4. `node_modules/@timbel-timblo-onpremise/prisma/dist/`에 동기화

**사용 시나리오**:

- 프로젝트를 submodule로 받아서 수정한 후
- 로컬에서 테스트하기 위해 node_modules의 패키지를 업데이트할 때 사용

**사용 방법**:

1. **submodule 설정**:

   ```bash
   # 사용하는 프로젝트에서 submodule 추가
   git submodule add -b ${Branch} <repository-url> prisma
   ```

2. **스키마 수정 후 동기화**:

   ```bash
   # 사용하는 프로젝트 루트에서 실행
   node prisma/scripts/dev-sync.js
   ```

3. **submodule 업데이트**:

   ```bash
   git submodule update --remote --merge
   ```

## 📁 프로젝트 구조

```
src/
├── base.database.js          # 메인 데이터베이스 클래스
└── libs/
    └── prismaService/
        ├── mariaDB/          # MariaDB Prisma 클라이언트
        └── mongoDB/          # MongoDB Prisma 클라이언트

schema/
├── mariadb/                  # MariaDB Prisma 스키마
└── mongodb/                  # MongoDB Prisma 스키마

scripts/
├── update-enums.js          # Enum 자동 업데이트
├── copy-libs.js             # libs 폴더 복사
├── publish.js               # 배포 스크립트
└── dev-sync.js              # 개발용 로컬 동기화 스크립트
```

## 🔧 주요 기능

- **통합 데이터베이스 클라이언트**: MariaDB와 MongoDB를 하나의 클래스에서 관리
- **자동 Enum 관리**: Prisma 스키마 변경 시 Enum 자동 업데이트
- **TypeScript 지원**: 완전한 타입 정의 제공
- **개발 환경 로깅**: 쿼리 및 에러 로깅 자동 활성화
- **자동화된 배포**: GitHub 패키지 레지스트리 자동 배포

## 📋 스크립트

| 명령어                   | 설명                                     |
| ------------------------ | ---------------------------------------- |
| `npm run package`        | Prisma 빌드 + Enum 업데이트 + 전체 빌드  |
| `npm run prismaBuild`    | MariaDB + MongoDB Prisma 클라이언트 생성 |
| `npm run build`          | 전체 빌드 (ESM + CJS + TypeScript)       |
| `npm run publish:github` | GitHub 패키지 레지스트리 배포            |

## 📄 라이선스

MIT

## 👥 기여

이 패키지는 Timblo 내부 사용을 위한 패키지입니다.
