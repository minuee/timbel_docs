# Field Validation Protocol

## 1. 목적
실제 회의 환경에서 앱/서버/backend가 사용 가능한지, STT 품질과 운영성이 개선되는지 검증한다.

## 2. 시나리오
### FV-1
- 실제 회의
- same app
- start anchor 유지
- 20~40분 세션

### FV-2
- anchor 완화 pilot
- 실제 운영성 비교

### FV-3
- 실제 운영 시뮬레이션
- 사용자 불편 / 업로드 성공률 / operator 부담 확인

## 3. 비교군
- 중앙 마이크 1개 결과
- 단순 mix 결과
- 현재 시스템 결과

## 4. 수집 항목
- raw audio
- metadata
- processing log
- STT 결과
- listening review
- operator notes
- participant feedback

## 5. 평가 항목
- STT 누락 감소 여부
- 작은 목소리 보존 여부
- overlap 구간 개선 여부
- 하울링 / 번짐 여부
- operator workflow 부담

## 6. 목적
field validation은 기술 검증이 아니라 제품 검증이다.
