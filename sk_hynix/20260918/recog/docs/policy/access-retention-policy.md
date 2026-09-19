# Access / Retention Policy

## 1. 목적
녹음 원본과 파생 artifact의 접근 및 보관 정책을 정의한다.

## 2. 기본 원칙
- raw audio는 민감 데이터로 본다
- derived artifact도 민감 정보가 될 수 있다
- 최소 권한 원칙을 적용한다
- 삭제 기준을 명확히 한다

## 3. 접근 권한
허용 대상:
- session operator
- 지정 reviewer
- processing service account

비허용 대상:
- 세션 외 일반 사용자
- 목적 외 다운로드

## 4. 보관 대상
- raw uploaded files
- canonicalized files
- aligned tracks
- mixdown
- manifests
- evidence bundle

## 5. 보관 기간
- research mode 세션: 추후 확정
- pilot mode 세션: 추후 확정
- hold / investigation 예외: 운영 정책으로 관리

## 6. 삭제 정책
- 세션 retention window 종료 시 raw/derived artifact 동시 삭제
- hold가 없는 경우 자동 삭제 우선
- 삭제 이벤트는 audit trail에 기록

## 7. 로그 / 감사
- manual download 기록
- reviewer access 기록
- deletion 기록
