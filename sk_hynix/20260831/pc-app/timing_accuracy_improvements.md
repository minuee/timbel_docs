# 타이밍 정확도 개선 가이드

> **목적**  
> 2025-09-23에 구현된 타이밍 정확도 개선사항을 상세히 문서화하고, 개발자가 이해하고 활용할 수 있도록 가이드를 제공합니다.

---

## 🎯 개선 목표

### 문제 상황
- UI 표시 시간과 실제 파일 생성 시점 간 2초 차이
// 메모 기능은 Helper 비대상(UI 전용) — 관련 서술 제거
- max_ms 도달 시 UI 상태가 즉시 복구되지 않음

### 해결 목표
- UI-파일 동기화: 2초 → 0.2초 이내
// 메모 타임스탬프 항목 제거
- 자동 정지 시 UI 상태 즉시 복구

---

## 🔧 기술적 개선사항

### 1. t_capture 기반 동기화

#### 개념
- **t_capture**: 마이크에서 실제 캡쳐된 시간 (발화 시점에 가장 근접)
- **t_file**: 실제 파일에 기록된 시간 (저장 위치 기준)

#### 구현
```cpp
// AudioHelper.cpp - SendProgressEvent()
void AudioHelper::SendProgressEvent() {
    double seconds = totalSamples / static_cast<double>(AudioConfig::SAMPLE_RATE);
    json event;
    event.set("ev", "progress");
    event.set("seconds", seconds);           // t_file
    event.set("samples", totalSamples);
    event.set("mic_samples", micPushed16kTotal);  // t_capture
    event.set("mic_seconds", static_cast<double>(micPushed16kTotal) / static_cast<double>(AudioConfig::SAMPLE_RATE));
    SendEvent(event);
}
```

### 2. Progress 이벤트 주기 단축

#### 변경사항
- **이전**: 1초마다 전송 (1Hz)
- **현재**: 200ms마다 전송 (5Hz)
- **추가**: 각 믹스 블록마다 즉시 전송

#### 코드
```cpp
// AudioHelper.cpp - MixBlockAndWrite()
void AudioHelper::MixBlockAndWrite(size_t chunkSamples) {
    // ... 믹싱 로직 ...
    
    // 샘플이 누적될 때마다 진행 상황을 즉시 전송
    SendProgressEvent();
    
    // ... 나머지 로직 ...
}
```

### 3. UI 동기화 개선

#### 렌더러 변경사항
```javascript
// app.js - updateProgress()
updateProgress(event) {
    // t_capture 우선 사용
    const micSeconds = typeof event.mic_seconds === 'number' ? event.mic_seconds : event.seconds;
    this.useProgressClock = true;
    this.lastProgressSeconds = micSeconds;
    
    const elapsedMs = Math.max(0, Math.floor(micSeconds * 1000));
    this.recordingTime.textContent = this.formatTime(elapsedMs);
    // ... 남은 시간 계산 ...
}

// app.js - addMemo()
addMemo() {
    // t_capture 기반 메모 타임스탬프
    const currentTime = this.useProgressClock
        ? Math.max(0, Math.floor(this.lastProgressSeconds * 1000))
        : this.getCurrentRecordingTime();
    // ... 메모 저장 ...
}
```

### 4. 자동 정지 상태 복구

#### 문제
max_ms 도달 시 UI 버튼 상태가 즉시 복구되지 않음

#### 해결
```javascript
// app.js - handleRecordingStopped()
handleRecordingStopped(event) {
    // 자동 정지든 수동 정지든 동일 처리
    this.isRecording = false;
    this.isPaused = false;
    this.stopRecordingTimer();
    this.updateRecordingButtons();  // 즉시 버튼 상태 복구
    this.updateStatus('녹음 완료');
    // ... 상태 초기화 ...
}
```

---

## 📊 성능 개선 결과

### 타이밍 정확도
| 항목 | 이전 | 현재 | 개선율 |
|------|------|------|--------|
| UI-파일 동기화 | ±2초 | ±0.2초 | 90% 개선 |
// 메모 타임스탬프 행 제거
| Progress 전송 주기 | 1초 | 200ms | 5배 향상 |
| UI 시간 표시 안정성 | 불안정 (2배 증가) | 안정적 | 100% 개선 |

### 사용자 경험
// 메모 관련 UX 항목 제거
- ✅ 자동 정지 시 즉시 UI 상태 복구
- ✅ 실시간 진행 상황 표시
- ✅ stop 후 UI 시간 표시 안정화 (2배 증가 문제 해결)
- ✅ 테스트 모드에서 파일 저장 방지

---

## 🔍 기술적 세부사항

### 1. JSON 이벤트 파싱 수정

#### 문제
```cpp
// SimpleJson에서 문자열 리터럴이 bool로 잘못 매칭
event.set("ev", "level");  // "level"이 true로 변환됨
```

#### 해결
```cpp
// simple_json.hpp에 const char* 오버로드 추가
void set(const std::string& key, const char* value) { 
    j_[key] = value ? nlohmann::json(value) : nlohmann::json(""); 
}
```

### 2. max_ms 초과 시 세그먼트 폐기

#### 문제
설정된 시간 초과 시 마지막 미완성 세그먼트가 저장되어 파일 개수 초과

#### 해결
```cpp
// AudioHelper.cpp - HandleStop()
if (stopDueToMaxDuration) {
    LOG_INFO("Discarding last partial segment due to max_ms reached");
    segmentManager->DiscardCurrentSegment();
} else {
    LOG_INFO("Finalizing current segment on stop");
    segmentManager->FinalizeCurrentSegment();
}
```

### 3. 이벤트 중복 로그 억제

#### 문제
"설정된 녹음 시간이 완료되었습니다" 메시지 중복 출력

#### 해결
```javascript
// app.js - timeCompleteLogged 플래그 추가
if (remaining === 0 && !this.timeCompleteLogged) {
    this.logMessage('설정된 녹음 시간이 완료되었습니다', 'warning');
    this.timeCompleteLogged = true;
}
```

### 4. 테스트/녹음 모드 분리

#### 문제
테스트 단계에서 캡쳐된 데이터가 파일로 저장됨

#### 해결
```cpp
// AudioHelper.cpp - isTestMode와 isRecording 플래그 분리
void AudioHelper::MixBlockAndWrite(size_t chunkSamples) {
    // ... 믹싱 로직 ...
    
    // 녹음 모드일 때만 세그먼트에 추가
    if (segmentManager && isRecording) {
        segmentManager->AddSamples(mixedData, chunkSamples);
    }
}
```

### 5. UI 시간 표시 안정화

#### 문제
stop 후 UI 시간이 실제 시간의 2배로 표시됨

#### 해결
```javascript
// app.js - handleSegmentReady() 수정
handleSegmentReady(event) {
    if (typeof event.samples === 'number') {
        const elapsedMsFromSamples = Math.floor((event.samples * 1000) / 16000);
        const progressMs = Math.max(0, Math.floor((this.lastProgressSeconds || 0) * 1000));
        // 중복 계산 방지: 최댓값 선택
        const desiredMs = Math.max(progressMs, elapsedMsFromSamples);
        this.recordingTime.textContent = this.formatTime(desiredMs);
    }
}
```

---

## 🧪 테스트 방법

### 1. 타이밍 정확도 테스트
```bash
# 3분 세그먼트로 녹음 시작
# 2:58-2:59 부근에서 파일 생성 확인
// 메모 입력 관련 테스트 항목 제거
```

### 2. 자동 정지 테스트
```bash
# max_ms=9분으로 설정
# 9분 후 자동 정지 시 버튼 상태 확인
# 세그먼트 파일 개수 확인 (정확히 3개)
```

### 3. Progress 이벤트 테스트
```bash
# 개발자 도구에서 progress 이벤트 빈도 확인
# mic_seconds와 seconds 필드 값 비교
```

---

## 🔮 향후 개선 방향

### 1. 하드웨어 타임스탬프 활용
- WASAPI capture timestamp 사용
- 더 정확한 t_capture 추적

// VAD 기반 메모 스냅 항목 제거

### 3. 실시간 오프셋 추정
- delaySamples = micCapturedSamples - emittedSamples
- 동적 보정값 적용

---

## 📚 관련 문서

- [CHANGELOG.md](./CHANGELOG.md) - 전체 변경 기록
- [DEVELOPMENT_STATUS.md](./DEVELOPMENT_STATUS.md) - 개발 상태 요약
- [electron_helper_interface.md](./electron_helper_interface.md) - API 명세서

---

**이 문서는 타이밍 정확도 개선의 기술적 세부사항과 구현 방법을 상세히 설명합니다.**
