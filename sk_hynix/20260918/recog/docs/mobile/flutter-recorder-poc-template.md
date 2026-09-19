# Flutter Recorder PoC Result Template

## 1. 목적
이 문서는 Flutter recorder PoC의 결과를 일관된 형식으로 기록하기 위한 템플릿이다. 목적은 iOS/Android에서 연구 baseline인 `WAV / PCM / 48kHz / mono` 녹음이 실제로 가능한지 빠르게 판단하는 것이다.

## 2. 기본 정보
- 날짜:
- 작성자:
- Flutter 버전:
- Recorder plugin 이름:
- Plugin 버전:
- 테스트 브랜치:
- 테스트 디바이스 수:

## 3. 테스트 환경
### iOS
- 기기 모델:
- iOS 버전:
- 앱 빌드 방식:
- built-in mic 사용 여부:

### Android
- 기기 모델:
- Android 버전:
- 앱 빌드 방식:
- built-in mic 사용 여부:

## 4. 목표 baseline
- container: `wav`
- codec: `pcm_s16le`
- sample rate: `48000`
- channels: `1`

## 5. 수행 절차
1. Flutter 앱 실행
2. recorder plugin으로 녹음 시작/정지
3. iOS 파일 1개 생성
4. Android 파일 1개 생성
5. 생성 파일을 아래 스크립트로 검사

```bash
python3 tools/check_recorder_baseline.py <path/to/file.wav>
```

## 6. 결과 기록
### iOS 결과
- 생성 파일 경로:
- 녹음 성공 여부:
- route 감지 가능 여부:
- recording_started_at 기록 가능 여부:
- `check_recorder_baseline.py` 결과:
```json
{
  "path": "",
  "baseline_valid": false,
  "container": "",
  "codec": "",
  "sample_rate_hz": 0,
  "channels": 0,
  "duration_seconds": 0,
  "violations": []
}
```

### Android 결과
- 생성 파일 경로:
- 녹음 성공 여부:
- route 감지 가능 여부:
- recording_started_at 기록 가능 여부:
- `check_recorder_baseline.py` 결과:
```json
{
  "path": "",
  "baseline_valid": false,
  "container": "",
  "codec": "",
  "sample_rate_hz": 0,
  "channels": 0,
  "duration_seconds": 0,
  "violations": []
}
```

## 7. 세부 판정
### 7.1 포맷
- [ ] iOS에서 WAV 가능
- [ ] Android에서 WAV 가능
- [ ] iOS에서 PCM 확인
- [ ] Android에서 PCM 확인
- [ ] iOS에서 48kHz 확인
- [ ] Android에서 48kHz 확인
- [ ] iOS에서 mono 확인
- [ ] Android에서 mono 확인

### 7.2 제어 가능성
- [ ] iOS에서 녹음 시작 시각 기록 가능
- [ ] Android에서 녹음 시작 시각 기록 가능
- [ ] iOS에서 route 감지 가능
- [ ] Android에서 route 감지 가능

### 7.3 리스크
- [ ] iOS plugin limitation 존재
- [ ] Android plugin limitation 존재
- [ ] native bridge 필요 가능성 있음

## 8. 결과 해석
### 성공
둘 다 `baseline_valid=true`이면 Flutter baseline recorder 전략 유지 가능.

### 부분 성공
한 플랫폼만 통과하면:
- plugin 교체 검토
- platform-specific native bridge 검토

### 실패
둘 다 baseline 미충족이면:
- Flutter plugin 재검토
- native recorder 모듈 전략 검토

## 9. 결론
- 현재 판정:
- 다음 액션:
- 구현 전략 유지/수정 여부:
