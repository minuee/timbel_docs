# Prisma Enum 자동 업데이트 스크립트

이 스크립트는 Prisma 클라이언트 빌드 후 자동으로 Enum들을 추출하여 `base.database.js`에 반영하는 도구입니다.

## 파일 구조

```
scripts/
├── update-enums.js    # Enum 자동 업데이트 스크립트
└── README.md         # 이 파일
```

## 사용법

### 1. 자동 실행 (권장)

```bash
npm run prismaBuild
```

이 명령어는 다음 순서로 실행됩니다:

1. MariaDB Prisma 클라이언트 생성
2. MongoDB Prisma 클라이언트 생성
3. Enum 자동 추출 및 base.database.js 업데이트

### 2. 수동 실행

```bash
# Enum 업데이트만 실행
npm run updateEnums

# 또는 직접 실행
node scripts/update-enums.js
```

## 스크립트 동작 방식

1. **Enum 추출**:

   - `src/libs/prismaService/mariaDB/index.d.ts`에서 MariaDB Enum들 추출
   - `src/libs/prismaService/mongoDB/index.d.ts`에서 MongoDB Enum들 추출

2. **중복 처리**:

   - MariaDB와 MongoDB에서 동일한 이름의 Enum이 있는 경우 별칭 사용
   - 예: `YesNo` → `MongoYesNo`, `SupportLang` → `MongoSupportLang`

3. **파일 업데이트**:
   - `src/base.database.js`의 import 섹션 자동 업데이트
   - `Enums` 객체 자동 업데이트

## 추출되는 Enum 목록

### MariaDB Enums (30개)

- YesNo, CorrectionStatus, ContentType, ContentShareRole
- DownloadType, DownloadDevice, DownloadDeviceMobile, ReSummarySize
- NotifyType, UsageType, DomainType, TermsStatus
- AgreementStatus, PolicyCategory, BatchType, BatchStatus
- Provider, SupportLang, Engine, Summarizer
- OS, LoginDevice, WorkspaceRole, PlatformType
- PermissionType, PolicyType, Unit, SettingValueType
- WorkspaceSettingUiType, WorkspaceSettingGroup

### MongoDB Enums (6개)

- BookmarksKeys, MemoKeys, YesNo, TranslateType, SupportLang, Engine

## 주의사항

- 스크립트 실행 전에 Prisma 클라이언트가 빌드되어 있어야 합니다
- `base.database.js` 파일이 존재해야 합니다
- 스크립트는 기존 `ContentFilter` 같은 커스텀 Enum은 유지합니다

## 문제 해결

### 오류: "TypeScript 파일을 찾을 수 없습니다"

- Prisma 클라이언트가 제대로 빌드되었는지 확인
- `npm run prismaBuild` 실행 후 다시 시도

### 오류: "base.database.js 파일을 찾을 수 없습니다"

- `src/base.database.js` 파일이 존재하는지 확인

### Enum이 제대로 업데이트되지 않는 경우

- TypeScript 파일의 export 패턴이 변경되었을 수 있음
- `extractEnumsFromTypes` 함수의 정규식을 확인
