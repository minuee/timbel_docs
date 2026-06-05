# ADR-005: 조직 — Team 계층 확장 및 OrgProvider 패턴

## 상태

승인됨

## 맥락

AICM의 권한 모델은 Role 기반 합집합 구조(additive-only)를 채택하고 있다. 사용자에게 Role을 부여하는 경로는 **개인 직접 할당(UserRole)**과 **조직 단위 할당(TeamRole)** 두 가지이다.

B2B 솔루션 특성상 고객사마다 다양한 조직 구조(부서 → 팀 → 파트, 또는 TF·프로젝트 단위)를 사용하며, 상위 조직에 부여한 역할이 하위 소속 멤버에게 자동 상속되어야 한다는 요구사항이 있다. 예를 들어 "A사업부"에 "상담원" 역할을 부여하면, A사업부 하위의 모든 팀·파트 소속 멤버가 해당 역할을 갖게 되어야 한다.

동시에 AICM은 SaaS(멀티테넌트)와 온프레미스(폐쇄망) 이중 배포를 지원하며(SP-1), 조직도 데이터의 원천이 환경에 따라 다르다.

- **초기(또는 온프렘)**: 외부 UserService가 아직 조직도 API를 제공하지 않거나, 자체적으로 팀을 관리해야 하는 경우 → AICM DB에서 직접 팀 계층을 관리
- **향후(SaaS)**: 외부 UserService가 조직도 API를 제공 → 외부 API에서 조직 계층을 조회

또한 문서/블록 접근 제한(Restriction)에서 화이트리스트 대상을 User 개인뿐 아니라 **팀 단위**로도 지정할 수 있어야 한다.

## 결정

### 1. Team 엔티티 — 재귀 트리 계층 구조

Team 엔티티에 `parent_id` 자기 참조 FK를 두어 재귀 트리(무한 뎁스)를 구성한다.

```
Team (
  id          UUID PK,
  name        VARCHAR(100) UNIQUE,
  parent_id   UUID FK → Team (nullable),  -- null이면 최상위
  team_source VARCHAR(20) DEFAULT 'manual',
  is_active   BOOLEAN DEFAULT true,
  ...
)
```

- **상위 팀 역할의 하위 자동 상속**: 상위 팀에 TeamRole로 Role을 부여하면 하위 팀 소속 멤버에게 자동 상속된다. 합산(additive-only)이며 DENY 규칙은 없다.
- **유효 역할 산출**: `유효 역할(userId) = UserRole(직접) ∪ TeamRole(소속 팀) ∪ TeamRole(소속 팀의 상위 팀 ... 루트까지)`
- **team_source 필드**: `manual`(관리자가 수동 생성한 목적별 팀)과 `org_sync`(외부 조직도에서 동기화된 팀)을 구분한다. `org_sync` 팀은 멤버 직접 편집이 제한된다.

### 2. OrgProvider 인터페이스 — 조직도 조회 추상화

조직도 조회(사용자의 소속 팀 + 상위 팀 목록)를 인터페이스로 추상화하여, 데이터 소스를 환경변수(`ORG_SOURCE`)로 전환할 수 있도록 한다.

```typescript
interface OrgProvider {
  getUserAncestorTeamIds(userId: string): Promise<string[]>;
}
```

| 시점 | ORG_SOURCE | Provider | 동작 |
|------|-----------|----------|------|
| 현재 | `local` | LocalOrgProvider | AICM DB의 Team(parent_id) 재귀 순회 |
| 향후 | `user_service` | UserServiceOrgProvider | 외부 UserService API 호출 + Redis 캐싱 |

```typescript
@Module({
  providers: [
    {
      provide: ORG_PROVIDER,
      useFactory: (config: ConfigService) => {
        return config.get('ORG_SOURCE') === 'user_service'
          ? new UserServiceOrgProvider(config)
          : new LocalOrgProvider(config);
      },
      inject: [ConfigService],
    },
  ],
})
export class AuthModule {}
```

기존 AuthProvider(인증 분기: `DEPLOY_MODE`)와 동일한 Provider 패턴을 사용하되, OrgProvider는 `ORG_SOURCE` 환경변수로 독립 분기한다. 인증 모드와 조직도 소스가 반드시 1:1 대응하지 않기 때문이다.

### 3. Restriction에서의 Team 활용

문서/블록 접근 제한(Restriction)의 화이트리스트 대상으로 `subject_type = 'TEAM'`을 지원한다. 해당 팀의 active 멤버(TeamMember) 전원에게 지정된 action이 허용된다.

Restriction은 BoardPermission 상속을 차단하고 화이트리스트 대상만 허용하는 **축소 메커니즘**이므로, Role이 아닌 Team(실체)으로 대상을 지정하는 것이 의미적으로 적합하다.

### 4. 기각된 대안

| 대안 | 기각 사유 |
|------|----------|
| 플랫 팀 구조 (계층 없음) | 고객사 조직도 패턴(부서 → 팀 → 파트)을 표현할 수 없고, 상위 조직 단위의 역할 일괄 부여가 불가 |
| 조직도 조회를 직접 DB 쿼리로 고정 | 향후 외부 UserService 연동 시 코드 전면 수정 필요. Provider 패턴으로 추상화하면 구현체 교체만으로 대응 가능 |
| Restriction 대상에 Role 사용 | 정규 권한 경로(BoardPermission)가 Role 기반인데 그 상속을 끊고 다시 Role로 허용 대상을 정하면 의미적 모순. Role이 다른 팀에 부여되면 의도치 않은 접근 범위 확대 위험 |
| AuthProvider와 OrgProvider를 동일 환경변수로 분기 | 인증 모드(SaaS/온프렘)와 조직도 소스가 독립적. 온프렘에서도 `org_sync` 팀을 쓸 수 있고, SaaS에서도 초기에는 `local` 모드를 쓸 수 있으므로 독립 분기가 적절 |

## 결과

### 긍정적

- **고객사 조직 구조 지원**: 재귀 트리로 부서 → 팀 → 파트 등 다양한 깊이의 조직 구조를 표현할 수 있다.
- **역할 상속 자동화**: 상위 팀에 역할을 부여하면 하위 멤버에게 자동 전파되어 관리 부담이 감소한다.
- **배포 환경 유연성**: OrgProvider 추상화로 조직도 데이터 소스를 런타임에 전환할 수 있어, 초기 개발(local) → 외부 연동(user_service)으로 점진적 전환이 가능하다.
- **접근 제한 표현력**: Restriction에서 팀 단위 화이트리스트를 지원하여 "이 팀 전원에게 허용"이라는 직관적 정책을 표현할 수 있다.

### 부정적

- **계층 순회 비용**: 유효 역할 산출 시 소속 팀부터 루트까지 parent_id를 재귀 순회해야 한다. Redis 캐싱(TTL 5분)으로 완화하며, 10팀 × 5뎁스 규모에서는 성능 문제 없음을 전제로 한다.
- **대량 캐시 무효화**: 상위 팀의 TeamRole이 변경되면 하위 팀 소속 멤버 전원의 권한 캐시를 무효화해야 한다. `SCAN` + Pipeline 배치 삭제로 대응하되, 팀 규모가 크게 성장하면 무효화 범위 최적화를 검토해야 한다.
- **OrgProvider 이중 캐시**: UserServiceOrgProvider 전환 시 Provider 레벨 캐시와 PermissionService 레벨 캐시가 이중 레이어가 된다. 전환 시점에 `perm:teams:{userId}` 캐시를 제거하고 OrgProvider 레벨 캐시(`org:teams:{userId}`, TTL 10분)로 통합해야 한다.

## 참고

- [모듈 아키텍처 §3.4](../02-architecture/02-module-architecture.md) — Provider 패턴 적용 범위
- [인증/인가 아키텍처 §3~§4, §8](../02-architecture/03-auth-architecture.md) — 유효 역할 산출, OrgProvider 패턴
- [인가 아키텍처 §3](../02-architecture/04-permission-architecture.md) — Role과 Team, 합집합 모델
- [AuthModule 엔티티](../03-module-design/auth/data.md) — Team, TeamMember, TeamRole DDL
