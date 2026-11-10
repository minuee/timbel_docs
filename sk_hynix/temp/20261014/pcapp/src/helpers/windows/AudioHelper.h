#pragma once

#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audiopolicy.h>
#include <endpointvolume.h>
#include <mmsystem.h>
#include <bcrypt.h>
#include <iostream>
#include <string>
#include <vector>
#include <thread>
#include <atomic>
#include <mutex>
#include <queue>
#include <deque>
#include <memory>
#include <cmath>
#include "simple_json.hpp"
#include "WavWriter.h"

#pragma comment(lib, "bcrypt.lib")

using json = SimpleJson;

// 전방 선언
class AudioHelper;

// 세그먼트 관리 클래스
class SegmentManager {
private:
    std::vector<int16_t> segmentBuffer;
    uint64_t currentSegmentSamples = 0;
    uint64_t segmentIndex = 0;
    std::string outputDirectory;
    bool encryptionEnabled = true;
    AudioHelper* pAudioHelper = nullptr;
    uint64_t segmentDurationSamples = 0; // 런타임 조절 가능 (ctor에서 기본값 설정)
    std::string fileExtension = ".pcm"; // 기본 확장자
    // 녹음 회차(take) 접미사 상태
    uint32_t runSuffix = 0;          // 0이면 괄호 생략, 1부터 (1), (2) ...
    bool runSuffixLocked = false;    // 이번 run에서 한 번만 결정
    
public:
    SegmentManager(AudioHelper* helper);
    ~SegmentManager();
    
    void SetOutputDirectory(const std::string& dir);
    void SetEncryptionEnabled(bool enabled);
    void SetSegmentDurationSeconds(uint32_t seconds);
    void SetFileExtension(const std::string& ext);
    void AddSamples(const int16_t* samples, size_t count);
    void FinalizeCurrentSegment();
    void Reset();
    // 현재 세그먼트를 저장하지 않고 폐기 (max_ms 초과 종료 시 사용)
    void DiscardCurrentSegment();
    // 현재 세그먼트에 데이터가 남아있는지 여부
    bool HasPendingSamples() const;
    
private:
    void SaveSegment();
    void EncryptAndSave(const std::vector<int16_t>& data, const std::string& filePath);
    std::string GenerateSegmentPath();
    void EnsureRunSuffix();
};

// 장치 변경 감지를 위한 클래스
class DeviceChangeNotifier : public IMMNotificationClient {
private:
    LONG m_cRef;
    AudioHelper* m_pAudioHelper;
    
public:
    DeviceChangeNotifier(AudioHelper* pHelper);
    virtual ~DeviceChangeNotifier();
    
    // IUnknown 메서드
    ULONG STDMETHODCALLTYPE AddRef() override;
    ULONG STDMETHODCALLTYPE Release() override;
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, VOID** ppvInterface) override;
    
    // IMMNotificationClient 메서드
    HRESULT STDMETHODCALLTYPE OnDeviceStateChanged(LPCWSTR pwstrDeviceId, DWORD dwNewState) override;
    HRESULT STDMETHODCALLTYPE OnDeviceAdded(LPCWSTR pwstrDeviceId) override;
    HRESULT STDMETHODCALLTYPE OnDeviceRemoved(LPCWSTR pwstrDeviceId) override;
    HRESULT STDMETHODCALLTYPE OnDefaultDeviceChanged(EDataFlow flow, ERole role, LPCWSTR pwstrDefaultDeviceId) override;
    HRESULT STDMETHODCALLTYPE OnPropertyValueChanged(LPCWSTR pwstrDeviceId, const PROPERTYKEY key) override;
};

// 링크할 라이브러리들
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib") 
#pragma comment(lib, "avrt.lib")
#pragma comment(lib, "winmm.lib")

// WASAPI 관련 상수
const REFERENCE_TIME REFTIMES_PER_SEC = 10000000;
const REFERENCE_TIME REFTIMES_PER_MILLISEC = 10000;

// 오디오 설정 상수
struct AudioConfig {
    static const int SAMPLE_RATE = 16000;
    static const int CHANNELS = 1;
    static const int BITS_PER_SAMPLE = 16;
    static const int BLOCK_MS = 20;
    static const int RINGBUF_TARGET_MS = 150;
    static const int RINGBUF_MIN_MS = 60;
    static const int RINGBUF_MAX_MS = 300;
    static const int FADE_MS = 4;
    
    // 세그먼트 관리 (샘플 프레임 기반)
    static const uint64_t SEGMENT_DURATION_SAMPLES = 180 * 16000; // 기본 3분 = 2,880,000 샘플
    static const size_t BLOCK_SAMPLES = (SAMPLE_RATE * BLOCK_MS) / 1000; // 20ms = 320 샘플
    
    static const double GAIN_MIC;
    static const double GAIN_SYS;
    static const double SILENCE_THRESHOLD;
};

// 디바이스 정보 구조체
struct AudioDevice {
    std::wstring id;
    std::wstring name;
    bool isDefault = false;
    bool isInput = true;
};

// 오디오 블록 구조체
struct AudioBlock {
    std::vector<int16_t> samples;
    uint64_t timestamp_ms;
    size_t sample_count;
    
    AudioBlock(size_t size) : samples(size), timestamp_ms(0), sample_count(size) {}
};

// 링버퍼 클래스
template<typename T>
class RingBuffer {
private:
    std::vector<T> buffer;
    size_t write_pos = 0;
    size_t read_pos = 0;
    size_t size = 0;
    size_t capacity;
    mutable std::mutex mutex;

public:
    RingBuffer(size_t cap) : buffer(cap), capacity(cap) {}
    
    void push(const T& item) {
        std::lock_guard<std::mutex> lock(mutex);
        buffer[write_pos] = item;
        write_pos = (write_pos + 1) % capacity;
        if (size < capacity) {
            size++;
        } else {
            read_pos = (read_pos + 1) % capacity; // 오버라이트
        }
    }
    
    bool pop(T& item) {
        std::lock_guard<std::mutex> lock(mutex);
        if (size == 0) return false;
        item = buffer[read_pos];
        read_pos = (read_pos + 1) % capacity;
        size--;
        return true;
    }
    
    size_t getSize() const {
        std::lock_guard<std::mutex> lock(mutex);
        return size;
    }
    
    void clear() {
        std::lock_guard<std::mutex> lock(mutex);
        write_pos = read_pos = size = 0;
    }
};

// 레벨 계산 도우미
class LevelMeter {
private:
    double rms_sum = 0.0;
    size_t sample_count = 0;
    
public:
    void addSamples(const int16_t* samples, size_t count) {
        for (size_t i = 0; i < count; i++) {
            double normalized = samples[i] / 32768.0;
            rms_sum += normalized * normalized;
            sample_count++;
        }
    }
    
    double getRMSAndReset() {
        if (sample_count == 0) return 0.0;
        double rms = sqrt(rms_sum / sample_count);
        rms_sum = 0.0;
        sample_count = 0;
        return rms;
    }
};

// 간단한 NLMS 기반 에코 캔슬러
class EchoCanceller {
private:
    size_t filterLen;
    float stepMu;
    float epsilon;
    std::vector<float> weights;      // 적응 필터 계수
    std::vector<float> refHistory;   // far-end(history)
    size_t histIndex = 0;
public:
    // len: 필터 길이(탭 수), mu: 학습률
    EchoCanceller(size_t len, float mu)
        : filterLen(len), stepMu(mu), epsilon(1e-6f), weights(len, 0.0f), refHistory(len, 0.0f), histIndex(0) {}
    
    void Reset() {
        std::fill(weights.begin(), weights.end(), 0.0f);
        std::fill(refHistory.begin(), refHistory.end(), 0.0f);
        histIndex = 0;
    }
    
    // farIn: 시스템(loopback) 참조, nearIn: 마이크 신호(에코 포함)
    // out: 에코 제거된 마이크 결과
    void ProcessFrame(const float* farIn, const float* nearIn, float* out, size_t count, bool adapt) {
        for (size_t n = 0; n < count; ++n) {
            // 참조 샘플을 히스토리에 기록
            refHistory[histIndex] = farIn ? farIn[n] : 0.0f;

            // 필터 출력 y = w^T x (x는 최신부터 과거 순의 참조 벡터)
            float y = 0.0f;
            float normX = epsilon;
            size_t idx = histIndex;
            for (size_t k = 0; k < filterLen; ++k) {
                float xk = refHistory[idx];
                y += weights[k] * xk;
                normX += xk * xk;
                // 순환 인덱스 감소
                if (idx == 0) idx = filterLen - 1; else idx--;
            }

            // 에러 e = near - y
            float e = nearIn[n] - y;
            out[n] = e;

            // NLMS 계수 업데이트: w += (mu * e * x) / (epsilon + ||x||^2)
            if (adapt) {
                float g = stepMu * e / normX;
                idx = histIndex;
                for (size_t k = 0; k < filterLen; ++k) {
                    float xk = refHistory[idx];
                    weights[k] += g * xk;
                    if (idx == 0) idx = filterLen - 1; else idx--;
                }
            }

            // 히스토리 인덱스 증가(순환)
            histIndex++;
            if (histIndex >= filterLen) histIndex = 0;
        }
    }
};

// AEC 백엔드 타입
enum class AecBackendType {
    NLMS,
    WEBRTC
};

// AEC 백엔드 인터페이스
class IAecBackend {
public:
    virtual ~IAecBackend() {}
    virtual void Reset() = 0;
    virtual void ProcessFrame(const float* farIn, const float* nearIn, float* out, size_t count, bool adapt) = 0;
};

// NLMS 백엔드 구현(기존 EchoCanceller 래핑)
class NlmsAecBackend : public IAecBackend {
private:
    EchoCanceller nlms;
public:
    NlmsAecBackend(size_t len, float mu) : nlms(len, mu) {}
    void Reset() override { nlms.Reset(); }
    void ProcessFrame(const float* farIn, const float* nearIn, float* out, size_t count, bool adapt) override {
        nlms.ProcessFrame(farIn, nearIn, out, count, adapt);
    }
};

// WebRTC AEC 백엔드 (실사용: APM 연동)
class WebRtcAecBackend : public IAecBackend {
private:
#ifdef WEBRTC_APM_AVAILABLE
    // 전방 선언으로 포인터만 보관 (헤더 의존 최소화)
    struct WebRtcState { 
        void* apm; 
        class AudioHelper* parent; // 지연 추정값 접근용
        int current_delay_ms;      // 현재 사용 중인 지연값
        int target_delay_ms;       // 목표 지연값
        int frame_count;           // 프레임 카운터
    };
    std::unique_ptr<WebRtcState> state;
#endif
    uint32_t sampleRate;
    int channels;
public:
    explicit WebRtcAecBackend(uint32_t sr, int ch = 1, AudioHelper* parent = nullptr) 
        : sampleRate(sr), channels(ch) {
#ifdef WEBRTC_APM_AVAILABLE
        // parent 포인터를 state에 저장 (Reset()에서 사용)
        if (!state) state = std::make_unique<WebRtcState>();
        state->parent = parent;
        state->current_delay_ms = 80;  // 기본 80ms 지연
        state->target_delay_ms = 80;
        state->frame_count = 0;
#endif
    }
    void Reset() override;
    void ProcessFrame(const float* farIn, const float* nearIn, float* out, size_t count, bool adapt) override;
};

// 가이드 문서의 AudioProcessor 클래스 추가
class AudioProcessor {
private:
#ifdef WEBRTC_APM_AVAILABLE
    void* apm_ptr;  // webrtc::AudioProcessing* 포인터
    struct StreamConfig {
        int sample_rate;
        int channels;
        StreamConfig() : sample_rate(0), channels(0) {}
        StreamConfig(int sr, int ch) : sample_rate(sr), channels(ch) {}
    } stream_config_;
#endif
    int sample_rate_;
    int channels_;
    bool initialized_;
    
public:
    AudioProcessor() : sample_rate_(0), channels_(0), initialized_(false) {
#ifdef WEBRTC_APM_AVAILABLE
        apm_ptr = nullptr;
#endif
    }
    
    ~AudioProcessor() {
        Cleanup();
    }
    
    bool Initialize(int sample_rate, int channels);
    void Cleanup();
    
    // 시스템 오디오 (참조 신호) 처리
    int ProcessReverseStream(float* audio_data, int samples_per_channel);
    
    // 마이크 오디오 (에코 제거 적용) 처리
    int ProcessStream(float* audio_data, int samples_per_channel);
    
    // 통계 정보 가져오기 (간단한 구현)
    void GetStatistics();
    
    bool IsInitialized() const { return initialized_; }
};

// 오디오 캡처 모드
enum class CaptureMode {
    MicOnly,
    MicPlusSystem, 
    SystemOnly
};

// 메인 오디오 헬퍼 클래스
class AudioHelper {
    friend class SegmentManager; // SegmentManager가 private 멤버에 접근할 수 있도록 허용
    friend class DeviceChangeNotifier; // DeviceChangeNotifier가 변경 이벤트 처리에 접근할 수 있도록 허용
private:
    // COM 인터페이스들
    IMMDeviceEnumerator* pEnumerator = nullptr;
    IMMDevice* pMicDevice = nullptr;
    IMMDevice* pSysDevice = nullptr;
    IAudioClient* pMicClient = nullptr;
    IAudioClient* pSysClient = nullptr;
    IAudioCaptureClient* pMicCaptureClient = nullptr;
    IAudioCaptureClient* pSysCaptureClient = nullptr;
    
    // 장치 변경 감지
    DeviceChangeNotifier* pDeviceNotifier = nullptr;
    std::atomic<bool> deviceChangeRequested{false};
    std::wstring currentSysDeviceId;
    std::wstring currentMicDeviceId;
    // 기본장치 추종 여부: true면 OS 기본장치 변화를 따른다, false면 사용자가 고정 선택
    // 기본장치 추종 제거: 사용자가 선택한 마이크만 사용
    // std::atomic<bool> micFollowsDefault{true};
    std::atomic<bool> micStopScheduled{false};
    // 장치 문제로 인해 세션 재개를 차단하는 플래그
    std::atomic<bool> resumeBlockedDueToMic{false};
    // 에러 이벤트 중복 방지 / 원인 전달
    std::atomic<bool> stopErrorSent{false};
    std::atomic<bool> stoppingDueToMicRemoval{false};
    // 선택/세션 마이크가 실제로 'ACTIVE' 상태인지 검증
    bool IsMicDeviceActive(const std::wstring& devId) const;
    // 선택된 마이크가 ACTIVE 상태인지 간편 확인
    bool IsSelectedMicActive() const { return IsMicDeviceActive(selectedMicId); }
    // ACTIVE 캡처 엔드포인트가 하나뿐이면 그 ID 반환, 아니면 빈 문자열
    std::wstring PickSingleActiveMicId() const;
    
    // 세그먼트 관리
    std::unique_ptr<SegmentManager> segmentManager;
    
    // 스레드 및 동기화
    std::thread micThread;
    std::thread sysThread;
    std::thread mixThread;
    std::thread watchdogThread;
    std::atomic<bool> isRunning{false};
    std::atomic<bool> isPaused{false};
    std::atomic<bool> isTestMode{false};
    std::atomic<bool> isRecording{false};
    std::atomic<bool> drainOnStop{false};
    std::atomic<bool> stopDueToMaxDuration{false};
    std::atomic<bool> stopDueToLowDisk{false};
    std::atomic<bool> stopAtBoundary{false};
    std::atomic<bool> boundaryStopScheduled{false};
    
    // 설정
    CaptureMode currentMode = CaptureMode::MicOnly;
    std::wstring selectedMicId; // UI가 선택해 둔 상태(영구 유지)
    std::wstring sessionMicId;  // 이번 세션(테스트/레코딩)에서만 사용할 마이크 ID
    bool HasSelectedMic() const { return !selectedMicId.empty(); }
    std::string sessionId;
    std::wstring outputDirectory; // 출력 디렉터리
    bool debugRawSaveEnabled = false; // 디버그 파일 저장 토글
    
    // 오디오 데이터 처리
    RingBuffer<float> sysAudioBuffer;
    LevelMeter micLevelMeter;
    LevelMeter sysLevelMeter;
    std::vector<int16_t> outputBuffer;
    WavWriter micDebugWriter;
    bool micDebugOpened = false;
    uint64_t micSamplesWritten = 0;
    WavWriter sysDebugWriter;
    bool sysDebugOpened = false;
    uint64_t sysSamplesWritten = 0;
    uint32_t sysDebugSampleRate = 0;
    uint32_t micDebugSampleRate = 0;
    // 믹싱용 FIFO(16 kHz, mono)
    std::deque<float> micFifo16k;
    std::deque<float> sysFifo16k;
    std::mutex micFifoMutex;
    std::mutex sysFifoMutex;
    WavWriter mixDebugWriter;
    bool mixDebugOpened = false;
    std::wstring mixFilePath; // 세션별 믹스 파일 경로(고정)
    uint64_t micPushed16kTotal = 0; // 믹싱 대상(16k) 기준 마이크 누적 샘플 수
    // 상태 보존형 리샘플러 상태
    double micResamplePhase = 0.0;
    float micResampleLast = 0.0f;
    uint32_t micResampleInRate = 0;
    double sysResamplePhase = 0.0;
    float sysResampleLast = 0.0f;
    uint32_t sysResampleInRate = 0;
    // 장치 전환 직후 클릭 방지를 위한 페이드 인 상태 (한글 주석)
    size_t fadeSamplesRemaining = 0; // 남은 페이드 샘플 수
    size_t fadeTotalSamples = 0;     // 전체 페이드 샘플 수
    
    // SystemOnly 재진입 경계 페이드인 상태 (시스템 데이터가 0→신호로 전환될 때만 적용)
    size_t sysReentryFadeRemaining = 0; // 남은 페이드 샘플 수
    size_t sysReentryFadeTotal = 0;     // 전체 페이드 샘플 수
    bool   sysHadDataPrevChunk = false; // 직전 블록에 시스템 데이터 존재 여부
    
    // 통계 및 상태
    uint64_t totalSamples = 0;
    uint64_t startTimeMs = 0;
    uint64_t maxDurationMs = 0; // 0이면 제한 없음
    uint64_t mixStartTimeMs = 0; // 첫 믹스 블록 출력 시각(ms)
    // AEC 드리프트 모니터링(10ms 프레임 기준)
    uint64_t aecReverseFramesPresent10ms = 0;
    uint64_t aecCaptureFrames10ms = 0;
    std::chrono::steady_clock::time_point aecLastDriftLog;
    std::atomic<bool> silenceDetected{false};
    uint64_t silenceStartMs = 0;
    bool sustainedEventSent = false; // 30초 sustained 이벤트 전송 여부
    bool silenceDetectionDisabled = false; // 무음 감지 비활성화 플래그
    uint32_t lastEarlyWarningIndex = 0; // 7초 경고 전송 인덱스(0,1,2,3,4)

    // 음소거 상태
    std::atomic<bool> muteMic{false};
    std::atomic<bool> muteSystem{false};

    // 레벨미터 토글 상태
    std::atomic<bool> levelMeterEnabled{true};
    std::atomic<bool> startedByLevelMeter{false};
    // 자동 재시작/재초기화 상태
    // std::atomic<bool> autoRestartScheduled{false};
    std::atomic<bool> reinitInProgress{false};
    // 레벨미터 자동 재시작 디바운스/백오프 상태
    std::atomic<bool> autoRestartScheduled{false};
    uint32_t autoRestartMaxAttempts = 3;
    
    // 웨이브폼 데이터
    std::vector<float> waveformBuffer;
    size_t waveformIndex = 0;

    // AEC 관련
    std::unique_ptr<IAecBackend> aecBackend;
    AecBackendType aecBackendType = AecBackendType::NLMS;
    bool aecEnabled = true; // MicPlusSystem에서만 적용
    
    // 가이드 문서의 AudioProcessor 추가
    std::unique_ptr<AudioProcessor> audioProcessor;
    size_t aecFilterLength = 4096; // ~256ms @16kHz, 긴 잔향 대응
    float aecMu = 0.02f; // 학습률 완화로 발산 방지
    // HPF(하이패스) 전처리 상태
    float micHP_x1 = 0.0f, micHP_y1 = 0.0f;
    float sysHP_x1 = 0.0f, sysHP_y1 = 0.0f;
    float hpAlpha = 0.96f; // ~100Hz 컷오프 근사

    void HighPassProcess(std::vector<float>& data, float& x1, float& y1) {
        // 1차 고역통과: y[n] = x[n] - x[n-1] + alpha*y[n-1]
        for (size_t i = 0; i < data.size(); ++i) {
            float x = data[i];
            float y = (x - x1) + hpAlpha * y1;
            data[i] = y;
            x1 = x; y1 = y;
        }
    }

    // 마이크 노이즈 저감을 위한 다운워드 익스팬더 상태/파라미터
    bool micExpanderEnabled = false; // 기본은 OFF (사용자가 원하면 켜기)
    float micExpanderThresholdRms = 0.0056f; // 약 -45 dBFS
    float micExpanderRatio = 2.0f;           // 2:1
    float micExpanderNoiseFloor = 0.12f;     // 약 -18 dBFS
    float micExpanderAttackMs = 10.0f;
    float micExpanderReleaseMs = 150.0f;
    float micExpanderHangMs = 80.0f;
    // 상태
    float micExpanderEnv = 0.0f;
    float micExpanderGain = 1.0f;
    uint32_t micExpanderHangSamplesLeft = 0;
    void ApplyMicExpander(std::vector<float>& data, uint32_t sampleRate);

    // 고정 지연 보상 (far-end 참조를 일정 샘플만큼 지연)
    size_t aecFixedDelayMs = 80; // 기본 80ms
    size_t aecFixedDelaySamples = 0; // 생성자에서 계산
    std::deque<float> aecRefDelayLine;
    void PrepareDelayedReference(const std::vector<float>& refIn, std::vector<float>& refOut, size_t count);

    // 동적 지연 추정용 히스토리(HPF 적용 신호 저장)
    size_t aecDelayWindowMs = 200; // 200ms 윈도우
    size_t aecDelayWindowSamples = 0;
    size_t aecMaxLagMs = 500; // 최대 150ms 지연 탐색
    size_t aecMaxLagSamples = 0;
    std::deque<float> aecMicHPHist;
    std::deque<float> aecSysHPHist;
    double aecDelaySmoothAlpha = 0.2; // 지연 추정 스무딩
    double aecFixedDelayEstimate = 0.0; // 부동 소수 추정치
    std::chrono::steady_clock::time_point aecLastDelayUpdate;
    void AppendAecHistory(const std::vector<float>& micHP, const std::vector<float>& sysHP);
    void MaybeUpdateAecDelay();
    
    // 내부 메서드들
    HRESULT InitializeCOM();
    HRESULT InitializeDeviceEnumerator();
    HRESULT GetDefaultDevice(EDataFlow dataFlow, IMMDevice** ppDevice);
    HRESULT GetDeviceById(const std::wstring& id, IMMDevice** ppDevice);
    HRESULT InitializeAudioClient(IMMDevice* pDevice, IAudioClient** ppClient, 
                                   IAudioCaptureClient** ppCaptureClient, bool isLoopback = false);
    
    // 장치 변경 처리
    void RegisterDeviceNotifications();
    void UnregisterDeviceNotifications();
    void OnSystemDeviceChanged();
    bool ReconnectSystemDevice();
    void CleanupSystemDevice();
    void NotifyMicDeviceChanged(const std::string& reason);
    void StopRecordingAsyncWithMicError(const std::string& code, const std::string& message);
    void StopRecordingAsyncWithDiskLow(const std::string& code, const std::string& message);
    
    void MicrophoneCaptureThread();
    void SystemCaptureThread();
    void MixingThread();
    
    void ProcessMicrophoneData(const BYTE* pData, UINT32 numFrames, WAVEFORMATEX* pFormat);
    void ProcessSystemData(const BYTE* pData, UINT32 numFrames, WAVEFORMATEX* pFormat);
    void SaveMicDebugIfEnabled(const int16_t* samples, size_t count, uint32_t sampleRate);
    void SaveSystemDebugIfEnabled(const int16_t* samples, size_t count, uint32_t sampleRate);
    void FinalizeDebugLengths();
    void PushToFifo(std::deque<float>& fifo, std::mutex& mtx, const float* samples, size_t count);
    size_t PopFromFifo(std::deque<float>& fifo, std::mutex& mtx, float* out, size_t wantCount);
    void EnsureOpenMixDebug();
    void MixBlockAndWrite(size_t chunkSamples);

    // 명령 처리: 음소거 설정
    void HandleSetMute(const json& params);
    // 명령 처리: 레벨미터 on/off
    void HandleSetLevelMeter(const json& params);

    // 레벨미터 전용 캡쳐 시작(파일 저장 없음) 필요 시 시작
    void StartLevelMeterCaptureIfNeeded();
    
    // 가이드 문서의 ProcessCapturedAudio 함수
    void ProcessCapturedAudio(float* mic_data, float* system_data, int samples_per_channel);
    void ResampleLinearMono(const float* in, size_t inFrames, uint32_t inRate, uint32_t outRate, std::vector<float>& out);
    void ResampleLinearMonoStateful(const float* in, size_t inFrames, uint32_t inRate, uint32_t outRate,
                                    std::vector<float>& out, double& phase, float& lastSample, uint32_t& stateInRate);
    size_t FifoSize(const std::deque<float>& fifo, std::mutex& mtx);
    uint64_t mixSamplesWritten = 0;
    void MixWhileReady(bool flushAll);
    
    void ConvertToMono16(const float* input, int16_t* output, size_t frames);
    void ApplyGainAndMix(int16_t* micData, const float* sysData, size_t frames, double micGain, double sysGain);

    // 디스크 상태 이벤트(주기) – helper→UI 통지
    void CheckAndEmitDiskStatusIfDue();
    bool QueryFreeBytes(uint64_t& freeBytes);
    uint64_t lastDiskStatusMs = 0;
    std::string lastDiskStatusCategory; // "ok" | "low" | "critical"
    uint64_t lastDiskStatusEventMs = 0; // 마지막 이벤트 실제 전송 시각(ms)
    
    void UpdateLevels(const int16_t* samples, size_t count);
    void UpdateWaveform(const int16_t* samples, size_t count);
    void DetectSilence(const int16_t* samples, size_t count);
    
    void SendEvent(const json& event);
    void SendError(const std::string& code, const std::string& message);
    void SendLevelEvent(const std::string& source, double rms);
    void SendProgressEvent();
    void SendWaveformEvent();
    void SendMicStateEvent(const char* state);
    
    uint64_t GetCurrentTimeMs();
    bool HasActiveCaptureDevice();
    void ScheduleLevelMeterAutoRestart(const std::string& reason);

public:
    AudioHelper();
    ~AudioHelper();
    
    bool Initialize();
    void Cleanup();
    
    // 명령 처리
    void ProcessCommand(const json& command);
    
    // AudioProcessor 초기화 (가이드 문서 기반)
    bool InitializeAudioProcessing(int sample_rate, int channels);
    void HandleGetVersion();
    void HandleListDevices();
    void HandleStartTest(const json& params);
    void HandleStopTest();
    void HandleStart(const json& params);
    void HandlePause();
    void HandleResume();
    void HandleStop();
    // HandleMark 함수는 제거됨 - 메모는 UI에서만 처리
    void HandleSetOutputDir(const json& params);
    void HandleSetDebugFiles(const json& params);
    void HandleSetSegmentConfig(const json& params);
    // 강제 재초기화 핸들러 및 유틸
    void HandleReinitAudio(const json& params);
    bool IsSameDeviceId(const std::wstring& a, const std::wstring& b);
    void StartWatchdogIfNeeded();
    
    // 장치 변경 콜백 (DeviceChangeNotifier에서 호출)
    void NotifySystemDeviceChanged();
    void OnSelectedMicRestored();
    
    // 메인 실행 루프
    void Run();
};

// 전역 함수들
std::vector<AudioDevice> EnumerateAudioDevices();
std::string WStringToString(const std::wstring& wstr);
std::wstring StringToWString(const std::string& str);