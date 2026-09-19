# Developer Task — Flutter Recorder PoC

## 목적
iOS / Android에서 연구 baseline인 `WAV / PCM / 48kHz / mono` 파일을 실제로 생성할 수 있는지 확인한다.

## 작업 범위
이번 작업은 제품 구현이 아니라 **Recorder feasibility 확인용 PoC**에 한정한다.

## 해야 할 것
1. Flutter 프로젝트 또는 별도 PoC 앱 준비
2. recorder plugin 후보 1개 연결
3. 녹음 시작 / 정지 기능만 구현
4. iOS에서 파일 1개 생성
5. Android에서 파일 1개 생성
6. 생성된 파일을 `tools/check_recorder_baseline.py`로 검사
7. 결과를 `docs/mobile/flutter-recorder-poc-template.md`에 기록

## 하지 말 것
- room/session full flow 구현
- BLE 연동
- 실제 업로드 구현
- DSP 알고리즘 수정
- UI polish

## 성공 기준
- iOS / Android 둘 다에서 파일 생성
- baseline checker로 `wav / pcm_s16le / 48000 / mono` 확인 가능
- route 감지 가능 여부 / timestamp 기록 가능 여부까지 확인

## 결과 정리 형식
- plugin 이름 / 버전
- iOS 결과
- Android 결과
- baseline checker JSON
- 최종 판정:
  - Flutter 유지
  - Flutter + native bridge
  - plugin 교체
  - native recorder 재검토

## 검증 명령
```bash
python3 tools/check_recorder_baseline.py <path/to/file.wav>
```

## 참고 문서
- `docs/implementation/next-steps.md`
- `docs/mobile/flutter-recorder-poc-template.md`
- `docs/policy/recording-policy.md`
- `docs/policy/anchor-policy.md`

## 최종 산출물
- baseline 검사 통과한 파일 2개(iOS / Android)
- PoC 결과 템플릿 작성 완료

## 한 줄 요약
**이번 작업의 목표는 “녹음이 되느냐”가 아니라, “연구 baseline 파일이 실제로 나오느냐”를 확인하는 것이다.**
