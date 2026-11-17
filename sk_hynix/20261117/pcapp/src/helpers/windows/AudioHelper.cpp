#include <combaseapi.h>
#include "AudioHelper.h"
#include <Mmdeviceapi.h>
#include "versioninfo.h"
#include <comdef.h>
#include <functiondiscoverykeys_devpkey.h>
#include <chrono>
#include <sstream>
#include <iomanip>
#include <filesystem>
#include <algorithm>
#include <fstream>
#include <random>
#include <cstring>
#include "Logger.h"
#include <unordered_set>
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#include <cmath>
#ifdef WEBRTC_APM_AVAILABLE
#if __has_include("api/audio/audio_processing.h")
#include "api/audio/audio_processing.h"
#define HAVE_WEBRTC_API_AP 1
#endif
#if __has_include("modules/audio_processing/include/audio_processing.h")
#include "modules/audio_processing/include/audio_processing.h"
#define HAVE_WEBRTC_MODULES_AP 1
#endif
#endif

#define DISK_STATUS_OK 500ULL * 1024ULL * 1024ULL // 500MB
#define DISK_STATUS_LOW 50ULL * 1024ULL * 1024ULL // 50MB

// DeviceChangeNotifier 구현
DeviceChangeNotifier::DeviceChangeNotifier(AudioHelper* pHelper) 
    : m_cRef(1), m_pAudioHelper(pHelper) {
}

DeviceChangeNotifier::~DeviceChangeNotifier() {
}

ULONG STDMETHODCALLTYPE DeviceChangeNotifier::AddRef() {
    return InterlockedIncrement(&m_cRef);
}

ULONG STDMETHODCALLTYPE DeviceChangeNotifier::Release() {
    ULONG ulRef = InterlockedDecrement(&m_cRef);
    if (0 == ulRef) {
        delete this;
    }
    return ulRef;
}

HRESULT STDMETHODCALLTYPE DeviceChangeNotifier::QueryInterface(REFIID riid, VOID** ppvInterface) {
    if (IID_IUnknown == riid) {
        AddRef();
        *ppvInterface = (IUnknown*)this;
    } else if (__uuidof(IMMNotificationClient) == riid) {
        AddRef();
        *ppvInterface = (IMMNotificationClient*)this;
    } else {
        *ppvInterface = NULL;
        return E_NOINTERFACE;
    }
    return S_OK;
}

HRESULT STDMETHODCALLTYPE DeviceChangeNotifier::OnDeviceStateChanged(LPCWSTR pwstrDeviceId, DWORD dwNewState) {
    LOG_INFO(std::string("Device state changed: ") + WStringToString(pwstrDeviceId) + 
             ", state=" + std::to_string(dwNewState));
    // UI 통지: 상태 변화도 장치 변경으로 간주하여 통지 (한글 주석)
    // native 마이크는 Add/Remove 대신 StateChanged만 발생할 수 있음
    // 녹음 장치와 재생 장치는 각각 다른 엔드포인트이므로 각각 이벤트 전송
    if (m_pAudioHelper && pwstrDeviceId) {
        std::wstring deviceId(pwstrDeviceId);
        std::string changeType = (dwNewState == DEVICE_STATE_ACTIVE) ? "added" : "removed";
        
        json ev;
        ev.set("ev", "audio_device_change");
        ev.set("change_type", changeType);
        ev.set("device_type", "audio");
        m_pAudioHelper->SendEvent(ev);
        
        // 선택된 마이크 상태 변화 처리
        if (!m_pAudioHelper->selectedMicId.empty() && m_pAudioHelper->selectedMicId == deviceId) {
            if (dwNewState == DEVICE_STATE_NOTPRESENT || dwNewState == DEVICE_STATE_DISABLED) {
                LOG_ERROR("Selected mic removed/disabled; stopping recording");
                m_pAudioHelper->NotifyMicDeviceChanged("selected_removed");
                return S_OK;
            } else if (dwNewState == DEVICE_STATE_ACTIVE) {
                // 선택 마이크가 ACTIVE로 복귀하거나, 같은 물리 장치가 새 엔드포인트 ID로 재등장한 경우
                m_pAudioHelper->OnSelectedMicRestored();
                return S_OK;
            }
        }
    }
    return S_OK;
}

HRESULT STDMETHODCALLTYPE DeviceChangeNotifier::OnDeviceAdded(LPCWSTR pwstrDeviceId) {
    LOG_INFO(std::string("Device added: ") + WStringToString(pwstrDeviceId));
    // UI 통지: 오디오 장치 추가 이벤트 전송 (한글 주석)
    // 문서 명세 3.3: audio_device_change 이벤트
    // 녹음 장치와 재생 장치는 각각 다른 엔드포인트이므로 각각 이벤트 전송
    if (m_pAudioHelper && pwstrDeviceId) {
        json ev;
        ev.set("ev", "audio_device_change");
        ev.set("change_type", "added");
        ev.set("device_type", "audio");
        m_pAudioHelper->SendEvent(ev);
    }
    return S_OK;
}

HRESULT STDMETHODCALLTYPE DeviceChangeNotifier::OnDeviceRemoved(LPCWSTR pwstrDeviceId) {
    LOG_INFO(std::string("Device removed: ") + WStringToString(pwstrDeviceId));
    // UI 통지: 오디오 장치 제거 이벤트 전송 (한글 주석)
    // 문서 명세 3.3: audio_device_change 이벤트
    // 녹음 장치와 재생 장치는 각각 다른 엔드포인트이므로 각각 이벤트 전송
    if (m_pAudioHelper && pwstrDeviceId) {
        std::wstring deviceId(pwstrDeviceId);
        
        json ev;
        ev.set("ev", "audio_device_change");
        ev.set("change_type", "removed");
        ev.set("device_type", "audio");
        m_pAudioHelper->SendEvent(ev);
        
        // 현재 사용 중인 마이크 장치 확인 및 처리
        if (m_pAudioHelper->pMicDevice) {
            LPWSTR curId = nullptr;
            if (SUCCEEDED(m_pAudioHelper->pMicDevice->GetId(&curId)) && curId) {
                std::wstring cur(curId);
                CoTaskMemFree(curId);
                if (cur == deviceId) {
                    m_pAudioHelper->NotifyMicDeviceChanged("removed");
                    m_pAudioHelper->SendMicStateEvent("unavailable");
                    m_pAudioHelper->ScheduleLevelMeterAutoRestart("device_removed");
                }
            }
        }
    }
    return S_OK;
}

HRESULT STDMETHODCALLTYPE DeviceChangeNotifier::OnDefaultDeviceChanged(EDataFlow flow, ERole role, LPCWSTR pwstrDefaultDeviceId) {
    // 시스템 오디오 출력 장치 변경 감지 (eRender)
    if (flow == eRender && role == eConsole && m_pAudioHelper) {
        LOG_INFO(std::string("Default render device changed to: ") + 
                 (pwstrDefaultDeviceId ? WStringToString(pwstrDefaultDeviceId) : "NULL"));
        m_pAudioHelper->NotifySystemDeviceChanged();
    }
    // 기본장치 추종 제거: 마이크 기본 장치 변경은 무시
    return S_OK;
}

HRESULT STDMETHODCALLTYPE DeviceChangeNotifier::OnPropertyValueChanged(LPCWSTR pwstrDeviceId, const PROPERTYKEY key) {
    return S_OK;
}

// SegmentManager 구현
SegmentManager::SegmentManager(AudioHelper* helper) : pAudioHelper(helper) {
    // 기본값: AudioConfig의 기본 3분
    segmentDurationSamples = AudioConfig::SEGMENT_DURATION_SAMPLES;
    segmentBuffer.reserve(segmentDurationSamples);
}

SegmentManager::~SegmentManager() {
    if (currentSegmentSamples > 0) {
        FinalizeCurrentSegment();
    }
}

void SegmentManager::SetOutputDirectory(const std::string& dir) {
    outputDirectory = dir;
}

void SegmentManager::SetEncryptionEnabled(bool enabled) {
    encryptionEnabled = enabled;
}

void SegmentManager::AddSamples(const int16_t* samples, size_t count) {
    // 현재 세그먼트에 샘플 추가
    for (size_t i = 0; i < count; ++i) {
        segmentBuffer.push_back(samples[i]);
        currentSegmentSamples++;
        
        // 세그먼트 완료 체크 (샘플 수 기준)
        if (currentSegmentSamples >= segmentDurationSamples) {
            SaveSegment();
            
            // 다음 세그먼트 준비
            segmentBuffer.clear();
            segmentBuffer.reserve(segmentDurationSamples);
            currentSegmentSamples = 0;
            segmentIndex++;
        }
    }
}

void SegmentManager::FinalizeCurrentSegment() {
    if (currentSegmentSamples > 0) {
        SaveSegment();
        // 보안: 메모리 제로화 후 해제
        std::fill(segmentBuffer.begin(), segmentBuffer.end(), 0);
        segmentBuffer.clear();
        currentSegmentSamples = 0;
    }
}

void SegmentManager::Reset() {
    // 보안: 메모리 제로화 후 해제
    std::fill(segmentBuffer.begin(), segmentBuffer.end(), 0);
    segmentBuffer.clear();
    currentSegmentSamples = 0;
    segmentIndex = 0;
    // 녹음 회차(take) 접미사 초기화: 새 녹음에서 다시 결정
    runSuffix = 0;
    runSuffixLocked = false;
}

void SegmentManager::DiscardCurrentSegment() {
    if (currentSegmentSamples > 0) {
        // 저장하지 않고 폐기
        std::fill(segmentBuffer.begin(), segmentBuffer.end(), 0);
        segmentBuffer.clear();
        currentSegmentSamples = 0;
        // segmentIndex는 증가시키지 않음 (저장하지 않았기 때문)
    }
}

bool SegmentManager::HasPendingSamples() const {
    return currentSegmentSamples > 0;
}

void SegmentManager::SetSegmentDurationSeconds(uint32_t seconds) {
    if (seconds == 0) seconds = 1;
    segmentDurationSamples = static_cast<uint64_t>(seconds) * AudioConfig::SAMPLE_RATE;
    // 새 길이에 맞춰 버퍼 예약 크기 조정(성능 최적화)
    segmentBuffer.reserve(segmentDurationSamples);
}

void SegmentManager::SetFileExtension(const std::string& ext) {
    fileExtension = ext;
    if (!fileExtension.empty() && fileExtension[0] != '.') {
        fileExtension = "." + fileExtension;
    }
}

void SegmentManager::SaveSegment() {
    if (segmentBuffer.empty()) return;
    
    try {
        // 최소 길이 정책: 1초 미만 세그먼트는 저장하지 않음
        const uint64_t kMinSamplesToSave = static_cast<uint64_t>(AudioConfig::SAMPLE_RATE) * 1ULL; // 1s
        if (currentSegmentSamples < kMinSamplesToSave) {
#ifdef _DEBUG_LOG
            LOG_WARN("Segment too short (<1s), skipping save");
#else
            LOG_WARN("Segment too short (<1s), skipping save");
#endif
            return;
        }

        // 디스크 여유 공간 임계치 확인: 50MB 미만이면 경고 및 경계 중지 예약
        if (pAudioHelper) {
            uint64_t freeBytes = 0;
            if (pAudioHelper->QueryFreeBytes(freeBytes)) {
                const uint64_t MB = 1024ULL * 1024ULL;
                if (freeBytes < 50ULL * MB) {
                    pAudioHelper->SendError("DISK_SPACE_CRITICAL", "디스크 여유 공간이 50MB 미만입니다. 다음 세그먼트 경계에서 중지합니다.");
                    pAudioHelper->stopAtBoundary = true;
                }
            }
        }

        std::string basePath = GenerateSegmentPath();
        std::string finalPath;
        
        if (encryptionEnabled) {
            // 암호화 파일: start 명령의 확장자 사용 (이미 GenerateSegmentPath에 포함됨)
            finalPath = basePath;
            EncryptAndSave(segmentBuffer, finalPath);
            // 암호화 실패 시 파일이 생성되지 않았으므로 저장/이벤트를 중단한다.
            if (!std::filesystem::exists(std::filesystem::u8path(finalPath))) {
                if (pAudioHelper) {
                    pAudioHelper->SendError("ENCRYPT_FAILED", "암호화 실패로 세그먼트가 저장되지 않았습니다.");
                }
                return;
            }
        } else {
            // encryption_enabled=false: 강제로 .raw 확장자 사용
            // basePath에서 확장자 제거 후 .raw 추가
            std::filesystem::path p = std::filesystem::u8path(basePath);
            std::string stem = p.stem().u8string();
            std::string dir = p.parent_path().u8string();
            finalPath = dir.empty() ? (stem + ".raw") : (dir + "/" + stem + ".raw");
            
            std::filesystem::path rawPath = std::filesystem::u8path(finalPath);
            std::ofstream file(rawPath, std::ios::binary);
            if (file.is_open()) {
                file.write(reinterpret_cast<const char*>(segmentBuffer.data()),
                          segmentBuffer.size() * sizeof(int16_t));
                file.close();
            } else {
                if (pAudioHelper) {
                    pAudioHelper->SendError("DISK_WRITE_OPEN_FAILED", "세그먼트 파일을 열 수 없습니다(쓰기 실패).");
                }
                return;
            }
        }
        
        // 세그먼트 완료 이벤트 전송
        if (pAudioHelper) {
            json event;
            event.set("ev", "segment_ready");
            event.set("index", segmentIndex);
            event.set("path", finalPath);
            event.set("samples", currentSegmentSamples);
            event.set("duration_ms", (currentSegmentSamples * 1000) / AudioConfig::SAMPLE_RATE);
            event.set("size_bytes", segmentBuffer.size() * sizeof(int16_t));
            event.set("encrypted", encryptionEnabled);
            pAudioHelper->SendEvent(event);
        }
        
        // 릴리즈에서도 파일 저장 로그를 남기기 위해 릴리즈에서는 WARN 레벨 사용
#ifdef _DEBUG_LOG
        LOG_INFO(std::string("Segment saved: ") + finalPath +
                 ", samples=" + std::to_string(currentSegmentSamples) +
                 ", encrypted=" + (encryptionEnabled ? "true" : "false"));
#else
        LOG_WARN(std::string("Segment saved: ") + finalPath +
                 ", samples=" + std::to_string(currentSegmentSamples) +
                 ", encrypted=" + (encryptionEnabled ? "true" : "false"));
#endif
        
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("Failed to save segment: ") + e.what());
        if (pAudioHelper) {
            pAudioHelper->SendError("SEGMENT_SAVE_FAILED", 
                                   std::string("세그먼트 저장 실패: ") + e.what());
        }
    }
}

void SegmentManager::EncryptAndSave(const std::vector<int16_t>& data, const std::string& filePath) {
    const uint8_t* rawData = reinterpret_cast<const uint8_t*>(data.data());
    size_t dataSize = data.size() * sizeof(int16_t);
    
    // AES256-CBC 암호화 (Dart 코드와 동일한 방식)
    BCRYPT_ALG_HANDLE hAlg = nullptr;
    BCRYPT_KEY_HANDLE hKey = nullptr;
    std::vector<uint8_t> encrypted;
    
    try {
        // AES 알고리즘 핸들 열기
        NTSTATUS status = BCryptOpenAlgorithmProvider(&hAlg, BCRYPT_AES_ALGORITHM, nullptr, 0);
        if (!BCRYPT_SUCCESS(status)) {
            throw std::runtime_error("Failed to open AES algorithm provider");
        }
        
        // CBC 모드 설정
        status = BCryptSetProperty(hAlg, BCRYPT_CHAINING_MODE, 
                                  (PUCHAR)BCRYPT_CHAIN_MODE_CBC, 
                                  sizeof(BCRYPT_CHAIN_MODE_CBC), 0);
        if (!BCRYPT_SUCCESS(status)) {
            throw std::runtime_error("Failed to set CBC mode");
        }
        
        // Dart 코드와 동일한 키/IV 사용 (UTF-8 문자열)
        // Dart: Key.fromUtf8('b7671acf046542c4848d6162ee9733cc')
        // Dart: IV.fromUtf8('baf766f829f8489a')
        const unsigned char key[32] = {
            'b','7','6','7','1','a','c','f','0','4','6','5','4','2','c','4',
            '8','4','8','d','6','1','6','2','e','e','9','7','3','3','c','c'
        };
        
        const unsigned char iv[16] = {
            'b','a','f','7','6','6','f','8','2','9','f','8','4','8','9','a'
        };
        
        // 키 객체 생성
        status = BCryptGenerateSymmetricKey(hAlg, &hKey, nullptr, 0, 
                                           const_cast<PUCHAR>(key), sizeof(key), 0);
        if (!BCRYPT_SUCCESS(status)) {
            throw std::runtime_error("Failed to generate symmetric key");
        }
        
        // 암호화 수행 (CBC 모드)
        DWORD encryptedSize = 0;
        
        // 먼저 암호화 크기 계산
        status = BCryptEncrypt(hKey, (PUCHAR)rawData, (ULONG)dataSize, nullptr,
                              const_cast<PUCHAR>(iv), sizeof(iv),
                              nullptr, 0, &encryptedSize, BCRYPT_BLOCK_PADDING);
        if (!BCRYPT_SUCCESS(status)) {
            throw std::runtime_error("Failed to get encrypted size");
        }
        
        encrypted.resize(encryptedSize);
        
        // 실제 암호화 수행
        status = BCryptEncrypt(hKey, (PUCHAR)rawData, (ULONG)dataSize, nullptr,
                              const_cast<PUCHAR>(iv), sizeof(iv),
                              encrypted.data(), encryptedSize, &encryptedSize, BCRYPT_BLOCK_PADDING);
        if (!BCRYPT_SUCCESS(status)) {
            throw std::runtime_error("Failed to encrypt data");
        }
        
        // 파일에 저장: 암호화된 데이터만 (키/IV는 코드에 하드코딩)
        std::filesystem::path encPath = std::filesystem::u8path(filePath);
        std::ofstream file(encPath, std::ios::binary);
        if (file.is_open()) {
            file.write(reinterpret_cast<const char*>(encrypted.data()), encryptedSize);
            file.close();
        }
        
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("AES256 encryption failed, plaintext not written: ") + e.what());
        // 보안상 평문 저장 금지: 파일 미생성
        return;
    }
    
    // 리소스 정리
    if (hKey) BCryptDestroyKey(hKey);
    if (hAlg) BCryptCloseAlgorithmProvider(hAlg, 0);
}

void SegmentManager::EnsureRunSuffix() {
    if (runSuffixLocked) return;
    std::string sessionIdStr = pAudioHelper ? pAudioHelper->sessionId : "unknown";
    if (sessionIdStr.empty()) sessionIdStr = "unknown";
    std::filesystem::path baseDir = outputDirectory.empty() ? "recordings" : std::filesystem::u8path(outputDirectory);
    std::filesystem::path sessionDir = baseDir / sessionIdStr;
    try { std::filesystem::create_directories(sessionDir); } catch (...) {}
    std::unordered_set<uint32_t> used;
    try {
        for (const auto& entry : std::filesystem::directory_iterator(sessionDir)) {
            if (!entry.is_regular_file()) continue;
            const std::string stem = entry.path().stem().u8string();
            if (stem.rfind(sessionIdStr, 0) != 0) continue; // 접두 불일치
            size_t pos = sessionIdStr.size();
            uint32_t sfx = 0;
            if (pos < stem.size() && stem[pos] == '(') {
                size_t end = stem.find(')', pos + 1);
                if (end != std::string::npos) {
                    std::string num = stem.substr(pos + 1, end - (pos + 1));
                    try { sfx = static_cast<uint32_t>(std::stoul(num)); } catch (...) { sfx = 0; }
                    pos = end + 1;
                }
            }
            if (pos < stem.size() && stem[pos] == '_') {
                used.insert(sfx);
            }
        }
    } catch (...) {}
    uint32_t s = 0;
    while (used.count(s)) ++s;
    runSuffix = s;
    runSuffixLocked = true;
}

std::string SegmentManager::GenerateSegmentPath() {
    // 세션 ID가 있으면 사용, 없으면 기본값
    std::string sessionIdStr = pAudioHelper ? pAudioHelper->sessionId : "unknown";
    if (sessionIdStr.empty()) {
        sessionIdStr = "unknown";
    }
    
    // outputDirectory/recordings/{sessionId}/ 폴더 구조 생성
    std::filesystem::path baseDir = outputDirectory.empty() ? "recordings" : std::filesystem::u8path(outputDirectory);
    std::filesystem::path sessionDir = baseDir / sessionIdStr;
    
    // 세션 폴더 생성
    try {
        std::filesystem::create_directories(sessionDir);
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("Failed to create directory: ") + e.what());
        return (baseDir / (sessionIdStr + "_" + std::to_string((unsigned long long)segmentIndex) + fileExtension)).u8string();
    }

    // 이번 run의 접미사 확정(최초 1회)
    EnsureRunSuffix();
    const std::string take = (runSuffix == 0) ? "" : ("(" + std::to_string(runSuffix) + ")");

    // 파일명: {sessionId}{(runSuffix)}_{index}.{ext}
    char filename[256];
    std::snprintf(filename, sizeof(filename), 
                  "%s%s_%llu%s",
                  sessionIdStr.c_str(), take.c_str(),
                  static_cast<unsigned long long>(segmentIndex),
                  fileExtension.c_str());
    
    // UTF-8 경로 문자열 반환 (UI 표시용), 파일 접근은 u8path로 처리
    return (sessionDir / filename).u8string();
}

// 정적 상수 정의
const double AudioConfig::GAIN_MIC = 1.0;
const double AudioConfig::GAIN_SYS = 0.7;
const double AudioConfig::SILENCE_THRESHOLD = 0.02;
const double AudioConfig::SILENCE_THRESHOLD_SYS = 0.003; // ~ -50 dBFS

// 전역 함수 구현
std::string WStringToString(const std::wstring& wstr) {
    if (wstr.empty()) return std::string();
    int size_needed = WideCharToMultiByte(CP_UTF8, 0, &wstr[0], (int)wstr.size(), NULL, 0, NULL, NULL);
    std::string strTo(size_needed, 0);
    WideCharToMultiByte(CP_UTF8, 0, &wstr[0], (int)wstr.size(), &strTo[0], size_needed, NULL, NULL);
    return strTo;
}

std::wstring StringToWString(const std::string& str) {
    if (str.empty()) return std::wstring();
    int size_needed = MultiByteToWideChar(CP_UTF8, 0, &str[0], (int)str.size(), NULL, 0);
    std::wstring wstrTo(size_needed, 0);
    MultiByteToWideChar(CP_UTF8, 0, &str[0], (int)str.size(), &wstrTo[0], size_needed);
    return wstrTo;
}

// Base64 인코더 (간단 구현)
static std::string Base64Encode(const uint8_t* data, size_t len) {
    static const char tbl[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    out.reserve(((len + 2) / 3) * 4);
    size_t i = 0;
    while (i + 3 <= len) {
        uint32_t v = (data[i] << 16) | (data[i+1] << 8) | data[i+2];
        out.push_back(tbl[(v >> 18) & 0x3F]);
        out.push_back(tbl[(v >> 12) & 0x3F]);
        out.push_back(tbl[(v >> 6) & 0x3F]);
        out.push_back(tbl[v & 0x3F]);
        i += 3;
    }
    if (i + 1 == len) {
        uint32_t v = (data[i] << 16);
        out.push_back(tbl[(v >> 18) & 0x3F]);
        out.push_back(tbl[(v >> 12) & 0x3F]);
        out.push_back('=');
        out.push_back('=');
    } else if (i + 2 == len) {
        uint32_t v = (data[i] << 16) | (data[i+1] << 8);
        out.push_back(tbl[(v >> 18) & 0x3F]);
        out.push_back(tbl[(v >> 12) & 0x3F]);
        out.push_back(tbl[(v >> 6) & 0x3F]);
        out.push_back('=');
    }
    return out;
}

// UTF-16LE wstring을 Base64(원시 바이트)로 변환
static std::string WStringToBase64Utf16Le(const std::wstring& w) {
    if (w.empty()) return std::string();
    const uint8_t* bytes = reinterpret_cast<const uint8_t*>(w.data());
    size_t byteLen = w.size() * sizeof(wchar_t);
    return Base64Encode(bytes, byteLen);
}

// JSON 안전 문자열로 변환(UTF-16 → ASCII with \uXXXX), 멀티바이트 경계 문제 방지
static std::string WStringToJsonEscaped(const std::wstring& wstr) {
    auto hex4 = [](wchar_t ch) {
        const char* digits = "0123456789abcdef";
        std::string out(4, '0');
        out[0] = digits[(ch >> 12) & 0xF];
        out[1] = digits[(ch >> 8) & 0xF];
        out[2] = digits[(ch >> 4) & 0xF];
        out[3] = digits[(ch) & 0xF];
        return out;
    };
    std::string res;
    res.reserve(wstr.size() * 6);
    for (wchar_t ch : wstr) {
        switch (ch) {
            case L'"': res += "\\\""; break;
            case L'\\': res += "\\\\"; break;
            case L'\b': res += "\\b"; break;
            case L'\f': res += "\\f"; break;
            case L'\n': res += "\\n"; break;
            case L'\r': res += "\\r"; break;
            case L'\t': res += "\\t"; break;
            default:
                if (ch >= 0x20 && ch <= 0x7E) {
                    res.push_back(static_cast<char>(ch));
                } else {
                    res += "\\u";
                    res += hex4(ch);
                }
                break;
        }
    }
    return res;
}

std::vector<AudioDevice> EnumerateAudioDevices() {
    std::vector<AudioDevice> devices;

    IMMDeviceEnumerator* pEnumerator = nullptr;
    HRESULT hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), NULL, CLSCTX_ALL,
                         __uuidof(IMMDeviceEnumerator), (void**)&pEnumerator);
    
    if (FAILED(hr)) {
        std::cerr << "CoCreateInstance failed: " << std::hex << hr << std::endl;
        return devices;
    }
    
    if (SUCCEEDED(hr)) {
        IMMDeviceCollection* pCollection = nullptr;
        hr = pEnumerator->EnumAudioEndpoints(eCapture, DEVICE_STATE_ACTIVE, &pCollection);
        
        if (FAILED(hr)) {
            std::cerr << "EnumAudioEndpoints failed: " << std::hex << hr << std::endl;
        } else {
            UINT count;
            hr = pCollection->GetCount(&count);
            // std::cerr << "Found " << count << " audio capture devices" << std::endl;
            
            for (UINT i = 0; i < count && SUCCEEDED(hr); i++) {
                IMMDevice* pDevice = nullptr;
                hr = pCollection->Item(i, &pDevice);
                
                if (SUCCEEDED(hr)) {
                    AudioDevice device;
                    
                    // 디바이스 ID 가져오기
                    LPWSTR pwszID = nullptr;
                    hr = pDevice->GetId(&pwszID);
                    if (SUCCEEDED(hr)) {
                        device.id = pwszID;
                        CoTaskMemFree(pwszID);
                    }
                    
                    // 디바이스 이름 가져오기
                    IPropertyStore* pProps = nullptr;
                    hr = pDevice->OpenPropertyStore(STGM_READ, &pProps);
                    if (SUCCEEDED(hr)) {
                        PROPVARIANT varName;
                        PropVariantInit(&varName);
                        hr = pProps->GetValue(PKEY_Device_FriendlyName, &varName);
                        if (SUCCEEDED(hr)) {
                            device.name = varName.pwszVal;
                        }
                        PropVariantClear(&varName);
                        pProps->Release();
                    }
                    
                    devices.push_back(device);
                    pDevice->Release();
                }
            }
            pCollection->Release();
        }
        pEnumerator->Release();
    }
    
    return devices;
}

// AudioHelper 구현
AudioHelper::AudioHelper() : sysAudioBuffer(AudioConfig::RINGBUF_MAX_MS * AudioConfig::SAMPLE_RATE / 1000),
                           waveformBuffer(200, 0.0f) {
    // 세그먼트 관리자 초기화
    segmentManager = std::make_unique<SegmentManager>(this);
    
    // 가이드 문서의 AudioProcessor 초기화
    audioProcessor = std::make_unique<AudioProcessor>();
    
    // AEC 초기화: 기본은 WebRTC가 가능하면 WebRTC, 아니면 NLMS
#ifdef WEBRTC_APM_AVAILABLE
    aecBackend = std::make_unique<WebRtcAecBackend>(AudioConfig::SAMPLE_RATE, AudioConfig::CHANNELS, this);
    aecBackendType = AecBackendType::WEBRTC;
#else
    aecBackend = std::make_unique<NlmsAecBackend>(aecFilterLength, aecMu);
    aecBackendType = AecBackendType::NLMS;
#endif
    aecFixedDelaySamples = (aecFixedDelayMs * AudioConfig::SAMPLE_RATE) / 1000;
    aecRefDelayLine.clear();
    aecDelayWindowSamples = (aecDelayWindowMs * AudioConfig::SAMPLE_RATE) / 1000;
    aecMaxLagSamples = (aecMaxLagMs * AudioConfig::SAMPLE_RATE) / 1000;
    aecMicHPHist.clear();
    aecSysHPHist.clear();
    aecLastDelayUpdate = std::chrono::steady_clock::now();
}

AudioHelper::~AudioHelper() {
    Cleanup();
}

// AudioProcessor 구현 (가이드 문서 기반)
bool AudioProcessor::Initialize(int sample_rate, int channels) {
#ifdef WEBRTC_APM_AVAILABLE
    try {
        // 기존 인스턴스가 있으면 정리
        Cleanup();
        
        sample_rate_ = sample_rate;
        channels_ = channels;
        stream_config_ = StreamConfig(sample_rate, channels);
        
        // AudioProcessing 인스턴스 생성
        #if defined(HAVE_WEBRTC_MODULES_AP)
        auto apm_ref = webrtc::AudioProcessingBuilder().Create();
        if (!apm_ref) {
            LOG_ERROR("Failed to create WebRTC AudioProcessing instance");
            return false;
        }
        
        // AEC 및 기타 모듈 설정 (음성 품질 최적화)
        webrtc::AudioProcessing::Config config;
        
        // 에코 제거 설정 - 음성 품질 우선
        config.echo_canceller.enabled = true;
        config.echo_canceller.mobile_mode = false;
        // 하위 호환: 일부 WebRTC 빌드에서는 delay_agnostic/extended_filter가 없음
        // enforce_high_pass_filtering는 사용 가능 범위 내에서 유지
        config.echo_canceller.enforce_high_pass_filtering = true;

        // 노이즈 억제 비활성화 (더블톡 시 마이크 음성 최대한 보호)
        config.noise_suppression.enabled = false;
        // config.noise_suppression.level = webrtc::AudioProcessing::Config::NoiseSuppression::kLow;
        
        // AGC2 활성화(레벨 안정화) - GC1은 비활성 유지
        config.gain_controller1.enabled = false;
        config.gain_controller2.enabled = true;
        
        // HPF 활성화: DC/저주파 드리프트 제거로 AEC 수렴 보조
        config.high_pass_filter.enabled = true;
        
        apm_ref->ApplyConfig(config);
        
        // 참조 카운트 증가 후 포인터 저장
        apm_ref->AddRef();
        apm_ptr = apm_ref.get();
        
        initialized_ = true;
        LOG_INFO("AudioProcessor initialized successfully");
        return true;
        #else
        LOG_WARN("WebRTC modules not available, AudioProcessor initialization failed");
        return false;
        #endif
        
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("AudioProcessor initialization failed: ") + e.what());
        return false;
    }
#else
    LOG_WARN("WEBRTC_APM_AVAILABLE not defined, AudioProcessor initialization skipped");
    return false;
#endif
}

void AudioProcessor::Cleanup() {
#ifdef WEBRTC_APM_AVAILABLE
    if (apm_ptr) {
        auto* apm = reinterpret_cast<webrtc::AudioProcessing*>(apm_ptr);
        apm->Release();
        apm_ptr = nullptr;
    }
#endif
    initialized_ = false;
}

int AudioProcessor::ProcessReverseStream(float* audio_data, int samples_per_channel) {
#ifdef WEBRTC_APM_AVAILABLE
    if (!initialized_ || !apm_ptr) {
        return -1;
    }
    
    try {
        auto* apm = reinterpret_cast<webrtc::AudioProcessing*>(apm_ptr);
        
        const float* const_ptr[] = { audio_data };
        float* output_ptr[] = { audio_data };
        
        webrtc::StreamConfig cfg(stream_config_.sample_rate, stream_config_.channels);
        
        return apm->ProcessReverseStream(const_ptr, cfg, cfg, output_ptr);
        
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("ProcessReverseStream failed: ") + e.what());
        return -1;
    }
#else
    return 0; // No-op if WebRTC not available
#endif
}

int AudioProcessor::ProcessStream(float* audio_data, int samples_per_channel) {
#ifdef WEBRTC_APM_AVAILABLE
    if (!initialized_ || !apm_ptr) {
        return -1;
    }
    
    try {
        auto* apm = reinterpret_cast<webrtc::AudioProcessing*>(apm_ptr);
        
        const float* const_ptr[] = { audio_data };
        float* output_ptr[] = { audio_data };
        
        webrtc::StreamConfig cfg(stream_config_.sample_rate, stream_config_.channels);
        
        return apm->ProcessStream(const_ptr, cfg, cfg, output_ptr);
        
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("ProcessStream failed: ") + e.what());
        return -1;
    }
#else
    return 0; // No-op if WebRTC not available
#endif
}

void AudioProcessor::GetStatistics() {
#ifdef WEBRTC_APM_AVAILABLE
    if (!initialized_ || !apm_ptr) {
        return;
    }
    
    try {
        auto* apm = reinterpret_cast<webrtc::AudioProcessing*>(apm_ptr);
        auto stats = apm->GetStatistics();
        
        if (stats.echo_return_loss) {
            LOG_INFO(std::string("Echo Return Loss: ") + std::to_string(*stats.echo_return_loss) + " dB");
        }
        if (stats.echo_return_loss_enhancement) {
            LOG_INFO(std::string("Echo Return Loss Enhancement: ") + std::to_string(*stats.echo_return_loss_enhancement) + " dB");
        }
        
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("GetStatistics failed: ") + e.what());
    }
#endif
}

// WebRTC AEC 백엔드: 링크 오류 방지를 위한 최소 구현
// 실제 WebRTC 처리는 향후 WEBRTC_APM_AVAILABLE가 활성화된 경우에 교체한다.
void WebRtcAecBackend::Reset() {
#ifdef WEBRTC_APM_AVAILABLE
    if (!state) {
        state = std::make_unique<WebRtcState>();
        state->parent = nullptr; // 생성자에서 설정된 값 유지
        state->current_delay_ms = 60;  // 초기 지연값
        state->target_delay_ms = 60;   // 목표 지연값
        state->frame_count = 0;        // 프레임 카운터 초기화
    }
    auto existing = reinterpret_cast<webrtc::AudioProcessing*>(state->apm);
    if (existing) {
        existing->Release();
        state->apm = nullptr;
    }

    // APM 생성 시도: 빌더가 있으면 우선 사용, 없으면 포인터 null 유지(폴백)
#if defined(WEBRTC_APM_AVAILABLE)
    webrtc::AudioProcessing::Config cfg;
    cfg.echo_canceller.enabled = true;
    cfg.high_pass_filter.enabled = true;
    cfg.noise_suppression.enabled = false;
    cfg.gain_controller1.enabled = false;
    cfg.gain_controller2.enabled = false;

  #if defined(HAVE_WEBRTC_MODULES_AP)
    // modules/audio_processing의 Builder 사용
    {
        auto apm_ref = webrtc::AudioProcessingBuilder().Create();
        if (apm_ref) {
            apm_ref->ApplyConfig(cfg);
            apm_ref->Initialize();
            apm_ref->AddRef();
            state->apm = apm_ref.get();
        } else {
            state->apm = nullptr;
        }
    }
  #else
    state->apm = nullptr;
  #endif
#else
    state->apm = nullptr;
#endif
#endif
}

void WebRtcAecBackend::ProcessFrame(const float* farIn,
                                    const float* nearIn,
                                    float* out,
                                    size_t count,
                                    bool /*adapt*/) {
#ifdef WEBRTC_APM_AVAILABLE
    webrtc::AudioProcessing* apm = state ? reinterpret_cast<webrtc::AudioProcessing*>(state->apm) : nullptr;
    if (apm) {
        const int channels = 1;
        webrtc::StreamConfig cfg_in(static_cast<int>(sampleRate), channels);
        webrtc::StreamConfig cfg_out(static_cast<int>(sampleRate), channels);

        // 지연(delay) 설정 - 적응형 지연 추정
        state->frame_count++;
        
        // 100 프레임(1초)마다 지연값 조정 검토
        if (state->frame_count % 100 == 0) {
            // 간단한 에너지 기반 지연 추정 (farIn과 nearIn의 상관관계 활용)
            if (farIn && nearIn && count >= 160) {
                double correlation = 0.0;
                double far_energy = 0.0, near_energy = 0.0;
                
                for (size_t i = 0; i < 160; ++i) {
                    correlation += farIn[i] * nearIn[i];
                    far_energy += farIn[i] * farIn[i];
                    near_energy += nearIn[i] * nearIn[i];
                }
                
                if (far_energy > 0.001 && near_energy > 0.001) {
                    double normalized_corr = correlation / sqrt(far_energy * near_energy);
                    
                    // 상관관계 기반 지연 조정 (음성 품질 고려)
                    if (normalized_corr > 0.2) {  // 0.3 → 0.2로 완화
                        state->target_delay_ms = std::max(40, state->current_delay_ms - 3);  // 더 보수적 조정
                    } else if (normalized_corr < 0.05) {  // 0.1 → 0.05로 완화
                        state->target_delay_ms = std::min(100, state->current_delay_ms + 5);  // 더 보수적 조정
                    }
                }
            }
        }
        
        // 지연값을 점진적으로 조정 (급격한 변화 방지)
        if (state->current_delay_ms != state->target_delay_ms) {
            int diff = state->target_delay_ms - state->current_delay_ms;
            state->current_delay_ms += (diff > 0) ? std::min(diff, 2) : std::max(diff, -2);
        }
        
        apm->set_stream_delay_ms(state->current_delay_ms);
        
        // 지연값 변화 로깅 (디버깅용)
        if (state->frame_count % 1000 == 0) {
            LOG_INFO(std::string("WebRTC AEC delay: ") + std::to_string(state->current_delay_ms) + "ms");
        }

        // Far-end(스피커) 신호를 항상 reverse 경로로 처리 (무음이라도 연속성 유지)
        std::vector<float> silence_buffer;
        const float* reverse_input = farIn;
        if (!farIn) {
            // farIn이 없으면 무음으로 대체하여 연속성 유지
            silence_buffer.resize(count, 0.0f);
            reverse_input = silence_buffer.data();
        }
        
        std::vector<float> reverse_out(count, 0.0f);
        const float* far_channels[1] = { reverse_input };
        float* rev_out_channels[1] = { reverse_out.data() };
        int reverse_err = apm->ProcessReverseStream(far_channels, cfg_in, cfg_out, rev_out_channels);
        
        if (reverse_err != 0) {
            LOG_WARN(std::string("ProcessReverseStream failed: ") + std::to_string(reverse_err));
        }

        // Near-end(마이크) 신호 처리
        std::vector<float> near_silence;
        const float* near_input = nearIn;
        if (!nearIn) {
            near_silence.resize(count, 0.0f);
            near_input = near_silence.data();
        }
        
        const float* near_channels[1] = { near_input };
        float* out_channels[1] = { out };
        int stream_err = apm->ProcessStream(near_channels, cfg_in, cfg_out, out_channels);
        
        if (stream_err == 0) {
            return; // 성공
        } else {
            LOG_WARN(std::string("ProcessStream failed: ") + std::to_string(stream_err));
        }
        // 실패 시 안전 경로로 폴백
    } else {
        LOG_DEBUG("WebRTC APM not available - using passthrough");
    }
#endif
    // 폴백: 입력을 그대로 출력으로 복사
    if (out) {
        if (nearIn) {
            std::memcpy(out, nearIn, count * sizeof(float));
        } else {
            std::memset(out, 0, count * sizeof(float));
        }
    }
}

bool AudioHelper::Initialize() {
    HRESULT hr = InitializeCOM();
    if (FAILED(hr)) {
        LOG_ERROR("COM init failed");
        SendError("COM_INIT_FAILED", "COM 초기화에 실패했습니다.");
        return false;
    }
    
    hr = InitializeDeviceEnumerator();
    if (FAILED(hr)) {
        LOG_ERROR("Device enumerator init failed");
        SendError("ENUMERATOR_FAILED", "디바이스 열거자 초기화에 실패했습니다.");
        return false;
    }
    
    // 장치 변경 알림 등록
    RegisterDeviceNotifications();
    
    // 타이머 분해능 향상(지터 감소)
    timeBeginPeriod(1);
    LOG_INFO("AudioHelper initialized");
    return true;
}

// AudioProcessor 초기화 (가이드 문서 기반)
bool AudioHelper::InitializeAudioProcessing(int sample_rate, int channels) {
    if (!audioProcessor) {
        LOG_ERROR("AudioProcessor not created");
        return false;
    }
    
    bool success = audioProcessor->Initialize(sample_rate, channels);
    if (success) {
        LOG_INFO(std::string("AudioProcessor initialized with sample_rate=") + 
                 std::to_string(sample_rate) + ", channels=" + std::to_string(channels));
    } else {
        LOG_WARN("AudioProcessor initialization failed, will use fallback processing");
    }
    
    return success;
}

HRESULT AudioHelper::InitializeCOM() {
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (hr == RPC_E_CHANGED_MODE) {
        hr = S_OK; // 이미 다른 모드로 초기화됨
    }
    return hr;
}

HRESULT AudioHelper::InitializeDeviceEnumerator() {
    return CoCreateInstance(__uuidof(MMDeviceEnumerator), NULL, CLSCTX_ALL,
                           __uuidof(IMMDeviceEnumerator), (void**)&pEnumerator);
}

HRESULT AudioHelper::GetDefaultDevice(EDataFlow dataFlow, IMMDevice** ppDevice) {
    if (!pEnumerator) return E_FAIL;
    return pEnumerator->GetDefaultAudioEndpoint(dataFlow, eConsole, ppDevice);
}

HRESULT AudioHelper::GetDeviceById(const std::wstring& id, IMMDevice** ppDevice) {
    if (!pEnumerator) return E_FAIL;
    return pEnumerator->GetDevice(id.c_str(), ppDevice);
}

HRESULT AudioHelper::InitializeAudioClient(IMMDevice* pDevice, IAudioClient** ppClient,
                                         IAudioCaptureClient** ppCaptureClient, bool isLoopback) {
    if (!pDevice) return E_POINTER; // 널 방어
    HRESULT hr = pDevice->Activate(__uuidof(IAudioClient), CLSCTX_ALL, NULL, (void**)ppClient);
    if (FAILED(hr)) return hr;
    
    // 디바이스의 믹스 포맷 가져오기
    WAVEFORMATEX* pWfx = nullptr;
    hr = (*ppClient)->GetMixFormat(&pWfx);
    if (FAILED(hr)) {
        // GetMixFormat 실패 시에도 pWfx가 할당되었을 수 있음
        if (pWfx) {
            CoTaskMemFree(pWfx);
        }
        return hr;
    }
    
    // Shared 모드로 초기화: 기본 버퍼 크기 사용(0) → 초기 지연 최소화
    DWORD flags = isLoopback ? AUDCLNT_STREAMFLAGS_LOOPBACK : 0;
    hr = (*ppClient)->Initialize(AUDCLNT_SHAREMODE_SHARED, flags,
                                0 /* hnsBufferDuration */, 0, pWfx, NULL);
    
    if (SUCCEEDED(hr)) {
        hr = (*ppClient)->GetService(__uuidof(IAudioCaptureClient), (void**)ppCaptureClient);
    }
    
    // 모든 경로에서 pWfx 해제 (성공/실패 무관)
    CoTaskMemFree(pWfx);
    return hr;
}

void AudioHelper::ProcessCommand(const json& command) {
    try {
        std::string cmd = command["cmd"];
        
        // 세션 ID 저장 (모든 명령에서 사용 가능)
        if (command.contains("sessionId")) {
            sessionId = command["sessionId"];
        }
        
        if (cmd == "version" || cmd == "get_version") {
            HandleGetVersion();
        } else if (cmd == "list_devices") {
            HandleListDevices();
        } else if (cmd == "set_output_dir") {
            HandleSetOutputDir(command);
        } else if (cmd == "set_debug_files") {
            HandleSetDebugFiles(command);
        } else if (cmd == "set_segment_config") {
            HandleSetSegmentConfig(command);
        } else if (cmd == "start_test") {
            HandleStartTest(command);
        } else if (cmd == "stop_test") {
            HandleStopTest();
        } else if (cmd == "start") {
            HandleStart(command);
        } else if (cmd == "pause") {
            HandlePause();
        } else if (cmd == "resume") {
            HandleResume();
        } else if (cmd == "stop") {
            HandleStop();
        } else if (cmd == "mark") {
            // 메모는 UI에서만 처리 (Helper에서 처리하지 않음)
            SendError("NOT_IMPLEMENTED", "메모 기능은 UI에서만 처리됩니다.");
        } else if (cmd == "set_mute") {
            HandleSetMute(command);
        } else if (cmd == "set_level_meter") {
            HandleSetLevelMeter(command);
        } else {
            SendError("UNKNOWN_COMMAND", "알 수 없는 명령: " + cmd);
        }
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("Command error: ") + e.what());
        SendError("COMMAND_ERROR", std::string("명령 처리 중 오류: ") + e.what());
    }
}

std::string EscapeJsonString(const std::string& str) {
    std::string escaped;
    for (char c : str) {
        switch (c) {
            case '"': escaped += "\\\""; break;
            case '\\': escaped += "\\\\"; break;
            case '\b': escaped += "\\b"; break;
            case '\f': escaped += "\\f"; break;
            case '\n': escaped += "\\n"; break;
            case '\r': escaped += "\\r"; break;
            case '\t': escaped += "\\t"; break;
            default: escaped += c; break;
        }
    }
    return escaped;
}

void AudioHelper::HandleListDevices() {
    auto devices = EnumerateAudioDevices(); // 캡쳐 장치 목록
    // 렌더(재생) 장치 목록도 수집
    std::vector<AudioDevice> renderDevices;
    {
        IMMDeviceEnumerator* pEnum = nullptr;
        if (SUCCEEDED(CoCreateInstance(__uuidof(MMDeviceEnumerator), NULL, CLSCTX_ALL,
                                       __uuidof(IMMDeviceEnumerator), (void**)&pEnum))) {
            IMMDeviceCollection* pCol = nullptr;
            if (SUCCEEDED(pEnum->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &pCol))) {
                UINT cnt = 0;
                if (SUCCEEDED(pCol->GetCount(&cnt))) {
                    for (UINT i = 0; i < cnt; ++i) {
                        IMMDevice* pDev = nullptr;
                        if (SUCCEEDED(pCol->Item(i, &pDev))) {
                            AudioDevice d;
                            // ID
                            LPWSTR pid = nullptr;
                            if (SUCCEEDED(pDev->GetId(&pid))) { d.id = pid; CoTaskMemFree(pid); }
                            // 이름
                            IPropertyStore* pProps = nullptr;
                            if (SUCCEEDED(pDev->OpenPropertyStore(STGM_READ, &pProps))) {
                                PROPVARIANT v; PropVariantInit(&v);
                                if (SUCCEEDED(pProps->GetValue(PKEY_Device_FriendlyName, &v))) {
                                    d.name = v.pwszVal;
                                }
                                PropVariantClear(&v);
                                pProps->Release();
                            }
                            renderDevices.push_back(d);
                            pDev->Release();
                        }
                    }
                }
                pCol->Release();
            }
            pEnum->Release();
        }
    }
    // 기본 장치 ID 조회 (캡쳐/렌더)
    std::wstring defaultCaptureIdW, defaultRenderIdW;
    {
        IMMDeviceEnumerator* pEnum = nullptr;
        if (SUCCEEDED(CoCreateInstance(__uuidof(MMDeviceEnumerator), NULL, CLSCTX_ALL,
                                       __uuidof(IMMDeviceEnumerator), (void**)&pEnum))) {
            IMMDevice* pDef = nullptr;
            if (SUCCEEDED(pEnum->GetDefaultAudioEndpoint(eCapture, eConsole, &pDef)) && pDef) {
                LPWSTR pid = nullptr; if (SUCCEEDED(pDef->GetId(&pid))) { defaultCaptureIdW = pid; CoTaskMemFree(pid);} pDef->Release();
            }
            pDef = nullptr;
            if (SUCCEEDED(pEnum->GetDefaultAudioEndpoint(eRender, eConsole, &pDef)) && pDef) {
                LPWSTR pid = nullptr; if (SUCCEEDED(pDef->GetId(&pid))) { defaultRenderIdW = pid; CoTaskMemFree(pid);} pDef->Release();
            }
            pEnum->Release();
        }
    }
    
    // SimpleJson을 사용해서 올바른 JSON 구조 생성
    json event;
    event.set("ev", "devices");
    
    // 배열을 JSON 문자열로 직접 구성 (이스케이프 처리된)
    std::ostringstream deviceArrayStr;
    deviceArrayStr << "[";
    
    for (size_t i = 0; i < devices.size(); ++i) {
        if (i > 0) deviceArrayStr << ",";
        std::string name_b64 = WStringToBase64Utf16Le(devices[i].name);
        bool isDef = (!defaultCaptureIdW.empty() && devices[i].id == defaultCaptureIdW);
        deviceArrayStr << "{"
            << "\"id\":\"" << EscapeJsonString(WStringToString(devices[i].id)) << "\"," 
            << "\"name\":\"" << WStringToJsonEscaped(devices[i].name) << "\"," 
            << "\"name_b64_utf16le\":\"" << name_b64 << "\"," 
            << "\"isDefault\":" << (isDef ? "true" : "false")
            << "}";
    }
    deviceArrayStr << "]";
    // 렌더 배열 구성
    std::ostringstream renderArrayStr; renderArrayStr << "[";
    for (size_t i = 0; i < renderDevices.size(); ++i) {
        if (i > 0) renderArrayStr << ",";
        std::string name_b64 = WStringToBase64Utf16Le(renderDevices[i].name);
        bool isDef = (!defaultRenderIdW.empty() && renderDevices[i].id == defaultRenderIdW);
        renderArrayStr << "{"
            << "\"id\":\"" << EscapeJsonString(WStringToString(renderDevices[i].id)) << "\"," 
            << "\"name\":\"" << WStringToJsonEscaped(renderDevices[i].name) << "\"," 
            << "\"name_b64_utf16le\":\"" << name_b64 << "\"," 
            << "\"isDefault\":" << (isDef ? "true" : "false")
            << "}";
    }
    renderArrayStr << "]";
    
    // 전체 이벤트 JSON을 직접 구성 (기존 devices는 캡쳐, renderDevices 추가)
    std::cout << "{\"ev\":\"devices\",\"devices\":" << deviceArrayStr.str()
              << ",\"renderDevices\":" << renderArrayStr.str() << "}" << std::endl;
}

void AudioHelper::HandleStartTest(const json& params) {
    // 테스트도 성공 후에만 재개 차단 해제
    try {
        // 테스트 모드 활성화
        isTestMode = true;
        isRecording = false;
        stopDueToMaxDuration = false; // 시작 시 초기화
        
        // 무음 감지 상태 초기화 (새 세션마다 재활성화)
        silenceDetectionDisabled = false; // 무음 감지 비활성화 해제
        silenceDetected = false;          // 현재 무음 상태 리셋
        sustainedEventSent = false;       // 30초 지속 이벤트 전송 플래그 리셋
        silenceStartMs = 0;               // 무음 시작 시간 리셋
        
        // 테스트 시작 시 시간 관련 변수 초기화
        totalSamples = 0;
        micPushed16kTotal = 0;
        stopAtBoundary = false;
        
        // 모드 설정(요청값을 우선 로컬에 보관하여 재사용/재초기화 판단에 사용)
        std::string modeStr = params["mode"];
        CaptureMode desiredMode = currentMode;
        if (modeStr == "MicOnly") {
            desiredMode = CaptureMode::MicOnly;
        } else if (modeStr == "MicPlusSystem") {
            desiredMode = CaptureMode::MicPlusSystem;
        } else if (modeStr == "SystemOnly") {
            desiredMode = CaptureMode::SystemOnly;
        }

        // 호출 출처 판정
        const bool fromRecording = params.contains("_from_recording");
        const bool fromAuto      = params.contains("_auto");
        const bool fromUser      = !fromRecording && !fromAuto; // UI 직접 호출로 간주

        // 세션용 요청 파싱
        std::wstring requestedMicId; std::wstring requestedRenderId;
        if (params.contains("mic")) {
            std::string mic = params["mic"];
            if (!mic.empty() && mic != "default") {
                requestedMicId = StringToWString(mic);
            }
        }
        if (params.contains("render")) {
            std::string rd = params["render"]; if (rd != "default") requestedRenderId = StringToWString(rd);
        }
        
        // 세션 마이크 ID 결정 및 선택 상태 반영
        if (!requestedMicId.empty()) {
            sessionMicId = requestedMicId;
            // ★ UI에서 직접 누른 테스트 시작일 때만 선택 상태로도 반영
            if (fromUser) {
                selectedMicId = requestedMicId;
                LOG_INFO("Persist selected mic from user test start");
            }
        } else {
            sessionMicId = selectedMicId;
        }

        // 3) 필수: 세션 마이크가 있어야 테스트/레벨미터 시작
        if (sessionMicId.empty()) {
            SendMicStateEvent("unavailable");
            SendError("NO_SELECTED_MIC", "선택된 마이크가 없어 테스트를 시작할 수 없습니다.");
            LOG_ERROR("Abort test start: no selected/session mic");
            return;
        }
        // 다른 마이크로 자동 전환 금지: 선택/세션 마이크가 ACTIVE가 아니면 시작하지 않음
        if (!IsMicDeviceActive(sessionMicId)) {
            SendMicStateEvent("unavailable");
            SendError("NO_MIC_DEVICE", "선택된 마이크가 감지되지 않거나 사용 불가 상태입니다.");
            LOG_ERROR("Abort test start: selected/session mic not ACTIVE");
            return;
        }

        // 이미 캡쳐 중이며 녹음은 아닌 경우, 장치와 모드가 동일할 때만 재사용
        if (isRunning && !isRecording) {
            bool sameMic = IsSameDeviceId(currentMicDeviceId, sessionMicId);
            bool sameRender = IsSameDeviceId(currentSysDeviceId, requestedRenderId);
            bool sameMode = (currentMode == desiredMode);
            if (sameMic && sameRender && sameMode) {
                isPaused = false;
                json ev; ev.set("ev", "test_started"); ev.set("mode", modeStr); ev.set("reuse", true);
                SendEvent(ev);
                LOG_INFO("Test started (reuse running capture)");
                return;
            }
            // 재사용 불가: 기존 캡쳐 완전 종료 후 요청 장치로 재초기화
            HandleReinitAudio(params);
            return;
        }

        // 여기 도달 시 새로 시작하는 경로이므로 모드를 반영
        currentMode = desiredMode;
        
        // 4) 세션 마이크로만 열기
        GetDeviceById(sessionMicId, &pMicDevice);
        if (!pMicDevice) {
            SendError("NO_MIC_DEVICE", "선택된 마이크 장치를 찾을 수 없습니다.");
            LOG_ERROR("Selected/session mic device not found");
            return;
        }

        // 5) 현재 실제 사용 중 디바이스 ID 로깅
        {
            LPWSTR pwszID = nullptr;
            if (SUCCEEDED(pMicDevice->GetId(&pwszID)) && pwszID) {
                currentMicDeviceId = pwszID;
                CoTaskMemFree(pwszID);
                LOG_INFO(std::string("Current mic device ID: ") + WStringToString(currentMicDeviceId));
            }
        }

        
        // 시스템 오디오 디바이스 설정 (필요한 경우)
        if (currentMode != CaptureMode::MicOnly) {
            if (params.contains("render")) {
                std::string rd = params["render"];
                if (rd == "default") {
                    GetDefaultDevice(eRender, &pSysDevice);
                } else {
                    std::wstring rid = StringToWString(rd);
                    GetDeviceById(rid, &pSysDevice);
                }
            } else {
                GetDefaultDevice(eRender, &pSysDevice);
            }
            
            // 현재 시스템 디바이스 ID 저장
            if (pSysDevice) {
                LPWSTR pwszID = nullptr;
                HRESULT hrId = pSysDevice->GetId(&pwszID);
                if (SUCCEEDED(hrId)) {
                    currentSysDeviceId = pwszID;
                    CoTaskMemFree(pwszID);
                    LOG_INFO(std::string("Current system device ID: ") + WStringToString(currentSysDeviceId));
                }
            }
        }
        
        // 오디오 클라이언트 초기화
        HRESULT hr = InitializeAudioClient(pMicDevice, &pMicClient, &pMicCaptureClient);
        if (FAILED(hr)) {
            LOG_ERROR("Mic init failed");
            if (!stoppingDueToMicRemoval.load() && !stopErrorSent.load()) {
                SendError("MIC_INIT_FAILED", "마이크 초기화 실패");
            } else {
                LOG_WARN("MIC_INIT_FAILED suppressed (stopping due to mic removal)");
            }
            return;
        }
        
        if (pSysDevice) {
            hr = InitializeAudioClient(pSysDevice, &pSysClient, &pSysCaptureClient, true);
            if (FAILED(hr)) {
                LOG_WARN("System init failed, proceeding with mic only");
                SendError("SYS_INIT_FAILED", "시스템 오디오 초기화 실패");
                // 부분 초기화 실패 시 마이크 자원 즉시 정리
                if (pMicClient) { pMicClient->Stop(); pMicClient->Release(); pMicClient = nullptr; }
                if (pMicCaptureClient) { pMicCaptureClient->Release(); pMicCaptureClient = nullptr; }
                if (pMicDevice) { pMicDevice->Release(); pMicDevice = nullptr; }
                return;
            }
        }
        
        // AudioProcessor 초기화 (가이드 문서 기반)
        InitializeAudioProcessing(AudioConfig::SAMPLE_RATE, AudioConfig::CHANNELS);
        
        // 녹음/테스트 모드 시작 (이미 설정된 isTestMode 값 유지)
        isRunning = true;
        
        // 세션 시작 시각을 먼저 고정
        startTimeMs = GetCurrentTimeMs();

        // 오디오 클라이언트 시작
        pMicClient->Start();
        if (pSysClient) {
            pSysClient->Start();
        }
        
        // 캡처 스레드 시작
        micThread = std::thread(&AudioHelper::MicrophoneCaptureThread, this);
        if (currentMode != CaptureMode::MicOnly) {
            sysThread = std::thread(&AudioHelper::SystemCaptureThread, this);
        }
        mixThread = std::thread(&AudioHelper::MixingThread, this);

        // 최대 녹음 시간 설정
        maxDurationMs = 0;
        if (params.contains("max_ms")) {
            std::string msStr = params["max_ms"];
            try { maxDurationMs = static_cast<uint64_t>(std::stoull(msStr)); } catch (...) {}
        }
        StartWatchdogIfNeeded();
        
        json event;
        event.set("ev", "test_started");
        event.set("mode", modeStr);
        SendEvent(event);
        
        // 테스트 시작 로그 (눈에 잘 띄도록)
        if (isTestMode) {
            LOG_INFO("========================================");
            LOG_INFO("            TEST STARTED");
            LOG_INFO("========================================");
            LOG_INFO(std::string("Mode: ") + modeStr);
            LOG_INFO(std::string("Session ID: ") + (sessionId.empty() ? "No-Session" : sessionId));
            LOG_INFO("Test mode initialized successfully");
            LOG_INFO("========================================");
        }
        // 테스트 캡쳐 시작이 정상적으로 완료되었으므로 차단 해제
        resumeBlockedDueToMic.store(false);
        
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("Start test failed: ") + e.what());
        SendError("START_TEST_ERROR", std::string("테스트 시작 실패: ") + e.what());
    }
}

void AudioHelper::HandleStopTest() {
    if (isRunning) {
        // 1) 더 이상 세그먼트에 쓰지 못하게 즉시 차단 (레이스 방지)
        isRecording.store(false, std::memory_order_release);
        
        // 2) 메모리 장벽으로 플래그 전환 순서 보장
        std::atomic_thread_fence(std::memory_order_seq_cst);
        
        // 3) 드레인을 허용하되, 이제부터는 파일 기록이 불가
        isPaused = false;
        drainOnStop.store(true, std::memory_order_release);
        isRunning = false;
        bool wasTestMode = isTestMode;
        isTestMode = false;
        
        // 테스트 정지 시에만 시간 관련 변수 초기화 (녹음 정지에는 영향 없음)
        if (wasTestMode) {
            totalSamples = 0;
            micPushed16kTotal = 0;
        }
        
        // 테스트 중 누적된 세그먼트 데이터 폐기 (저장하지 않음) - 테스트 모드일 때만
        if (wasTestMode && segmentManager) {
            segmentManager->DiscardCurrentSegment();
            LOG_INFO("Discarded test mode segment data");
        }
        
        // 스레드 종료 대기
        if (micThread.joinable()) micThread.join();
        if (sysThread.joinable()) sysThread.join();
        // 믹스 스레드가 남은 60ms까지 drain할 수 있도록 신호 후 join
        if (mixThread.joinable()) mixThread.join();
        if (watchdogThread.joinable()) {
            // 워치독 스레드에서 호출된 경우 자기 자신을 join하면 데드락 발생 → 회피
            if (std::this_thread::get_id() != watchdogThread.get_id()) {
                watchdogThread.join();
            }
        }
        
        // 오디오 클라이언트 중지
        if (pMicClient) pMicClient->Stop();
        if (pSysClient) pSysClient->Stop();
        // 디버그 WAV 닫기 (mix 포함)
        FinalizeDebugLengths();
        maxDurationMs = 0;
        
        // 테스트 모드였을 때만 이벤트/로그를 전송
        if (wasTestMode) {
            json event;
            event.set("ev", "test_stopped");
            SendEvent(event);

#ifdef _DEBUG_LOG
            LOG_INFO("========================================");
            LOG_INFO("              TEST STOPPED");
            LOG_INFO("========================================");
#else
            LOG_WARN("========================================");
            LOG_WARN("              TEST STOPPED");
            LOG_WARN("========================================");
#endif
            LOG_INFO(std::string("Total samples processed: ") + std::to_string(totalSamples));
            LOG_INFO(std::string("Session ID: ") + (sessionId.empty() ? "No-Session" : sessionId));
            LOG_INFO("========================================");
        }
        
        // 테스트 중지 후 레벨미터 자동 재시작: 디바운스 스케줄링이 없을 때만 즉시 재시작
        if (levelMeterEnabled.load() && !isRecording && !isRunning) {
            if (!autoRestartScheduled.load()) {
                StartLevelMeterCaptureIfNeeded();
            } else {
                LOG_INFO("Skip immediate level-meter restart (auto-restart scheduled)");
            }
        }
    }
}

void AudioHelper::HandleStart(const json& params) {
    // 장치 문제로 블록된 세션이라도, 선택 마이크가 이미 ACTIVE면 차단 자동 해제 후 진행
    if (resumeBlockedDueToMic.load()) {
        if (IsSelectedMicActive()) {
            resumeBlockedDueToMic.store(false);
            stoppingDueToMicRemoval.store(false);
            stopErrorSent.store(false);
            LOG_INFO("Resume block cleared at start: selected mic is ACTIVE");
        } else {
            SendError("CANNOT_RESUME_NO_MIC", "마이크가 복구되지 않아 녹음을 시작할 수 없습니다.");
            LOG_ERROR("Abort start: resume blocked due to mic issue");
            return;
        }
    }
    // 해제는 성공 후로 미룸
    // 사전 디스크 용량 체크: 50MB 미만이면 시작 거부
    try {
        uint64_t freeBytes = 0;
        if (QueryFreeBytes(freeBytes)) {
            if (freeBytes < DISK_STATUS_LOW) {
                SendError("DISK_SPACE_CRITICAL", "디스크 여유 공간이 50MB 미만이어서 녹음을 시작할 수 없습니다.");
#ifdef _DEBUG_LOG
                LOG_WARN("Disk space critical at start; recording not started");
#else
                LOG_WARN("Disk space critical at start; recording not started");
#endif
                return;
            }
        }
    } catch (...) {
        LOG_WARN("Disk space pre-check failed in HandleStart");
    }

    // 마이크 장치가 없으면 녹음 시작 금지
    if (!HasSelectedMic()) {
        SendMicStateEvent("unavailable");
        SendError("NO_SELECTED_MIC", "선택된 마이크가 없어 녹음을 시작할 수 없습니다.");
        LOG_ERROR("Abort start: no selected mic");
        return;
    }
    // 녹음 모드에서 마이크 필요 여부 계산
    std::string modeStrCheck = params.contains("mode") ? std::string(params["mode"]) : "MicPlusSystem";
    bool needMicForRecording = (modeStrCheck == "MicOnly" || modeStrCheck == "MicPlusSystem");
    if (needMicForRecording) {
        const std::wstring devId = !sessionMicId.empty() ? sessionMicId : selectedMicId;
        if (devId.empty() || !IsMicDeviceActive(devId)) {
            SendMicStateEvent("unavailable");
            SendError("NO_MIC_DEVICE", "선택된 마이크가 감지되지 않거나 사용 불가 상태입니다.");
            LOG_ERROR("Abort start: selected/session mic not ACTIVE");
            return;
        }
    }
    // 자동 대체 금지: 위 needMicForRecording 검사로 충분하며, 다른 마이크로의 폴백은 허용하지 않음
    // (아래에서 실제 시작 성공 후에 녹음 플래그/상태/배너를 켭니다)
    
    // 이미 테스트 모드에서 실행 중이면 스레드 재시작 없이 전환
    // 실행 중이 아니면 캡쳐/믹스 스레드 시작을 위해 테스트 초기화 루틴 재사용
    if (!isRunning) {
        json p = params;
        p.set("_from_recording", true);   // 내부 호출 표식
        HandleStartTest(p);
        // 테스트 초기화 실패(마이크 없음/초기화 실패 등) 시 녹음 전환 금지
        if (!isRunning || !HasActiveCaptureDevice()) {
            if (!stoppingDueToMicRemoval.load() && !stopErrorSent.load()) {
                SendError("MIC_INIT_FAILED", "마이크 초기화 실패로 녹음을 시작할 수 없습니다.");
            } else {
                LOG_WARN("MIC_INIT_FAILED suppressed (stopping due to mic removal)");
                // UI 펜딩 해제를 위해 보조 에러 1회 보냄
                SendError("CANNOT_RESUME_NO_MIC", "마이크가 복구되지 않아 녹음을 시작할 수 없습니다.");
            }
            LOG_ERROR("Abort start: start_test did not bring up mic/client");
            return;
        }
    } else {
        // 실행 중인데 요청 모드/마이크 ID가 현재 바인딩과 다르면 재초기화 강제(B 정책)
        if (params.contains("mode")) {
            std::string modeStr = params["mode"];
            CaptureMode desiredMode = currentMode;
            if (modeStr == "MicOnly") desiredMode = CaptureMode::MicOnly;
            else if (modeStr == "MicPlusSystem") desiredMode = CaptureMode::MicPlusSystem;
            else if (modeStr == "SystemOnly") desiredMode = CaptureMode::SystemOnly;
            bool needReinit = (desiredMode != currentMode);
            // 마이크 ID 불일치 또는 레벨미터 기원 세션이면 재초기화
            if (!sessionMicId.empty() && !IsSameDeviceId(currentMicDeviceId, sessionMicId)) {
                needReinit = true;
                LOG_INFO("Reinit required: session mic differs from current mic device");
            }
            if (startedByLevelMeter.load() && !isRecording) {
                needReinit = true;
                LOG_INFO("Reinit required: session started by level meter");
            }
            if (needReinit) {
                HandleReinitAudio(params);
                if (!isRunning || !HasActiveCaptureDevice()) {
                    if (!stoppingDueToMicRemoval.load() && !stopErrorSent.load()) {
                        SendError("MIC_INIT_FAILED", "모드 변경 재초기화 실패로 녹음을 시작할 수 없습니다.");
                    } else {
                        LOG_WARN("MIC_INIT_FAILED suppressed (stopping due to mic removal)");
                    }
                    LOG_ERROR("Abort start: reinit for mode change failed");
                    return;
                }
                startedByLevelMeter.store(false);
            }
        }
    }

    // 성공적으로 시작되었으므로 재개 차단 해제
    resumeBlockedDueToMic.store(false);

    // 성공 보장 구간: 배너 및 시작 로그 출력
#ifdef _DEBUG_LOG
    LOG_INFO("========================================");
    LOG_INFO("           RECORDING STARTED");
    LOG_INFO("========================================");
#else
    LOG_WARN("========================================");
    LOG_WARN("           RECORDING STARTED");
    LOG_WARN("========================================");
#endif
    try {
        LOG_INFO(std::string("HandleStart params: ") + params.dump());
    } catch (...) {
        LOG_WARN("Failed to dump HandleStart params");
    }
    {
        std::string modeStrLog = params.contains("mode") ? std::string(params["mode"]) : "Unknown";
        std::string sessionStr = sessionId.empty() ? "No-Session" : sessionId;
        LOG_INFO(std::string("Mode: ") + modeStrLog);
        LOG_INFO(std::string("Session ID: ") + sessionStr);
        LOG_INFO(std::string("Start Time: ") + std::to_string(GetCurrentTimeMs()));
    }

    // 여기서부터 '녹음'으로 전환 (성공 보장 구간)
    isTestMode = false;
    isRecording = true;
    stopAtBoundary = false;
    stopDueToMaxDuration = false; // 시작 시 초기화

    // 무음 감지 상태 초기화 (녹음 시작 시 보장)
    silenceDetectionDisabled = false;
    silenceDetected = false;
    sustainedEventSent = false;
    silenceStartMs = 0;

    // 세그먼트 인덱스 초기화
    if (segmentManager) {
        segmentManager->Reset();
    }

    // 음소거 상태 초기화
    muteMic = false;
    muteSystem = false;
    
    startTimeMs = GetCurrentTimeMs();
    // 녹음 모드 전환을 위한 변수 초기화
    totalSamples = 0;
    micPushed16kTotal = 0;
    
    // 파일 확장자 설정 (start 명령에서 file_extension 파라미터 수신)
    if (params.contains("file_extension") && segmentManager) {
        std::string ext = std::string(params["file_extension"]);
        segmentManager->SetFileExtension(ext);
        LOG_INFO(std::string("File extension set to: ") + ext);
    }
    
    // 방어적: max_ms 재파싱 및 워치독 재시도 (문자열 파싱 + 원본 라인 보정)
    try {
        uint64_t parsed = 0;
        if (params.contains("max_ms")) {
            try {
                std::string msStr = params["max_ms"];
                parsed = static_cast<uint64_t>(std::stoull(msStr));
            } catch (...) { parsed = 0; }
        }
        if (parsed == 0) {
            // 원본 라인에서 직접 추출
            extern std::string g_lastCommandLine; // 선언부가 없으므로 간단 보정은 포기
        }
        if (parsed > 0) {
            maxDurationMs = parsed;
        }
        if (maxDurationMs == 0) {
            LOG_INFO("Watchdog skipped: max_ms==0 (no timeout)");
        } else if (!watchdogThread.joinable()) {
            StartWatchdogIfNeeded();
        } else {
            LOG_INFO("Watchdog skipped: already running");
        }
    } catch (...) {
        LOG_WARN("Failed to (re)parse max_ms in HandleStart");
    }
    
    // 실제 녹음 전환이 확정된 시점에만 이벤트 발행
    {
        json event;
        event.set("ev", "recording_started");
        SendEvent(event);
    }
    
    LOG_INFO("Recording initialization completed");
    LOG_INFO("========================================");
}

void AudioHelper::HandlePause() {
    if (isRunning && !isPaused) {
        isPaused = true;
        
        // 녹음 경계를 딱 맞추기 위해 큐와 상태를 즉시 비움
        { 
            std::lock_guard<std::mutex> lk(micFifoMutex); 
            micFifo16k.clear(); 
        }
        { 
            std::lock_guard<std::mutex> lk(sysFifoMutex); 
            sysFifo16k.clear(); 
        }
        micResamplePhase = 0.0; 
        micResampleLast = 0.0f; 
        micResampleInRate = 0;
        sysResamplePhase = 0.0; 
        sysResampleLast = 0.0f; 
        sysResampleInRate = 0;
        
        json event;
        event.set("ev", "paused");
        SendEvent(event);
#ifdef _DEBUG_LOG
        LOG_INFO("Recording paused (FIFO and resampler state cleared)");
#else
        LOG_WARN("Recording paused (FIFO and resampler state cleared)");
#endif
        // 주의(한글): 일시정지 상태에서도 levelMeterEnabled가 true이면 캡쳐 스레드는 레벨 측정을 위해 동작을 계속함
    } else {
        LOG_WARN("Cannot pause - not running or already paused");
    }
}

void AudioHelper::HandleResume() {
    // 장치 문제로 중단된 세션은 재개 금지
    if (resumeBlockedDueToMic.load()) {
        SendError("CANNOT_RESUME_NO_MIC", "일시정지 중 마이크가 제거/오류로 재개할 수 없습니다.");
        LOG_ERROR("Resume blocked due to mic issue");
        return;
    }
    // 실제 캡처 가능 여부 확인
    if (pMicClient == nullptr || pMicDevice == nullptr) {
        SendError("CANNOT_RESUME_NO_MIC", "마이크 캡처가 유효하지 않아 재개할 수 없습니다.");
        LOG_ERROR("Resume blocked: mic client/device is null");
        return;
    }
    if (isRunning && isPaused) {
        isPaused = false;
        json event;
        event.set("ev", "resumed");
        SendEvent(event);
#ifdef _DEBUG_LOG
        LOG_INFO("Recording resumed");
#else
        LOG_WARN("Recording resumed");
#endif
    } else {
        LOG_WARN("Cannot resume - not running or not paused");
    }
}

void AudioHelper::HandleStop() {
    // 녹음 중지 로그 (눈에 잘 띄도록)
    LOG_INFO("========================================");
    LOG_INFO("           RECORDING STOPPED");
    LOG_INFO("========================================");
    
    // 드레인 전 일시정지 해제 후 테스트 정지 공통 경로 수행
    isPaused = false; // 드레인이 pause에 막히지 않도록 해제
    HandleStopTest(); // 동일한 로직 (시간 변수 초기화 포함)
    // 주의: isRecording은 이미 HandleStopTest()에서 false로 설정됨
    
    // 마지막 세그먼트 처리: max_ms 초과로 중지된 경우 저장하지 않고 폐기
    if (segmentManager) {
        if (stopDueToMaxDuration) {
            LOG_INFO("Discarding last partial segment due to max_ms reached");
            segmentManager->DiscardCurrentSegment();
        } else {
            LOG_INFO("Finalizing current segment on stop");
            segmentManager->FinalizeCurrentSegment();
        }
    } else {
        LOG_ERROR("Segment manager is null on stop");
    }
    
    json event;
    event.set("ev", "recording_stopped");
    event.set("totalSamples", totalSamples);
    event.set("micSamplesWritten", micSamplesWritten);
    event.set("sysSamplesWritten", sysSamplesWritten);
    SendEvent(event);
    
    // 녹음 완료 통계
    uint64_t recordingDurationMs = GetCurrentTimeMs() - startTimeMs;
    double recordingDurationSec = recordingDurationMs / 1000.0;
    
    if (totalSamples == 0) {
        LOG_INFO("Recording stopped due to device or user stop (no samples)");
    } else {
        LOG_INFO(std::string("Recording completed successfully"));
    }
    LOG_INFO(std::string("Session ID: ") + (sessionId.empty() ? "No-Session" : sessionId));
    LOG_INFO(std::string("Duration: ") + std::to_string(recordingDurationSec) + " seconds");
    LOG_INFO(std::string("Total samples: ") + std::to_string(totalSamples));
    LOG_INFO(std::string("Mic samples: ") + std::to_string(micSamplesWritten));
    LOG_INFO(std::string("System samples: ") + std::to_string(sysSamplesWritten));
    LOG_INFO("========================================");

    // 즉시 재시작은 HandleStopTest() 한 곳에서만 수행 (중복 방지)
    
    // 세션 종료 시 세션 변수만 초기화 (selectedMicId는 보존)
    sessionMicId.clear();

    // 중복 억제 플래그 리셋
    micStopScheduled.store(false);
    stoppingDueToMicRemoval.store(false);
    stopErrorSent.store(false);
}

// 선택 마이크가 ACTIVE로 복구되었을 때 내부 상태를 정리한다.
void AudioHelper::OnSelectedMicRestored() {
    try {
        // 기존 selectedMicId가 ACTIVE면 단순 해제
        if (IsSelectedMicActive()) {
            resumeBlockedDueToMic.store(false);
            stoppingDueToMicRemoval.store(false);
            stopErrorSent.store(false);
            LOG_INFO("Selected mic restored to ACTIVE; resume block cleared");
            if (levelMeterEnabled.load() && !isRunning) {
                StartLevelMeterCaptureIfNeeded();
            }
            SendMicStateEvent("available");
            return;
        }
        // 자동 리바운드 금지: 선택 마이크가 ACTIVE가 아니면 상태만 통지
        SendMicStateEvent("unavailable");
        LOG_WARN("Selected mic not ACTIVE on restore; auto-rebind forbidden by policy");
    } catch (...) {
        LOG_ERROR("Exception in OnSelectedMicRestored");
    }
}

// HandleMark 함수는 제거됨 - 메모는 UI에서만 처리

void AudioHelper::MicrophoneCaptureThread() {
    // COM 초기화 (스레드별 필요)
    HRESULT hrCom = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hrCom) && hrCom != RPC_E_CHANGED_MODE) {
        LOG_ERROR("Failed to initialize COM in microphone thread");
        return;
    }
    
    // 스레드 우선순위 설정
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL);

    // MixFormat 1회 캐시(마이크)
    uint32_t micRateCached = 0;
    uint16_t micChCached = 1;
    {
        WAVEFORMATEX* pFmt = nullptr;
        if (pMicClient && SUCCEEDED(pMicClient->GetMixFormat(&pFmt)) && pFmt) {
            micRateCached = pFmt->nSamplesPerSec;
            micChCached = pFmt->nChannels;
            CoTaskMemFree(pFmt);
        }
        if (micRateCached == 0) {
            // 안전 폴백: shared-mode의 일반적인 값 가정
            micRateCached = 48000;
            micChCached = 2;
        }
    }
    
    while (isRunning) {
        if (isPaused && !levelMeterEnabled.load()) {
            Sleep(10);
            continue;
        }
        
        // 모든 대기 패킷을 한 번에 소진 (드롭 방지)
        UINT32 packetLength = 0;
        HRESULT hr = S_OK;
        while (isRunning && (!isPaused || levelMeterEnabled.load())) {
            hr = pMicCaptureClient->GetNextPacketSize(&packetLength);
            if (FAILED(hr) || packetLength == 0) break;
            do {
                BYTE* pData = nullptr;
                UINT32 numFrames = 0;
                DWORD flags = 0;
                hr = pMicCaptureClient->GetBuffer(&pData, &numFrames, &flags, NULL, NULL);
                if (SUCCEEDED(hr)) {
                    // MixFormat 캐시 사용
                    WAVEFORMATEX stackFormat{};
                    stackFormat.nSamplesPerSec = micRateCached;
                    stackFormat.nChannels = micChCached;
                    // (과다 로그 제거)
                    if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
                        // 무음 플래그: 0 샘플 주입 + 믹서 FIFO에도 반영
                        std::vector<int16_t> zerosI16(numFrames, 0);
                        micLevelMeter.addSamples(zerosI16.data(), zerosI16.size());
                        SaveMicDebugIfEnabled(zerosI16.data(), zerosI16.size(), micRateCached);
                        // Pause 중에는(녹음 중 + 일시정지) 레벨미터만 유지, 녹음 FIFO에는 넣지 않음
                        if (!(isRecording && isPaused)) {
                            // 0.0f 모노 버퍼를 16k로 상태형 리샘플 후 FIFO에 푸시
                            std::vector<float> zerosF(numFrames, 0.0f);
                            std::vector<float> zeros16k;
                            ResampleLinearMonoStateful(zerosF.data(), zerosF.size(), micRateCached, AudioConfig::SAMPLE_RATE,
                                                       zeros16k, micResamplePhase, micResampleLast, micResampleInRate);
                            if (!zeros16k.empty()) {
                                PushToFifo(micFifo16k, micFifoMutex, zeros16k.data(), zeros16k.size());
                                micPushed16kTotal += zeros16k.size();
                            }
                        }
                    } else {
                        ProcessMicrophoneData(pData, numFrames, &stackFormat);
                    }
                    pMicCaptureClient->ReleaseBuffer(numFrames);
                } else {
                    break;
                }
                hr = pMicCaptureClient->GetNextPacketSize(&packetLength);
            } while (SUCCEEDED(hr) && packetLength > 0);
        }
        Sleep(1);
    }
    
    // COM 해제
    if (SUCCEEDED(hrCom) || hrCom == RPC_E_CHANGED_MODE) {
        CoUninitialize();
    }
}

void AudioHelper::SystemCaptureThread() {
    // COM 초기화 (스레드별 필요)
    HRESULT hrCom = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hrCom) && hrCom != RPC_E_CHANGED_MODE) {
        LOG_ERROR("Failed to initialize COM in system thread");
        return;
    }
    
    // 스레드 우선순위 설정
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL);

    // MixFormat 1회 캐시(시스템)
    uint32_t sysRateCached = 0;
    uint16_t sysChCached = 2;
    {
        WAVEFORMATEX* pFmt = nullptr;
        if (pSysClient && SUCCEEDED(pSysClient->GetMixFormat(&pFmt)) && pFmt) {
            sysRateCached = pFmt->nSamplesPerSec;
            sysChCached = pFmt->nChannels;
            CoTaskMemFree(pFmt);
        }
        if (sysRateCached == 0) {
            // 안전 폴백
            sysRateCached = 48000;
            sysChCached = 2;
        }
    }
    
    while (isRunning) {
        if (isPaused && !levelMeterEnabled.load()) {
            Sleep(10);
            continue;
        }
        
        // 장치 변경 요청 확인 및 처리
        if (deviceChangeRequested) {
            // 변경 구간 동안 일시정지하여 믹서가 이전 참조로 계속 처리하지 않도록 함
            LOG_INFO("Pausing processing for system device switch");
            isPaused = true;
            OnSystemDeviceChanged();
            // ★ 새 pSysClient로 MixFormat 재조회하여 로컬 캐시 갱신
            if (pSysClient) {
                WAVEFORMATEX* pFmt = nullptr;
                HRESULT fmtHr = pSysClient->GetMixFormat(&pFmt);
                if (SUCCEEDED(fmtHr) && pFmt) {
                    sysRateCached = pFmt->nSamplesPerSec;
                    sysChCached   = pFmt->nChannels;
                    CoTaskMemFree(pFmt);
                    LOG_INFO(std::string("Updated system MixFormat cache after switch: rate=") + std::to_string(sysRateCached) +
                             ", ch=" + std::to_string(sysChCached));
                } else {
                    LOG_WARN("Failed to requery system MixFormat after device switch");
                }
            }
            // 프라임 대기: Reverse(시스템) 프레임이 충분히 쌓일 때까지 기다림(100ms)
            {
                const size_t prime = (AudioConfig::SAMPLE_RATE * 100) / 1000; // 100ms @16k
                for (int i = 0; i < 200; ++i) { // 최대 ~2초 대기
                    if (FifoSize(sysFifo16k, sysFifoMutex) >= prime) break;
                    Sleep(10);
                }
            }
            isPaused = false;
            LOG_INFO("Resumed processing after system device switch");
            // 장치 재연결 후 잠시 대기
            Sleep(50);
            continue;
        }
        
        // pSysClient가 null인 경우 (재연결 실패 등) 대기
        if (!pSysClient || !pSysCaptureClient) {
            Sleep(10);
            continue;
        }
        
        // 모든 대기 패킷을 한 번에 소진 (드롭 방지)
        UINT32 packetLength = 0;
        HRESULT hr = S_OK;
        while (isRunning && (!isPaused || levelMeterEnabled.load()) && pSysCaptureClient) {
            hr = pSysCaptureClient->GetNextPacketSize(&packetLength);
            if (FAILED(hr) || packetLength == 0) break;
            do {
                BYTE* pData = nullptr;
                UINT32 numFrames = 0;
                DWORD flags = 0;
                hr = pSysCaptureClient->GetBuffer(&pData, &numFrames, &flags, NULL, NULL);
                if (SUCCEEDED(hr)) {
                    // MixFormat 캐시 사용
                    WAVEFORMATEX stackFormat{};
                    stackFormat.nSamplesPerSec = sysRateCached;
                    stackFormat.nChannels = sysChCached;
                    // (과다 로그 제거)
                    if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
                        std::vector<int16_t> zerosI16(numFrames, 0);
                        sysLevelMeter.addSamples(zerosI16.data(), zerosI16.size());
                        SaveSystemDebugIfEnabled(zerosI16.data(), zerosI16.size(), sysRateCached);
                        // Pause 중에는(녹음 중 + 일시정지) 레벨미터만 유지, 녹음 FIFO에는 넣지 않음
                        if (!(isRecording && isPaused)) {
                            std::vector<float> zerosF(numFrames, 0.0f);
                            std::vector<float> zeros16k;
                            ResampleLinearMonoStateful(zerosF.data(), zerosF.size(), sysRateCached, AudioConfig::SAMPLE_RATE,
                                                       zeros16k, sysResamplePhase, sysResampleLast, sysResampleInRate);
                            if (!zeros16k.empty()) {
                                PushToFifo(sysFifo16k, sysFifoMutex, zeros16k.data(), zeros16k.size());
                            }
                        }
                    } else {
                        ProcessSystemData(pData, numFrames, &stackFormat);
                    }
                    pSysCaptureClient->ReleaseBuffer(numFrames);
                } else {
                    break;
                }
                hr = pSysCaptureClient->GetNextPacketSize(&packetLength);
            } while (SUCCEEDED(hr) && packetLength > 0);
        }
        Sleep(1);
    }
    
    // COM 해제
    if (SUCCEEDED(hrCom) || hrCom == RPC_E_CHANGED_MODE) {
        CoUninitialize();
    }
}

void AudioHelper::MixingThread() {
    const size_t blockSamples = AudioConfig::SAMPLE_RATE * AudioConfig::BLOCK_MS / 1000;
    outputBuffer.resize(blockSamples);
    
    auto lastProgressTime = std::chrono::steady_clock::now();
    // 사용자 규칙: 마이크 기준 60ms 버퍼링
    const size_t primeSamples = (AudioConfig::SAMPLE_RATE * 60) / 1000; // 60ms
    mixSamplesWritten = 0;
    mixStartTimeMs = 0;
    
    while (isRunning || drainOnStop) {
        if (isPaused && !drainOnStop) {
            Sleep(AudioConfig::BLOCK_MS);
            continue;
        }
        
        // 블록 단위로 처리
        auto blockStart = std::chrono::steady_clock::now();
        
        bool hasEnoughData = (FifoSize(micFifo16k, micFifoMutex) >= primeSamples);
        
        // 프라이밍: 드레인 중에는 우회
        if (!drainOnStop && !hasEnoughData) {
            // 데이터 부족해도 무음 감지는 수행 (0 샘플로)
            std::vector<int16_t> silentBlock(blockSamples, 0);
            DetectSilence(silentBlock.data(), blockSamples);
            Sleep(2);
            continue;
        }

        // 실제 오디오 처리는 여기서 수행: 마이크 기준 60ms 지연, 20ms 블록을 준비될 때마다 연속 방출
        MixWhileReady(false);
        
        // 레벨 및 웨이브폼 업데이트
        UpdateLevels(outputBuffer.data(), blockSamples);
        UpdateWaveform(outputBuffer.data(), blockSamples);
        DetectSilence(outputBuffer.data(), blockSamples);

        // 디버그 저장: 원본만 기록. 패딩/보정 금지
        
        // 주기적으로 진행상황 전송 (녹음 중에만)
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::milliseconds>(now - lastProgressTime).count() >= 200) {
            if (isRecording) {
                SendProgressEvent();
            }
            SendWaveformEvent();
            lastProgressTime = now;
        }

        // 디스크 상태 이벤트(1초 주기)
        CheckAndEmitDiskStatusIfDue();
        
        // stop 신호가 오면 남은 60ms까지 모두 방출
        if (drainOnStop) {
            MixWhileReady(true);
            drainOnStop = false; // 드레인 완료
            continue;
        }

        // 블록 타이밍 유지
        auto blockEnd = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(blockEnd - blockStart);
        auto elapsedMs = elapsed.count();
        if (elapsedMs < AudioConfig::BLOCK_MS) {
            Sleep(static_cast<DWORD>(AudioConfig::BLOCK_MS - elapsedMs));
        }
    }

    // 루프 종료: 드레인까지 끝난 시점. 경계 중지 예약이 있었다면 비동기로 안전 정지 호출
    if (!isRunning && !drainOnStop && boundaryStopScheduled) {
        std::thread([this]() {
            HandleStop();
            boundaryStopScheduled = false;
        }).detach();
    }
}

void AudioHelper::MixWhileReady(bool flushAll) {
    const size_t blockSamples = AudioConfig::SAMPLE_RATE * AudioConfig::BLOCK_MS / 1000;
    for (;;) {
        size_t micAvail = FifoSize(micFifo16k, micFifoMutex);
        if (!flushAll) {
            // 60ms 지연을 유지: micAvail이 60ms + 1블록 이상일 때만 방출
            const size_t delaySamples = (AudioConfig::SAMPLE_RATE * 60) / 1000;
            if (micAvail < delaySamples + blockSamples) break;
        } else {
            if (micAvail < blockSamples) {
                // flush 모드에서는 남은 잔여도 모두 방출
                if (micAvail > 0) {
                    MixBlockAndWrite(micAvail);
                }
                break;
            }
        }
        MixBlockAndWrite(blockSamples);
    }
}

// PadSystemDebugIfLagging 제거: 디버그 파일에는 원본만 저장

void AudioHelper::ProcessMicrophoneData(const BYTE* pData, UINT32 numFrames, WAVEFORMATEX* pFormat) {
    // float 포맷을 int16으로 변환하고 모노로 변환
    const float* floatData = reinterpret_cast<const float*>(pData);
    std::vector<float> mono;
    mono.resize(numFrames);
    
    for (UINT32 i = 0; i < numFrames; i++) {
        float sample = 0.0f;
        
        // 다중 채널을 모노로 변환
        if (pFormat->nChannels == 1) {
            // 모노: 그대로 사용
            sample = floatData[i];
        } else {
            // 스테레오 이상: 앞의 2채널만 사용하여 스테레오로 처리
            sample = (floatData[i * pFormat->nChannels] + floatData[i * pFormat->nChannels + 1]) * 0.5f;
        }
        mono[i] = sample;
        
        // 레벨미터에 추가
        int16_t intSample = static_cast<int16_t>(sample * 32767.0f);
        if (!muteMic.load()) {
            micLevelMeter.addSamples(&intSample, 1);
        }
        // 디버그 저장
        SaveMicDebugIfEnabled(&intSample, 1, pFormat->nSamplesPerSec);
    }

    // 다운워드 익스팬더(옵션) 적용: 팬 등 지속 노이즈 완만 억제
    if (micExpanderEnabled) {
        ApplyMicExpander(mono, pFormat->nSamplesPerSec);
    }

    // 16 kHz로 상태형 리샘플하여 FIFO에 푸시
    std::vector<float> mono16k;
    ResampleLinearMonoStateful(mono.data(), mono.size(), pFormat->nSamplesPerSec, AudioConfig::SAMPLE_RATE,
                               mono16k, micResamplePhase, micResampleLast, micResampleInRate);
    // Pause 중에는(녹음 중 + 일시정지) 레벨미터만 유지, 녹음 FIFO에는 넣지 않음
    if (!(isRecording && isPaused)) {
        PushToFifo(micFifo16k, micFifoMutex, mono16k.data(), mono16k.size());
        micPushed16kTotal += mono16k.size();
    }
    
    // 레벨 이벤트 전송 (100ms마다)
    static auto lastLevelTime = std::chrono::steady_clock::now();
    auto now = std::chrono::steady_clock::now();
    if (std::chrono::duration_cast<std::chrono::milliseconds>(now - lastLevelTime).count() >= 100) {
        double rms = (muteMic.load() || !levelMeterEnabled.load()) ? 0.0 : micLevelMeter.getRMSAndReset();
        SendLevelEvent("mic", rms);
        lastLevelTime = now;
    }
}

void AudioHelper::SaveMicDebugIfEnabled(const int16_t* samples, size_t count, uint32_t sampleRate) {
    if (!debugRawSaveEnabled) return;
    // 출력 디렉터리 설정이 없으면 실행 파일 위치 사용
    try {
        if (!micDebugOpened) {
            std::wstring dir = outputDirectory;
            if (dir.empty()) {
                wchar_t modulePath[MAX_PATH] = {0};
                GetModuleFileNameW(nullptr, modulePath, MAX_PATH);
                dir = std::filesystem::path(modulePath).parent_path().wstring();
            }
            // 파일명: YYYYMMDD_HHMMSS_mic-raw.wav
            auto now = std::chrono::system_clock::now();
            std::time_t t = std::chrono::system_clock::to_time_t(now);
            std::tm tm{}; localtime_s(&tm, &t);
            char name[64];
            std::snprintf(name, sizeof(name), "%04d%02d%02d_%02d%02d%02d_mic-raw.wav",
                          tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                          tm.tm_hour, tm.tm_min, tm.tm_sec);
            std::wstring wname(name, name + std::strlen(name));
            std::wstring path = (std::filesystem::path(dir) / wname).wstring();
            micDebugWriter.open(path, sampleRate, AudioConfig::CHANNELS, AudioConfig::BITS_PER_SAMPLE);
            micDebugSampleRate = sampleRate;
            micDebugOpened = true;
            LOG_INFO("Mic debug writer opened");
        }
        micDebugWriter.writeSamples(samples, count);
        micSamplesWritten += count;
    } catch (...) {
        // 디버그 저장 실패는 무시
    }
}

void AudioHelper::ProcessSystemData(const BYTE* pData, UINT32 numFrames, WAVEFORMATEX* pFormat) {
    const float* floatData = reinterpret_cast<const float*>(pData);
    std::vector<float> mono;
    mono.resize(numFrames);
    
    for (UINT32 i = 0; i < numFrames; i++) {
        float sample = 0.0f;
        
        // 다중 채널을 모노로 변환
        if (pFormat->nChannels == 1) {
            // 모노: 그대로 사용
            sample = floatData[i];
        } else {
            // 스테레오 이상: 앞의 2채널만 사용하여 스테레오로 처리
            sample = (floatData[i * pFormat->nChannels] + floatData[i * pFormat->nChannels + 1]) * 0.5f;
        }
        mono[i] = sample;
        
        // 링버퍼에 추가
        sysAudioBuffer.push(sample);
        
        // 레벨미터에 추가
        int16_t intSample = static_cast<int16_t>(sample * 32767.0f);
        if (!muteSystem.load()) {
            sysLevelMeter.addSamples(&intSample, 1);
        }
        // 디버그 저장
        SaveSystemDebugIfEnabled(&intSample, 1, pFormat->nSamplesPerSec);
    }

    // 16 kHz로 상태형 리샘플하여 FIFO에 푸시
    std::vector<float> mono16k;
    ResampleLinearMonoStateful(mono.data(), mono.size(), pFormat->nSamplesPerSec, AudioConfig::SAMPLE_RATE,
                               mono16k, sysResamplePhase, sysResampleLast, sysResampleInRate);
    // Pause 중에는(녹음 중 + 일시정지) 레벨미터만 유지, 녹음 FIFO에는 넣지 않음
    if (!(isRecording && isPaused)) {
        PushToFifo(sysFifo16k, sysFifoMutex, mono16k.data(), mono16k.size());
    }
    
    // 레벨 이벤트 전송
    static auto lastLevelTime = std::chrono::steady_clock::now();
    auto now = std::chrono::steady_clock::now();
    if (std::chrono::duration_cast<std::chrono::milliseconds>(now - lastLevelTime).count() >= 100) {
        double rms = (muteSystem.load() || !levelMeterEnabled.load()) ? 0.0 : sysLevelMeter.getRMSAndReset();
        SendLevelEvent("system", rms);
        lastLevelTime = now;
    }
}

void AudioHelper::SaveSystemDebugIfEnabled(const int16_t* samples, size_t count, uint32_t sampleRate) {
    if (!debugRawSaveEnabled) return;
    try {
        if (!sysDebugOpened) {
            std::wstring dir = outputDirectory;
            if (dir.empty()) {
                wchar_t modulePath[MAX_PATH] = {0};
                GetModuleFileNameW(nullptr, modulePath, MAX_PATH);
                dir = std::filesystem::path(modulePath).parent_path().wstring();
            }
            auto now = std::chrono::system_clock::now();
            std::time_t t = std::chrono::system_clock::to_time_t(now);
            std::tm tm{}; localtime_s(&tm, &t);
            char name[64];
            std::snprintf(name, sizeof(name), "%04d%02d%02d_%02d%02d%02d_sys-raw.wav",
                          tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                          tm.tm_hour, tm.tm_min, tm.tm_sec);
            std::wstring wname(name, name + std::strlen(name));
            std::wstring path = (std::filesystem::path(dir) / wname).wstring();
            sysDebugWriter.open(path, sampleRate, AudioConfig::CHANNELS, AudioConfig::BITS_PER_SAMPLE);
            sysDebugSampleRate = sampleRate;
            sysDebugOpened = true;
            LOG_INFO("System debug writer opened");
        }
        sysDebugWriter.writeSamples(samples, count);
        sysSamplesWritten += count;
    } catch (...) {
    }
}

// 마이크 노이즈 저감을 위한 다운워드 익스팬더 구현
void AudioHelper::ApplyMicExpander(std::vector<float>& data, uint32_t sampleRate) {
    if (data.empty() || sampleRate == 0) return;
    // attack/release 계수 계산 (1차 지수형)
    const float attackA = std::exp(-1000.0f / std::fmax(1.0f, micExpanderAttackMs) / static_cast<float>(sampleRate));
    const float releaseA = std::exp(-1000.0f / std::fmax(1.0f, micExpanderReleaseMs) / static_cast<float>(sampleRate));
    const uint32_t hangSamples = static_cast<uint32_t>(micExpanderHangMs * static_cast<float>(sampleRate) / 1000.0f);

    for (size_t i = 0; i < data.size(); ++i) {
        float x = data[i];
        float absx = std::fabs(x);
        // Envelope follower (RMS 근사)
        float targetEnv = absx;
        micExpanderEnv = (targetEnv > micExpanderEnv)
            ? (attackA * micExpanderEnv + (1.0f - attackA) * targetEnv)
            : (releaseA * micExpanderEnv + (1.0f - releaseA) * targetEnv);

        // 문턱 위: 게이트 완전 오픈 + hang 유지
        if (micExpanderEnv >= micExpanderThresholdRms) {
            micExpanderGain = 1.0f;
            micExpanderHangSamplesLeft = hangSamples;
        } else {
            if (micExpanderHangSamplesLeft > 0) {
                micExpanderHangSamplesLeft--;
                micExpanderGain = 1.0f;
            } else {
                // 문턱 아래: 비율 기반으로 noise floor까지 완만 감쇄
                float gainTarget = 1.0f;
                float t = 0.0f;
                if (micExpanderThresholdRms > 0.0f) {
                    t = std::clamp(micExpanderEnv / micExpanderThresholdRms, 0.0f, 1.0f);
                }
                float desired = micExpanderNoiseFloor + t * (1.0f - micExpanderNoiseFloor);
                gainTarget = std::pow(desired, micExpanderRatio);
                // 릴리즈 기반 부드러운 추적
                micExpanderGain = 0.9f * micExpanderGain + 0.1f * gainTarget;
            }
        }

        data[i] = x * micExpanderGain;
    }
}

void AudioHelper::UpdateLevels(const int16_t* samples, size_t count) {
    // 이미 ProcessMicrophoneData와 ProcessSystemData에서 처리됨
}

void AudioHelper::UpdateWaveform(const int16_t* samples, size_t count) {
    // 다운샘플링하여 웨이브폼 버퍼에 추가
    size_t step = count / 64; // 64포인트로 다운샘플링
    if (step == 0) step = 1;
    
    for (size_t i = 0; i < count; i += step) {
        float normalized = samples[i] / 32768.0f;
        waveformBuffer[waveformIndex] = normalized;
        waveformIndex = (waveformIndex + 1) % waveformBuffer.size();
    }
}

void AudioHelper::DetectSilence(const int16_t* samples, size_t count) {
    // 녹음 중이 아닐 때(테스트 모드 포함) 또는 무음 감지가 비활성화된 경우 건너뛰기
    if (!isRecording || silenceDetectionDisabled) {
        return;
    }
    
    double rms = 0.0;
    for (size_t i = 0; i < count; i++) {
        double normalized = samples[i] / 32768.0;
        rms += normalized * normalized;
    }
    rms = sqrt(rms / count);
    
    // SystemOnly: 최종 녹음본 = 시스템 소리 × GAIN_SYS 이므로 시스템 기준에 게인을 곱해 비교한다.
    // (0.02 는 마이크 잡음 기준이라 작은 볼륨의 시스템 소리를 무음으로 판정했다)
    const double threshold = (currentMode == CaptureMode::SystemOnly)
        ? AudioConfig::SILENCE_THRESHOLD_SYS * AudioConfig::GAIN_SYS
        : AudioConfig::SILENCE_THRESHOLD;
    bool isSilent = rms < threshold;
    
    // 주기적으로 RMS 값 로깅 (5초마다, 무음 감지 활성 시만)
    static uint64_t lastRmsLogMs = 0;
    uint64_t currentMs = GetCurrentTimeMs();
    if (currentMs - lastRmsLogMs >= 5000) {
        lastRmsLogMs = currentMs;
        LOG_INFO(std::string("RMS level: ") + std::to_string(rms) + 
                 ", threshold: " + std::to_string(threshold) + 
                 ", isSilent: " + (isSilent ? "true" : "false"));
    }
    
    if (isSilent && !silenceDetected) {
        // 무음 시작
        silenceDetected = true;
        silenceStartMs = GetCurrentTimeMs();
        sustainedEventSent = false; // 새로운 무음 구간 시작 시 리셋
        lastEarlyWarningIndex = 0;  // 7초 경고 인덱스 리셋
        LOG_INFO("Silence detection started");
    } else if (!isSilent && silenceDetected) {
        // 사운드 감지됨 - 무음 감지 완전 해제
        silenceDetected = false;
        sustainedEventSent = false; // 리셋
        silenceDetectionDisabled = true; // 무음 감지 비활성화
        lastEarlyWarningIndex = 0;  // 리셋
        LOG_INFO("Sound detected - silence detection disabled permanently");
        
        // 무음 종료 이벤트 전송
        json event;
        event.set("ev", "silence");
        event.set("state", "off");
        SendEvent(event);
    }
    
    if (silenceDetected) {
        uint64_t elapsedMs = GetCurrentTimeMs() - silenceStartMs;
        
        // 30초 지속 시 sustained 이벤트 전송 후 즉시 off 이벤트도 전송
        if (elapsedMs >= 30000 && !sustainedEventSent) {
            sustainedEventSent = true;
            silenceDetectionDisabled = true; // 30초 후 무음 감지 비활성화
            json event;
            event.set("ev", "silence");
            event.set("state", "sustained");
            event.set("elapsedMs", elapsedMs);
            SendEvent(event);
            LOG_INFO("30-second sustained silence detected - UI should send email notification");
            LOG_INFO("Silence detection disabled after 30 seconds");
        } else if (elapsedMs < 30000) {
            // 7초마다 early 이벤트 전송을 인덱스 기반으로 보장
            // 7, 14, 21, 28초 → index = 1..4
            uint32_t expectedIndex = static_cast<uint32_t>(elapsedMs / 7000);
            if (expectedIndex > 0 && expectedIndex <= 4 && expectedIndex > lastEarlyWarningIndex) {
                lastEarlyWarningIndex = expectedIndex;
                json event;
                event.set("ev", "silence");
                event.set("state", "early");
                event.set("elapsedMs", static_cast<uint64_t>(expectedIndex) * 7000ULL);
                SendEvent(event);
                LOG_INFO(std::string("Early silence warning: ") + std::to_string(expectedIndex * 7) + " seconds");
            }
        }
    }
}

void AudioHelper::SendEvent(const json& event) {
    std::cout << event.dump() << std::endl;
}


void AudioHelper::SendError(const std::string& code, const std::string& message) {
    json event;
    event.set("ev", "error");
    event.set("code", code);
    event.set("message", message);
    SendEvent(event);
    LOG_ERROR(code + ": " + message);
}

void AudioHelper::SendLevelEvent(const std::string& source, double rms) {
    json event;
    event.set("ev", "level");
    event.set("source", source);
    event.set("rms", rms);
    event.set("t", GetCurrentTimeMs());
    SendEvent(event);
}

void AudioHelper::SendMicStateEvent(const char* state) {
    json ev; ev.set("ev", "mic_state"); ev.set("state", state);
    SendEvent(ev);
}

void AudioHelper::SendProgressEvent() {
    double seconds = totalSamples / static_cast<double>(AudioConfig::SAMPLE_RATE);
    json event;
    event.set("ev", "progress");
    event.set("seconds", seconds);
    event.set("samples", totalSamples);
    // mic 기준은 UI 동작 일관성을 위해 파일 진행(seconds)과 동일하게 보고
    // (pause/level meter 중 캡쳐된 mic 샘플로 시간 점프를 방지)
    event.set("mic_samples", static_cast<uint64_t>(seconds * AudioConfig::SAMPLE_RATE));
    event.set("mic_seconds", seconds);
    SendEvent(event);
}

void AudioHelper::SendWaveformEvent() {
    json event;
    event.set("ev", "waveform");
    event.set("t", GetCurrentTimeMs());
    
    // waveformBuffer를 문자열로 변환
    std::string amplitudesStr = "[";
    for (size_t i = 0; i < waveformBuffer.size(); ++i) {
        if (i > 0) amplitudesStr += ",";
        amplitudesStr += std::to_string(waveformBuffer[i]);
    }
    amplitudesStr += "]";
    event.set("amplitudes", amplitudesStr);
    SendEvent(event);
}

uint64_t AudioHelper::GetCurrentTimeMs() {
    auto now = std::chrono::system_clock::now();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch());
    return ms.count();
}

bool AudioHelper::IsMicDeviceActive(const std::wstring& devId) const {
    if (devId.empty()) return false;
    try {
        IMMDeviceEnumerator* pEnum = nullptr;
        if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), NULL, CLSCTX_ALL,
                                    __uuidof(IMMDeviceEnumerator), (void**)&pEnum))) {
            return false;
        }
        IMMDevice* pDev = nullptr;
        HRESULT hr = pEnum->GetDevice(devId.c_str(), &pDev);
        if (FAILED(hr) || !pDev) {
            if (pEnum) pEnum->Release();
            return false;
        }
        DWORD state = 0;
        hr = pDev->GetState(&state);
        pDev->Release();
        pEnum->Release();
        if (FAILED(hr)) return false;
        return state == DEVICE_STATE_ACTIVE;
    } catch (...) {
        return false;
    }
}

std::wstring AudioHelper::PickSingleActiveMicId() const {
    try {
        auto devices = EnumerateAudioDevices(); // ACTIVE 캡쳐만
        if (devices.size() == 1) {
            return devices.front().id;
        }
    } catch (...) {
        // ignore
    }
    return L"";
}

bool AudioHelper::HasActiveCaptureDevice() {
    try {
        IMMDeviceEnumerator* pEnum = nullptr;
        if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), NULL, CLSCTX_ALL,
                                    __uuidof(IMMDeviceEnumerator), (void**)&pEnum))) return false;
        IMMDevice* pDef = nullptr;
        HRESULT hr = pEnum->GetDefaultAudioEndpoint(eCapture, eConsole, &pDef);
        if (FAILED(hr) || !pDef) { if (pEnum) pEnum->Release(); return false; }
        DWORD state = 0;
        IPropertyStore* pProps = nullptr;
        // 간단히 존재만 확인하고 해제
        pDef->Release();
        pEnum->Release();
        return true;
    } catch (...) {
        return false;
    }
}

void AudioHelper::ScheduleLevelMeterAutoRestart(const std::string& reason) {
    // 디바운스: 이미 예약되었으면 무시
    bool expected = false;
    if (!autoRestartScheduled.compare_exchange_strong(expected, true)) {
        LOG_INFO("Auto restart already scheduled; skip duplicate trigger");
        return;
    }
    // 백오프 재시도 스레드
    std::thread([this, reason]() {
        LOG_INFO(std::string("Scheduling auto restart due to ") + reason);
        const int delaysMs[3] = { 1000, 2000, 4000 };
        for (int i = 0; i < 3; ++i) {
            Sleep(delaysMs[i]);
            if (isRunning) { break; }
            if (!levelMeterEnabled.load()) { break; }
            if (!HasActiveCaptureDevice()) {
                LOG_WARN(std::string("Auto restart attempt ") + std::to_string(i+1) + "/3: no capture device");
                continue;
            }
            try {
                StartLevelMeterCaptureIfNeeded();
                LOG_INFO(std::string("Auto restart success on attempt ") + std::to_string(i+1));
                break;
            } catch (...) {
                LOG_WARN(std::string("Auto restart failed on attempt ") + std::to_string(i+1));
            }
        }
        autoRestartScheduled.store(false);
    }).detach();
}

void AudioHelper::Cleanup() {
    if (isRunning) {
        HandleStop();
    } else {
        // 실행 중이 아니더라도 세그먼트/디버그 파일을 안전하게 마무리한다.
        if (segmentManager) {
            LOG_INFO("Finalizing current segment in Cleanup (not running)");
            segmentManager->FinalizeCurrentSegment();
        }
        FinalizeDebugLengths();
    }
    
    // 장치 변경 알림 해제
    UnregisterDeviceNotifications();
    
    // COM 인터페이스 정리
    if (pMicCaptureClient) { pMicCaptureClient->Release(); pMicCaptureClient = nullptr; }
    if (pSysCaptureClient) { pSysCaptureClient->Release(); pSysCaptureClient = nullptr; }
    if (pMicClient) { pMicClient->Release(); pMicClient = nullptr; }
    if (pSysClient) { pSysClient->Release(); pSysClient = nullptr; }
    if (pMicDevice) { pMicDevice->Release(); pMicDevice = nullptr; }
    if (pSysDevice) { pSysDevice->Release(); pSysDevice = nullptr; }
    if (pEnumerator) { pEnumerator->Release(); pEnumerator = nullptr; }
    
    // 워치독 스레드 조인(존재 시)
    if (watchdogThread.joinable()) {
        // 종료 조건: isRunning는 위에서 false가 되었고, 스레드는 루프 탈출 후 종료됨
        // 충분히 빠르게 종료되도록 짧게 대기
        try {
            watchdogThread.join();
        } catch (...) {
        }
    }

    CoUninitialize();
    // 타이머 분해능 원복
    timeEndPeriod(1);
}

// 디스크 여유 공간 조회 (출력 디렉터리 기준)
bool AudioHelper::QueryFreeBytes(uint64_t& freeBytes) {
    try {
        std::filesystem::path p;
        if (!outputDirectory.empty()) {
            p = std::filesystem::u8path(WStringToString(outputDirectory));
        } else {
            wchar_t modulePath[MAX_PATH] = {0};
            GetModuleFileNameW(nullptr, modulePath, MAX_PATH);
            p = std::filesystem::path(modulePath).parent_path();
        }

        // 가능한 한 정규화/절대 경로로 변환
        std::error_code ec;
        if (!p.is_absolute()) p = std::filesystem::absolute(p, ec);
        std::filesystem::path target = std::filesystem::weakly_canonical(p, ec);
        if (target.empty()) target = p;

        ULARGE_INTEGER freeCaller = {0}, total = {0}, freeTotal = {0};
        if (GetDiskFreeSpaceExW(target.c_str(), &freeCaller, &total, &freeTotal)) {
            freeBytes = static_cast<uint64_t>(freeCaller.QuadPart);
            return true;
        }

        // 실패 시, 드라이브 루트로 폴백 (예: C:\)
        std::filesystem::path root = target.root_path();
        if (!root.empty()) {
            if (GetDiskFreeSpaceExW(root.c_str(), &freeCaller, &total, &freeTotal)) {
                freeBytes = static_cast<uint64_t>(freeCaller.QuadPart);
                return true;
            }
        }
        // 추가 폴백: 현재 작업 디렉터리 드라이브
        wchar_t cwdBuf[MAX_PATH] = {0};
        if (GetCurrentDirectoryW(MAX_PATH, cwdBuf) > 0) {
            if (GetDiskFreeSpaceExW(cwdBuf, &freeCaller, &total, &freeTotal)) {
                freeBytes = static_cast<uint64_t>(freeCaller.QuadPart);
                return true;
            }
        }
        LOG_WARN("GetDiskFreeSpaceExW failed for target and fallbacks");
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("QueryFreeBytes exception: ") + e.what());
    } catch (...) {
        LOG_ERROR("QueryFreeBytes unknown exception");
    }
    return false;
}

// 1초마다 디스크 상태를 helper→UI로 전송
void AudioHelper::CheckAndEmitDiskStatusIfDue() {
    // 녹음 중이 아닐 때(테스트 모드 포함)에는 디스크 상태 체크/이벤트 전송을 하지 않음
    if (!isRecording) {
        return;
    }
    const uint64_t nowMs = GetCurrentTimeMs();
    if (lastDiskStatusMs != 0 && (nowMs - lastDiskStatusMs) < 1000) return;
    lastDiskStatusMs = nowMs;

    uint64_t freeBytes = 0;
    if (!QueryFreeBytes(freeBytes)) return;

    // 임계값: 500MB(충분), 50MB(가능), 그 미만(불가)
    std::string category;
    if (freeBytes >= DISK_STATUS_OK) category = "ok";        // 충분
    else if (freeBytes >= DISK_STATUS_LOW) category = "low";    // 부족하지만 가능
    else category = "critical";                            // 불가

    // 상태 변화 시 즉시 전송. 상태 동일이어도 10초마다 재전송.
    bool forceByInterval = (lastDiskStatusEventMs == 0) || ((nowMs - lastDiskStatusEventMs) >= 5000);
    if (category != lastDiskStatusCategory || forceByInterval) {
        lastDiskStatusCategory = category;
        lastDiskStatusEventMs = nowMs;
        json ev;
        ev.set("ev", "disk_status");
        ev.set("status", category); // ok | low | critical
        ev.set("free_bytes", freeBytes);
        SendEvent(ev);
        if (category == "critical") { LOG_WARN("Disk space critical: <50MB remaining"); }
    }

    // 정책: 여유 공간이 critical로 떨어지면 즉시 안전 정지 (경계 대기 없이)
    if ((category == "critical") && isRunning && !stopDueToLowDisk) {
        stopDueToLowDisk = true;
        LOG_WARN("Low disk space detected → immediate safe stop");
        StopRecordingAsyncWithDiskLow("DISK_SPACE_LOW_STOP", "디스크 여유 공간 부족으로 안전 중지합니다.");
    }
}

// 장치 변경 감지 관련 메서드들
void AudioHelper::RegisterDeviceNotifications() {
    if (!pEnumerator) return;
    
    try {
        pDeviceNotifier = new DeviceChangeNotifier(this);
        HRESULT hr = pEnumerator->RegisterEndpointNotificationCallback(pDeviceNotifier);
        if (SUCCEEDED(hr)) {
#ifdef _DEBUG_LOG
            LOG_INFO("Device change notifications registered");
#else
            LOG_WARN("Device change notifications registered");
#endif
        } else {
            LOG_ERROR(std::string("Failed to register device notifications: ") + std::to_string(hr));
            delete pDeviceNotifier;
            pDeviceNotifier = nullptr;
        }
    } catch (...) {
        LOG_ERROR("Exception while registering device notifications");
        if (pDeviceNotifier) {
            delete pDeviceNotifier;
            pDeviceNotifier = nullptr;
        }
    }
}

void AudioHelper::UnregisterDeviceNotifications() {
    if (pEnumerator && pDeviceNotifier) {
        pEnumerator->UnregisterEndpointNotificationCallback(pDeviceNotifier);
        pDeviceNotifier->Release();
        pDeviceNotifier = nullptr;
#ifdef _DEBUG_LOG
        LOG_INFO("Device change notifications unregistered");
#else
        LOG_WARN("Device change notifications unregistered");
#endif
    }
}

void AudioHelper::NotifySystemDeviceChanged() {
    // 캡쳐 중일 때만 처리
    if (isRunning && (currentMode != CaptureMode::MicOnly)) {
        deviceChangeRequested = true;
#ifdef _DEBUG_LOG
        LOG_INFO("System device change requested");
#else
        LOG_WARN("System device change requested");
#endif
    }
}

void AudioHelper::NotifyMicDeviceChanged(const std::string& reason) {
    // 선택 마이크 제거 → 최초 1회만 처리 (pause 여부 무관)
    if (reason == "selected_removed") {
        bool expected = false;
        if (!micStopScheduled.compare_exchange_strong(expected, true)) {
            LOG_INFO("Mic issue already scheduled; skip duplicate");
            return;
        }
        stoppingDueToMicRemoval.store(true);
        resumeBlockedDueToMic.store(true);
        if (!stopErrorSent.exchange(true)) {
            SendError("MIC_DEVICE_LOST", "마이크 장치가 제거되거나 비활성화되어 녹음을 중단합니다.");
        }
        if (isRunning || isRecording) {
            HandleStop();
        }
        return;
    }
    // 기본 경로: 기존 정책 유지(로그 포함)
    if (isRunning && !micStopScheduled) {
        micStopScheduled = true;
        StopRecordingAsyncWithMicError("MIC_DEVICE_CHANGED", std::string("마이크 장치 변경: ") + reason);
    }
}

void AudioHelper::StopRecordingAsyncWithMicError(const std::string& code, const std::string& message) {
    // 비동기로 정지 처리하여 데드락 방지
    std::thread([this, code, message]() {
        LOG_ERROR(std::string("Stopping due to mic issue: ") + message);
        SendError(code, message);
        HandleStop();
        micStopScheduled = false;
    }).detach();
}

void AudioHelper::StopRecordingAsyncWithDiskLow(const std::string& code, const std::string& message) {
    // 비동기로 정지 처리하여 데드락 방지
    std::thread([this, code, message]() {
        LOG_WARN(std::string("Stopping due to low disk: ") + message);
        SendError(code, message);
        HandleStop();
        stopDueToLowDisk = false;
    }).detach();
}

void AudioHelper::OnSystemDeviceChanged() {
    if (!deviceChangeRequested) return;
    deviceChangeRequested = false;
    
    LOG_INFO("Processing system device change");
    
    // 현재 시스템 디바이스 정리
    CleanupSystemDevice();
    
    // 새 디바이스로 재연결 시도
    if (ReconnectSystemDevice()) {
        LOG_INFO("System device reconnected successfully");
        // 디바이스 재연결 후 AEC 재초기화로 동기화 회복
        InitializeAudioProcessing(AudioConfig::SAMPLE_RATE, AudioConfig::CHANNELS);
        // 버퍼/상태 리셋: 과거 참조와 새 장치 참조가 섞이지 않도록 정리
        {
            std::lock_guard<std::mutex> lk(sysFifoMutex);
            sysFifo16k.clear();
        }
        // 선택(추천): 마이크 FIFO도 초반 200ms를 버려 더 빠른 재수렴 유도
        {
            std::lock_guard<std::mutex> lk(micFifoMutex);
            const size_t drop = (AudioConfig::SAMPLE_RATE * 200) / 1000; // 200ms
            size_t toDrop = (std::min)(drop, micFifo16k.size());
            while (toDrop-- > 0 && !micFifo16k.empty()) micFifo16k.pop_front();
        }
        sysResamplePhase = 0.0;
        sysResampleLast = 0.0f;
        sysResampleInRate = 0;
        aecRefDelayLine.clear();
        aecMicHPHist.clear();
        aecSysHPHist.clear();
        aecFixedDelayEstimate = 0.0;
        aecFixedDelaySamples = (aecFixedDelayMs * AudioConfig::SAMPLE_RATE) / 1000;
        aecReverseFramesPresent10ms = 0;
        aecCaptureFrames10ms = 0;
        aecLastDelayUpdate = std::chrono::steady_clock::now();
        // 클릭 방지: 200ms 페이드 인 설정
        fadeTotalSamples = AudioConfig::SAMPLE_RATE / 5; // 200ms
        fadeSamplesRemaining = fadeTotalSamples;
        json event;
        event.set("ev", "device_reconnected");
        event.set("type", "system");
        event.set("aec_reset", true);
        SendEvent(event);
    } else {
        LOG_ERROR("Failed to reconnect system device");
        SendError("DEVICE_RECONNECT_FAILED", "시스템 오디오 디바이스 재연결에 실패했습니다.");
    }
}

bool AudioHelper::ReconnectSystemDevice() {
    try {
        // 새로운 기본 시스템 디바이스 가져오기
        IMMDevice* pNewDevice = nullptr;
        HRESULT hr = GetDefaultDevice(eRender, &pNewDevice);
        if (FAILED(hr)) {
            LOG_ERROR("Failed to get new default render device");
            return false;
        }
        
        // 새 디바이스 ID 확인
        LPWSTR pwszID = nullptr;
        hr = pNewDevice->GetId(&pwszID);
        if (SUCCEEDED(hr)) {
            std::wstring newDeviceId = pwszID;
            CoTaskMemFree(pwszID);
            
            // 같은 디바이스면 재연결할 필요 없음
            if (newDeviceId == currentSysDeviceId) {
                pNewDevice->Release();
                return true;
            }
            
            currentSysDeviceId = newDeviceId;
            LOG_INFO(std::string("Switching to new system device: ") + WStringToString(newDeviceId));
        }
        
        // 새 오디오 클라이언트 초기화
        IAudioClient* pNewClient = nullptr;
        IAudioCaptureClient* pNewCaptureClient = nullptr;
        hr = InitializeAudioClient(pNewDevice, &pNewClient, &pNewCaptureClient, true);
        
        if (FAILED(hr)) {
            LOG_ERROR("Failed to initialize new system audio client");
            pNewDevice->Release();
            return false;
        }
        
        // 기존 디바이스 정리 (이미 CleanupSystemDevice에서 처리됨)
        
        // 새 디바이스로 교체
        pSysDevice = pNewDevice;
        pSysClient = pNewClient;
        pSysCaptureClient = pNewCaptureClient;
        
        // 새 클라이언트 시작
        hr = pSysClient->Start();
        if (FAILED(hr)) {
            LOG_ERROR("Failed to start new system audio client");
            CleanupSystemDevice();
            return false;
        }
        
        return true;
        
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("Exception in ReconnectSystemDevice: ") + e.what());
        return false;
    }
}

void AudioHelper::CleanupSystemDevice() {
    // 시스템 오디오 클라이언트 중지 및 정리
    if (pSysClient) {
        pSysClient->Stop();
        pSysClient->Release();
        pSysClient = nullptr;
    }
    if (pSysCaptureClient) {
        pSysCaptureClient->Release();
        pSysCaptureClient = nullptr;
    }
    if (pSysDevice) {
        pSysDevice->Release();
        pSysDevice = nullptr;
    }
}

void AudioHelper::PushToFifo(std::deque<float>& fifo, std::mutex& mtx, const float* samples, size_t count) {
    std::lock_guard<std::mutex> lock(mtx);
    for (size_t i = 0; i < count; ++i) fifo.push_back(samples[i]);
    const size_t maxSamples = AudioConfig::SAMPLE_RATE * 3; // 최대 3초 보관
    while (fifo.size() > maxSamples) fifo.pop_front();
}

size_t AudioHelper::PopFromFifo(std::deque<float>& fifo, std::mutex& mtx, float* out, size_t wantCount) {
    std::lock_guard<std::mutex> lock(mtx);
    size_t n = (std::min)(wantCount, static_cast<size_t>(fifo.size()));
    for (size_t i = 0; i < n; ++i) { out[i] = fifo.front(); fifo.pop_front(); }
    return n;
}

void AudioHelper::EnsureOpenMixDebug() {
    if (mixDebugOpened) return;
    std::wstring dir = outputDirectory;
    if (dir.empty()) {
        wchar_t modulePath[MAX_PATH] = {0};
        GetModuleFileNameW(nullptr, modulePath, MAX_PATH);
        dir = std::filesystem::path(modulePath).parent_path().wstring();
    }
    // 세션 단일 파일 경로 고정: 이미 있으면 같은 경로로 재사용(중복 생성 방지)
    if (mixFilePath.empty()) {
        auto now = std::chrono::system_clock::now();
        std::time_t t = std::chrono::system_clock::to_time_t(now);
        std::tm tm{}; localtime_s(&tm, &t);
        char name[64];
        std::snprintf(name, sizeof(name), "%04d%02d%02d_%02d%02d%02d_mix.wav",
                      tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                      tm.tm_hour, tm.tm_min, tm.tm_sec);
        std::wstring wname(name, name + std::strlen(name));
        mixFilePath = (std::filesystem::path(dir) / wname).wstring();
    }
    mixDebugWriter.open(mixFilePath, AudioConfig::SAMPLE_RATE, AudioConfig::CHANNELS, AudioConfig::BITS_PER_SAMPLE);
    mixDebugOpened = true;
}

void AudioHelper::PrepareDelayedReference(const std::vector<float>& refIn, std::vector<float>& refOut, size_t count) {
    // 고정 지연만큼 큐에 쌓은 뒤, 동일 길이의 지연된 참조를 생성
    refOut.resize(count);
    for (size_t i = 0; i < count; ++i) {
        aecRefDelayLine.push_back(refIn[i]);
        float delayed = 0.0f;
        if (aecRefDelayLine.size() > aecFixedDelaySamples) {
            delayed = aecRefDelayLine.front();
            aecRefDelayLine.pop_front();
        }
        refOut[i] = delayed;
    }
}

void AudioHelper::AppendAecHistory(const std::vector<float>& micHP, const std::vector<float>& sysHP) {
    for (float v : micHP) {
        aecMicHPHist.push_back(v);
        if (aecMicHPHist.size() > aecDelayWindowSamples) aecMicHPHist.pop_front();
    }
    for (float v : sysHP) {
        aecSysHPHist.push_back(v);
        if (aecSysHPHist.size() > aecDelayWindowSamples + aecMaxLagSamples) aecSysHPHist.pop_front();
    }
}

void AudioHelper::MaybeUpdateAecDelay() {
    auto now = std::chrono::steady_clock::now();
    if (std::chrono::duration_cast<std::chrono::milliseconds>(now - aecLastDelayUpdate).count() < 200) {
        return;
    }
    aecLastDelayUpdate = now;
    // 충분한 히스토리가 없으면 스킵
    if (aecMicHPHist.size() < aecDelayWindowSamples || aecSysHPHist.size() < aecDelayWindowSamples + aecMaxLagSamples) return;

    // mic 구간(마지막 window)과 sys 히스토리에서 0..maxLag 탐색하여 최대 상관 지연을 찾는다
    std::vector<float> micSeg(aecDelayWindowSamples);
    {
        size_t start = aecMicHPHist.size() - aecDelayWindowSamples;
        size_t i = 0; for (auto it = std::next(aecMicHPHist.begin(), start); it != aecMicHPHist.end(); ++it) micSeg[i++] = *it;
    }
    size_t bestLag = aecFixedDelaySamples;
    double bestCorr = -1e9;
    for (size_t lag = 0; lag <= aecMaxLagSamples; ++lag) {
        // sys에서 mic과 같은 길이 추출(지연된 위치)
        size_t sysStart = aecSysHPHist.size() - aecDelayWindowSamples - lag;
        if (sysStart >= aecSysHPHist.size()) continue;
        double sumXY = 0.0, sumX2 = 0.0, sumY2 = 0.0;
        size_t i = 0; auto it = std::next(aecSysHPHist.begin(), sysStart);
        for (; i < aecDelayWindowSamples; ++i, ++it) {
            double x = micSeg[i];
            double y = *it;
            sumXY += x * y; sumX2 += x * x; sumY2 += y * y;
        }
        double denom = std::sqrt((sumX2 + 1e-9) * (sumY2 + 1e-9));
        double corr = (denom > 0.0) ? (sumXY / denom) : 0.0;
        if (corr > bestCorr) { bestCorr = corr; bestLag = lag; }
    }
    // 스무딩하여 업데이트
    aecFixedDelayEstimate = (1.0 - aecDelaySmoothAlpha) * aecFixedDelayEstimate + aecDelaySmoothAlpha * static_cast<double>(bestLag);
    aecFixedDelaySamples = static_cast<size_t>(aecFixedDelayEstimate + 0.5);
}

// 가이드 문서의 ProcessCapturedAudio 함수 구현
void AudioHelper::ProcessCapturedAudio(float* mic_data, float* system_data, int samples_per_channel) {
    if (!audioProcessor || !audioProcessor->IsInitialized()) {
        // AudioProcessor가 초기화되지 않은 경우 기존 로직 사용
        return;
    }
    
    try {
        // 1. 시스템 오디오를 참조 신호로 처리
        if (system_data) {
            int result = audioProcessor->ProcessReverseStream(system_data, samples_per_channel);
            if (result != 0) {
                LOG_WARN(std::string("ProcessReverseStream error: ") + std::to_string(result));
            }
        }
        
        // 2. 마이크 오디오에 에코 제거 적용
        if (mic_data) {
            int result = audioProcessor->ProcessStream(mic_data, samples_per_channel);
            if (result != 0) {
                LOG_WARN(std::string("ProcessStream error: ") + std::to_string(result));
            }
        }
        
        // 3. 통계 정보 주기적으로 출력 (5초마다)
        static auto lastStatsTime = std::chrono::steady_clock::now();
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::seconds>(now - lastStatsTime).count() >= 5) {
            audioProcessor->GetStatistics();
            lastStatsTime = now;
        }
        
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("ProcessCapturedAudio error: ") + e.what());
    }
}

void AudioHelper::MixBlockAndWrite(size_t chunkSamples) {
    // 마이크 기준: 블록이 준비될 때까지 대기하여 스킵 방지
    while (FifoSize(micFifo16k, micFifoMutex) < chunkSamples) {
        // 드레인 중이면 isRunning==false 여도 끝까지 기록해야 함
        if (!isRunning && !drainOnStop) return;
        Sleep(1);
    }

    std::vector<float> micBlock(chunkSamples, 0.0f);
    std::vector<float> sysBlock(chunkSamples, 0.0f);
    size_t micGot = PopFromFifo(micFifo16k, micFifoMutex, micBlock.data(), chunkSamples);
    size_t sysGot = PopFromFifo(sysFifo16k, sysFifoMutex, sysBlock.data(), chunkSamples);
    // Reverse(시스템) 프레임 부족 시 zero-pad로 보정(누락 프레임 방지)
    if (sysGot < chunkSamples) {
        std::fill(sysBlock.begin() + sysGot, sysBlock.end(), 0.0f);
    }
    // AEC 드리프트 모니터링 카운트 (실 reverse 프레임 기준)
    aecReverseFramesPresent10ms += (sysGot / 160);
    aecCaptureFrames10ms += (chunkSamples / 160);

    // AEC 처리: 가이드 문서의 ProcessCapturedAudio 사용
    if (aecEnabled && currentMode == CaptureMode::MicPlusSystem) {
        const size_t frameSamples = 160; // 10ms @16kHz (WebRTC 권장)
        
        // 160샘플 단위로 처리
        for (size_t off = 0; off + frameSamples <= chunkSamples; off += frameSamples) {
            float* micSeg = micBlock.data() + off;
            float* sysSeg = (sysGot > off) ? sysBlock.data() + off : nullptr;
            
            // 가이드 문서의 ProcessCapturedAudio 호출
            ProcessCapturedAudio(micSeg, sysSeg, static_cast<int>(frameSamples));
        }
    }

    // 음소거 적용: 저장 데이터는 0으로
    if (muteMic.load()) {
        std::fill(micBlock.begin(), micBlock.end(), 0.0f);
    }
    if (muteSystem.load()) {
        std::fill(sysBlock.begin(), sysBlock.end(), 0.0f);
    }

    // 덕킹을 위한 에너지 계산
    double sysEnergy = 0.0, micEnergy = 0.0;
    for (size_t i = 0; i < chunkSamples; ++i) {
        if (i < sysGot) sysEnergy += sysBlock[i] * sysBlock[i];
        micEnergy += micBlock[i] * micBlock[i];
    }
    sysEnergy /= chunkSamples;
    micEnergy /= chunkSamples;
    
    // 덕킹 게인 계산 (더블톡 시 마이크 음성 보호 우선)
    // 주의(한글 주석): 덕킹은 마이크가 아니라 시스템 신호에 적용해야 마이크가 작아지지 않는다.
    float duckingGain = 1.0f;
    if (currentMode == CaptureMode::MicPlusSystem && sysEnergy > micEnergy * 10.0) {
        // 시스템 에너지가 마이크보다 10배 이상 클 때 시스템 볼륨만 약하게 낮춤 (~-3dB)
        duckingGain = 0.7f;
    }

    std::vector<int16_t> out(chunkSamples);
    for (size_t i = 0; i < chunkSamples; ++i) {
        float micGain = (currentMode == CaptureMode::SystemOnly || muteMic.load()) ? 0.0f : static_cast<float>(AudioConfig::GAIN_MIC);
        float sysGain = (currentMode == CaptureMode::MicOnly || muteSystem.load()) ? 0.0f : static_cast<float>(AudioConfig::GAIN_SYS) * duckingGain;
        float m = micBlock[i] * micGain;
        float s = (i < sysGot ? sysBlock[i] : 0.0f) * sysGain;
        float x = m + s;
        if (x > 0.999f) x = 0.999f; else if (x < -0.999f) x = -0.999f;
        out[i] = static_cast<int16_t>(x * 32767.0f);
    }
    // 장치 전환 직후 200ms 페이드 인 적용 (클릭 방지)
    if (fadeSamplesRemaining > 0) {
        size_t n = (std::min)(chunkSamples, fadeSamplesRemaining);
        size_t start = fadeTotalSamples - fadeSamplesRemaining;
        for (size_t i = 0; i < n; ++i) {
            float factor = static_cast<float>(start + i + 1) / static_cast<float>(fadeTotalSamples);
            float scaled = static_cast<float>(out[i]) * factor;
            if (scaled > 32767.0f) scaled = 32767.0f; else if (scaled < -32768.0f) scaled = -32768.0f;
            out[i] = static_cast<int16_t>(scaled);
        }
        fadeSamplesRemaining -= n;
    }
    totalSamples += chunkSamples;

    // 최대 녹음 시간 도달 시(샘플 기준) 세그먼트 경계에서 안전하게 중지
    if (maxDurationMs > 0) {
        const uint64_t maxSamples = (maxDurationMs * AudioConfig::SAMPLE_RATE) / 1000ULL;
        if (totalSamples >= maxSamples) {
            // 경계까지 밀어붙이기: 현 세그먼트가 종료될 때까지 추가 블록 허용
            stopAtBoundary = true;
        }
    }

    // 출력 버퍼도 갱신(레벨/웨이브폼 업데이트용)
    if (outputBuffer.size() == chunkSamples) {
        std::memcpy(outputBuffer.data(), out.data(), chunkSamples * sizeof(int16_t));
    }

    if (debugRawSaveEnabled) {
        EnsureOpenMixDebug();
        mixDebugWriter.writeSamples(out.data(), out.size());
    }
    
    // SystemOnly 모드 재진입 경계 페이드인 적용: 직전 블록이 무음(데이터 없음)이고 이번 블록에 데이터가 생긴 경우
    if (currentMode == CaptureMode::SystemOnly) {
        bool sysHasDataThisChunk = (sysGot > 0);
        if (!sysHadDataPrevChunk && sysHasDataThisChunk && sysReentryFadeRemaining == 0) {
            // 2~5ms 권장. AudioConfig::FADE_MS 사용 (기본 4ms)
            size_t fadeSamples = static_cast<size_t>((AudioConfig::SAMPLE_RATE * AudioConfig::FADE_MS) / 1000);
            if (fadeSamples < 1) fadeSamples = 1;
            sysReentryFadeTotal = fadeSamples;
            sysReentryFadeRemaining = (std::min)(fadeSamples, chunkSamples);
        }
        if (sysReentryFadeRemaining > 0) {
            size_t n = (std::min)(sysReentryFadeRemaining, chunkSamples);
            size_t start = sysReentryFadeTotal - sysReentryFadeRemaining;
            for (size_t i = 0; i < n; ++i) {
                float factor = static_cast<float>(start + i + 1) / static_cast<float>(sysReentryFadeTotal);
                float scaled = static_cast<float>(out[i]) * factor;
                if (scaled > 32767.0f) scaled = 32767.0f; else if (scaled < -32768.0f) scaled = -32768.0f;
                out[i] = static_cast<int16_t>(scaled);
            }
            sysReentryFadeRemaining -= n;
        }
        sysHadDataPrevChunk = sysHasDataThisChunk;
    }

    // 세그먼트 관리자에 샘플 추가 (녹음 모드에서만)
    if (segmentManager && isRecording) {
        segmentManager->AddSamples(out.data(), out.size());
        // log 줄이자
        // LOG_INFO(std::string("Added samples to segment manager: ") + std::to_string(out.size()));
    }
    
    mixSamplesWritten += out.size();
    if (mixStartTimeMs == 0) mixStartTimeMs = GetCurrentTimeMs();
    // 진행 상황 이벤트는 실제 녹음 중일 때만 전송 (pause/테스트/레벨미터 전용 캡쳐에서는 전송하지 않음)
    if (isRecording) {
        SendProgressEvent();
    }
    // 주기적(1초) 드리프트 로그: reverse와 capture 프레임 차이
    {
        auto now = std::chrono::steady_clock::now();
        if (aecLastDriftLog.time_since_epoch().count() == 0) aecLastDriftLog = now;
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - aecLastDriftLog).count();
        if (ms >= 1000) {
            long long drift10ms = static_cast<long long>(aecCaptureFrames10ms) - static_cast<long long>(aecReverseFramesPresent10ms);
            LOG_INFO(std::string("AEC drift monitor: capture_frames_10ms=") + std::to_string(aecCaptureFrames10ms) +
                     ", reverse_frames_10ms=" + std::to_string(aecReverseFramesPresent10ms) +
                     ", drift_10ms=" + std::to_string(drift10ms));
            aecCaptureFrames10ms = 0;
            aecReverseFramesPresent10ms = 0;
            aecLastDriftLog = now;
        }
    }
    // 블록 로그
    // log 줄이자
    // LOG_INFO(std::string("Mix wrote block, samples=") + std::to_string(out.size()) +
    //          ", mix_total=" + std::to_string(mixSamplesWritten) +
    //          ", mic_fifo=" + std::to_string(FifoSize(micFifo16k, micFifoMutex)) +
    //          ", sys_fifo=" + std::to_string(FifoSize(sysFifo16k, sysFifoMutex)) +
    //          ", mic_pushed=" + std::to_string(micPushed16kTotal));

    // 세그먼트 경계에서 중지 처리: 경계가 지나고 currentSegmentSamples==0인 시점에 스톱
    if (stopAtBoundary && !boundaryStopScheduled) {
        // SegmentManager 내부 상태를 보지 못하므로, 샘플 카운트로 근사 경계 검출: 세그먼트 롤오버 직후 AddSamples가 0으로 리셋됨
        // 위에서 AddSamples 호출 직후이므로, totalSamples % segmentDurationSamples == 0 근사 사용
        const uint64_t segmentSamples = (uint64_t)AudioConfig::SAMPLE_RATE * 180; // 기본 3분
        if (segmentSamples > 0 && (totalSamples % segmentSamples) == 0) {
            if (stopDueToLowDisk) {
                LOG_WARN("Low disk boundary reached, stopping");
                StopRecordingAsyncWithDiskLow("DISK_SPACE_LOW_STOP", "디스크 여유 공간 부족으로 안전 중지합니다.");
            } else {
                LOG_INFO("Max duration reached at segment boundary, stopping");
                stopDueToMaxDuration = true;
                drainOnStop = true;
                isRunning = false;
                stopAtBoundary = false;
                boundaryStopScheduled = true;
            }
        }
    }
}

void AudioHelper::ResampleLinearMono(const float* in, size_t inFrames, uint32_t inRate, uint32_t outRate, std::vector<float>& out) {
    if (inFrames == 0) { out.clear(); return; }
    if (inRate == outRate) { out.assign(in, in + inFrames); return; }
    double ratio = static_cast<double>(outRate) / static_cast<double>(inRate);
    size_t outFrames = static_cast<size_t>(std::ceil(inFrames * ratio));
    out.resize(outFrames);
    for (size_t i = 0; i < outFrames; ++i) {
        double srcPos = i / ratio;
        size_t idx = static_cast<size_t>(srcPos);
        double frac = srcPos - static_cast<double>(idx);
        float a = (idx < inFrames) ? in[idx] : in[inFrames - 1];
        float b = (idx + 1 < inFrames) ? in[idx + 1] : in[inFrames - 1];
        out[i] = a + static_cast<float>(frac) * (b - a);
    }
}

void AudioHelper::ResampleLinearMonoStateful(const float* in, size_t inFrames, uint32_t inRate, uint32_t outRate,
                                            std::vector<float>& out, double& phase, float& lastSample, uint32_t& stateInRate) {
    out.clear();
    if (inRate == 0 || outRate == 0) return;
    if (stateInRate != 0 && stateInRate != inRate) {
        // 입력 레이트 변경 시 상태 리셋
        phase = 0.0;
        lastSample = 0.0f;
    }
    stateInRate = inRate;

    const double step = static_cast<double>(inRate) / static_cast<double>(outRate);
    double srcPos = phase; // 입력 프레임 좌표
    // 직전 샘플 확보
    float prev = lastSample;
    out.reserve(static_cast<size_t>(inFrames * (static_cast<double>(outRate) / static_cast<double>(inRate)) + 2));

    for (;;) {
        size_t idx = static_cast<size_t>(srcPos);
        if (idx >= inFrames) break;
        double frac = srcPos - static_cast<double>(idx);
        float a = (idx == 0) ? prev : in[idx];
        float b = (idx + 1 < inFrames) ? in[idx + 1] : in[inFrames - 1];
        float y = a + static_cast<float>(frac) * (b - a);
        out.push_back(y);
        srcPos += step;
    }
    // 상태 업데이트: 다음 콜백 시작 시점의 소수점 위치와 마지막 샘플
    if (inFrames > 0) lastSample = in[inFrames - 1];
    phase = srcPos - static_cast<double>(inFrames);
}

size_t AudioHelper::FifoSize(const std::deque<float>& fifo, std::mutex& mtx) {
    std::lock_guard<std::mutex> lock(mtx);
    return fifo.size();
}

void AudioHelper::FinalizeDebugLengths() {
    // Mic/System 각각 열려있으면 닫기
    if (micDebugOpened) {
        micDebugWriter.close();
        micDebugOpened = false;
    }
    if (sysDebugOpened) {
        sysDebugWriter.close();
        sysDebugOpened = false;
    }
    if (mixDebugOpened) {
        mixDebugWriter.close();
        mixDebugOpened = false;
    }
    mixFilePath.clear();
}

void AudioHelper::Run() {
    std::string line;
    while (true) {
        if (std::getline(std::cin, line)) {
            if (line.empty()) {
                continue;
            }
            try {
                // 원본 명령 보관(간이 파서 보정용)
                static std::string g_lastCommandLine;
                g_lastCommandLine = line;
                json command = SimpleJson::fromString(line);
                ProcessCommand(command);
            } catch (const std::exception& e) {
                SendError("JSON_PARSE_ERROR", std::string("JSON 파싱 오류: ") + e.what());
                LOG_ERROR(std::string("JSON parse error: ") + e.what());
            }
        } else {
            // stdin이 닫힌 경우: 녹음 중이면 감시하며 유지, 아니면 종료
            if (isRunning) {
                Sleep(50);
                continue;
            }
            break;
        }
    }
}

void AudioHelper::StartWatchdogIfNeeded() {
    if (maxDurationMs == 0) return;
    if (watchdogThread.joinable()) return;
    watchdogThread = std::thread([this]() {
        const uint64_t localStart = startTimeMs;
        const uint64_t deadline   = localStart + maxDurationMs;
        LOG_INFO(std::string("Watchdog started: max_ms=") + std::to_string(maxDurationMs) +
                 ", start_ms=" + std::to_string(localStart) + ", deadline_ms=" + std::to_string(deadline));

        while (isRunning) {
            uint64_t now = GetCurrentTimeMs();
            if (now >= deadline) {
                // A안: 즉시 중지 대신 세그먼트 경계에서 안전 정지
                if (!stopAtBoundary) {
                    LOG_INFO("Watchdog timeout reached, will stop at next segment boundary");
                    stopAtBoundary = true;
                }
                // 경계 도달은 MixBlockAndWrite()에서 처리
            }
            Sleep(50);
        }
    });
}

void AudioHelper::HandleGetVersion() {
    try {
        json event;
        event.set("ev", "version_info");
        event.set("version", AUDIOHELPER_VERSION_SHORT);
        event.set("version_full", AUDIOHELPER_VERSION_STRING);
        event.set("product_name", AUDIOHELPER_PRODUCT_NAME);
        event.set("description", AUDIOHELPER_DESCRIPTION);
        event.set("webrtc_aec", AUDIOHELPER_HAS_WEBRTC_AEC ? true : false);
        event.set("noise_suppression", AUDIOHELPER_HAS_NOISE_SUPPRESSION ? true : false);
        event.set("gain_control", AUDIOHELPER_HAS_GAIN_CONTROL ? true : false);
        event.set("build_date", AUDIOHELPER_BUILD_DATE);
        event.set("build_time", AUDIOHELPER_BUILD_TIME);
        event.set("copyright", AUDIOHELPER_COPYRIGHT);
        
        // WebRTC AEC 런타임 상태 정보
#ifdef WEBRTC_APM_AVAILABLE
        event.set("webrtc_available", true);
        if (audioProcessor && audioProcessor->IsInitialized()) {
            event.set("webrtc_initialized", true);
        } else {
            event.set("webrtc_initialized", false);
        }
#else
        event.set("webrtc_available", false);
        event.set("webrtc_initialized", false);
#endif
        
        SendEvent(event);
        LOG_INFO(std::string("Version info sent: ") + AUDIOHELPER_VERSION_SHORT);

        // UI 초기 표시를 위해 디스크 상태를 즉시 1회 전송
        CheckAndEmitDiskStatusIfDue();
    } catch (const std::exception& e) {
        SendError("GET_VERSION_ERROR", e.what());
        LOG_ERROR(std::string("Get version error: ") + e.what());
    }
}

void AudioHelper::HandleSetOutputDir(const json& params) {
    try {
        std::string dirUtf8 = params["directory"];
        if (dirUtf8.empty()) {
            SendError("BAD_PARAM", "directory 파라미터가 비었습니다.");
            return;
        }
        outputDirectory = StringToWString(dirUtf8);
        std::error_code ec; std::filesystem::create_directories(outputDirectory, ec);
        
        // 세그먼트 관리자에도 경로 설정
        if (segmentManager) {
            segmentManager->SetOutputDirectory(dirUtf8);
        }
        
        
        json event; event.set("ev", "output_dir_set"); event.set("directory", std::filesystem::path(outputDirectory).u8string());
        SendEvent(event);
        LOG_INFO(std::string("Output directory set: ") + dirUtf8);

        // 출력 디렉터리 설정 직후 디스크 상태를 즉시 전송
        CheckAndEmitDiskStatusIfDue();
    } catch (const std::exception& e) {
        SendError("SET_OUTPUT_DIR_ERROR", e.what());
        LOG_ERROR(std::string("Set output dir error: ") + e.what());
    }
}

void AudioHelper::HandleSetDebugFiles(const json& params) {
    try {
        std::string enabled = params["enabled"];
        debugRawSaveEnabled = (enabled == "true" || enabled == "1" || enabled == "on");
        json event; event.set("ev", "debug_files_set"); event.set("enabled", debugRawSaveEnabled ? "true" : "false");
        SendEvent(event);
        LOG_INFO(std::string("Debug files enabled: ") + (debugRawSaveEnabled ? "true" : "false"));
    } catch (const std::exception& e) {
        SendError("SET_DEBUG_FILES_ERROR", e.what());
        LOG_ERROR(std::string("Set debug files error: ") + e.what());
    }
}

void AudioHelper::HandleSetSegmentConfig(const json& params) {
    try {
        if (segmentManager) {
            // 암호화 설정
            if (params.contains("encryption_enabled")) {
                std::string enabled = params["encryption_enabled"];
                bool encryptionEnabled = (enabled == "true" || enabled == "1" || enabled == "on");
                segmentManager->SetEncryptionEnabled(encryptionEnabled);
                LOG_INFO(std::string("Segment encryption enabled: ") + (encryptionEnabled ? "true" : "false"));
            }
            // 세그먼트 길이(초) 설정
            if (params.contains("segment_seconds")) {
                std::string secStr = params["segment_seconds"];
                uint32_t seconds = 0;
                try { seconds = static_cast<uint32_t>(std::stoul(secStr)); } catch (...) { seconds = 180; }
                if (seconds == 0) seconds = 180;
                segmentManager->SetSegmentDurationSeconds(seconds);
                LOG_INFO(std::string("Segment duration seconds set: ") + std::to_string(seconds));
            }
            
            // 출력 디렉터리 설정 (이미 설정되어 있으면 세그먼트 관리자에도 적용)
            if (!outputDirectory.empty()) {
                segmentManager->SetOutputDirectory(WStringToString(outputDirectory));
            }
        }
        
        json event;
        event.set("ev", "segment_config_set");
        if (params.contains("encryption_enabled")) {
            event.set("encryption_enabled", params["encryption_enabled"]);
        }
        if (params.contains("segment_seconds")) {
            event.set("segment_seconds", params["segment_seconds"]);
        }
        // Include current disk status in the response
        try {
            uint64_t freeBytes = 0;
            std::string status = "unknown";
            if (QueryFreeBytes(freeBytes)) {
                if (freeBytes >= DISK_STATUS_OK) {
                    status = "ok";
                } else if (freeBytes >= DISK_STATUS_LOW) {
                    status = "low";
                } else {
                    status = "critical";
                }
            }
            event.set("disk_status", status);
            event.set("free_bytes", freeBytes);
        } catch (...) {
            event.set("disk_status", "unknown");
            event.set("free_bytes", static_cast<uint64_t>(0));
        }
        SendEvent(event);
        LOG_INFO("Segment configuration updated");
        
    } catch (const std::exception& e) {
        SendError("SET_SEGMENT_CONFIG_ERROR", e.what());
        LOG_ERROR(std::string("Set segment config error: ") + e.what());
    }
}

void AudioHelper::HandleSetMute(const json& params) {
    try {
        // 파라미터: target = "mic" | "system" | "both", value = "on"|"off"|"true"|"false"|"1"|"0"
        std::string target = "both";
        if (params.contains("target")) {
            target = std::string(params["target"]);
        }
        bool value = false;
        if (params.contains("value")) {
            std::string s = std::string(params["value"]);
            value = (s == "on" || s == "true" || s == "1");
        }

        if (target == "mic") {
            muteMic.store(value);
        } else if (target == "system") {
            muteSystem.store(value);
        } else {
            muteMic.store(value);
            muteSystem.store(value);
        }

        json ev; ev.set("ev", "mute_state");
        ev.set("mic", muteMic.load());
        ev.set("system", muteSystem.load());
        SendEvent(ev);

        LOG_INFO(std::string("Mute updated: mic=") + (muteMic.load()?"true":"false") +
                 ", system=" + (muteSystem.load()?"true":"false"));
    } catch (const std::exception& e) {
        SendError("SET_MUTE_ERROR", e.what());
        LOG_ERROR(std::string("Set mute error: ") + e.what());
    }
}

void AudioHelper::HandleSetLevelMeter(const json& params) {
    try {
        bool enable = true;
        if (params.contains("enabled")) {
            std::string s = std::string(params["enabled"]);
            enable = (s == "on" || s == "true" || s == "1");
        }
        levelMeterEnabled.store(enable);

        // 레벨미터 on: 캡쳐가 꺼져 있으면 테스트와 유사하게 캡쳐만 시작(파일 저장 없음)
        if (enable && !isRunning) {
            // 현재 설정된 모드로 캡쳐 시작(디바이스는 기존 선택 사용)
            json startParams; 
            std::string lmMode = "MicOnly";
            if (currentMode == CaptureMode::MicPlusSystem) lmMode = "MicPlusSystem";
            else if (currentMode == CaptureMode::SystemOnly) lmMode = "SystemOnly";
            startParams.set("mode", lmMode);
            // 선택 마이크가 없거나 ACTIVE가 아니면 시작하지 않음
            if (HasSelectedMic() && IsMicDeviceActive(selectedMicId)) {
                startParams.set("mic", WStringToString(selectedMicId));
                HandleStartTest(startParams);
            } else {
                LOG_WARN("Level meter enable skipped: selected mic missing or inactive");
                SendMicStateEvent("unavailable");
            }
            isTestMode = false; // 파일 저장 금지 유지(테스트 모드 동작이지만 표시는 끔)
            startedByLevelMeter.store(true);
        }
        // 레벨미터 off: 레벨미터가 켠 상태로만 시작된 캡쳐라면 중지
        if (!enable && isRunning && startedByLevelMeter.load() && !isRecording) {
            HandleStopTest();
            startedByLevelMeter.store(false);
        }
        json ev; ev.set("ev", "level_meter_state"); ev.set("enabled", enable);
        SendEvent(ev);
        LOG_INFO(std::string("Level meter ") + (enable ? "enabled" : "disabled"));
    } catch (const std::exception& e) {
        SendError("SET_LEVEL_METER_ERROR", e.what());
        LOG_ERROR(std::string("Set level meter error: ") + e.what());
    }
}

void AudioHelper::StartLevelMeterCaptureIfNeeded() {
    try {
        if (!levelMeterEnabled.load() || isRunning) return;
        // 선택 마이크가 없거나 ACTIVE가 아니면 레벨미터 시작 금지
        if (!HasSelectedMic() || !IsMicDeviceActive(selectedMicId)) {
            LOG_WARN("Level meter skipped: selected mic missing or inactive");
            SendMicStateEvent("unavailable");
            return;
        }
        json startParams; 
        std::string lmMode = "MicOnly";
        if (currentMode == CaptureMode::MicPlusSystem) lmMode = "MicPlusSystem";
        else if (currentMode == CaptureMode::SystemOnly) lmMode = "SystemOnly";
        startParams.set("mode", lmMode);
        startParams.set("mic", WStringToString(selectedMicId));
        startParams.set("_auto", true);
        HandleStartTest(startParams);
        if (isRunning) {
            isTestMode = false;
            startedByLevelMeter.store(true);
            LOG_INFO("Level meter capture started (no recording)");
        } else {
            LOG_WARN("Level meter capture start skipped (init failed)");
        }
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("Failed to start level meter capture: ") + e.what());
    }
}

bool AudioHelper::IsSameDeviceId(const std::wstring& a, const std::wstring& b) {
    if (a.empty() && b.empty()) return true;
    return a == b;
}

void AudioHelper::HandleReinitAudio(const json& params) {
    try {
        // 요청 장치 파싱 (default → empty id)
        std::wstring reqMicId; std::wstring reqRenderId;
        if (params.contains("mic")) { std::string mic = params["mic"]; if (mic != "default") reqMicId = StringToWString(mic); }
        if (params.contains("render")) { std::string rd = params["render"]; if (rd != "default") reqRenderId = StringToWString(rd); }

        LOG_INFO("Audio reinit requested");

        // 모드 설정(요청이 있으면 반영)
        if (params.contains("mode")) {
            std::string modeStr = params["mode"];
            if (modeStr == "MicOnly") currentMode = CaptureMode::MicOnly;
            else if (modeStr == "MicPlusSystem") currentMode = CaptureMode::MicPlusSystem;
            else if (modeStr == "SystemOnly") currentMode = CaptureMode::SystemOnly;
        }

        // 안전 정지
        isRecording.store(false, std::memory_order_release);
        std::atomic_thread_fence(std::memory_order_seq_cst);
        isRunning.store(false, std::memory_order_release);
        drainOnStop.store(false, std::memory_order_release);

        // 스레드 종료 대기 및 클라이언트 정리 (HandleStopTest 유사)
        if (micThread.joinable()) micThread.join();
        if (sysThread.joinable()) sysThread.join();
        if (mixThread.joinable()) mixThread.join();
        if (watchdogThread.joinable()) {
            if (std::this_thread::get_id() != watchdogThread.get_id()) {
                watchdogThread.join();
            }
        }
        if (pMicClient) pMicClient->Stop();
        if (pSysClient) pSysClient->Stop();
        FinalizeDebugLengths();
        maxDurationMs = 0;

        // COM 객체 해제
        if (pMicCaptureClient) { pMicCaptureClient->Release(); pMicCaptureClient = nullptr; }
        if (pSysCaptureClient) { pSysCaptureClient->Release(); pSysCaptureClient = nullptr; }
        if (pMicClient) { pMicClient->Release(); pMicClient = nullptr; }
        if (pSysClient) { pSysClient->Release(); pSysClient = nullptr; }
        if (pMicDevice) { pMicDevice->Release(); pMicDevice = nullptr; }
        if (pSysDevice) { pSysDevice->Release(); pSysDevice = nullptr; }

        // 디바이스 바인딩 (기본 마이크 추종 금지)
        std::wstring bindMicId = reqMicId;
        if (bindMicId.empty()) {
            bindMicId = !sessionMicId.empty() ? sessionMicId : selectedMicId;
        }
        if (!bindMicId.empty()) {
            GetDeviceById(bindMicId, &pMicDevice);
        }
        if (!pMicDevice || !IsMicDeviceActive(bindMicId)) {
            LOG_ERROR("Mic reinit failed or inactive (no default fallback allowed)");
            SendError("NO_MIC_DEVICE", "선택된 마이크가 감지되지 않거나 사용 불가 상태입니다.");
            return;
        }
        {
            LPWSTR pid = nullptr; if (SUCCEEDED(pMicDevice->GetId(&pid)) && pid) { currentMicDeviceId = pid; CoTaskMemFree(pid); }
        }

        if (reqRenderId.empty()) {
            GetDefaultDevice(eRender, &pSysDevice);
        } else {
            GetDeviceById(reqRenderId, &pSysDevice);
        }
        if (pSysDevice) {
            LPWSTR pid = nullptr; if (SUCCEEDED(pSysDevice->GetId(&pid)) && pid) { currentSysDeviceId = pid; CoTaskMemFree(pid); }
        }

        // 상태 리셋
        silenceDetected = false;
        sustainedEventSent = false;
        silenceStartMs = 0;
        totalSamples = 0;
        micPushed16kTotal = 0;
        stopAtBoundary = false;
        isPaused = false;
        {
            std::lock_guard<std::mutex> lk(micFifoMutex); micFifo16k.clear();
        }
        {
            std::lock_guard<std::mutex> lk(sysFifoMutex); sysFifo16k.clear();
        }
        micResamplePhase = 0.0; micResampleLast = 0.0f; micResampleInRate = 0;
        sysResamplePhase = 0.0; sysResampleLast = 0.0f; sysResampleInRate = 0;
        aecRefDelayLine.clear(); aecMicHPHist.clear(); aecSysHPHist.clear();

        // 파이프라인 재초기화
        HRESULT hr = InitializeAudioClient(pMicDevice, &pMicClient, &pMicCaptureClient);
        if (FAILED(hr)) { 
            if (!stoppingDueToMicRemoval.load() && !stopErrorSent.load()) {
                SendError("MIC_INIT_FAILED", "마이크 초기화 실패");
            } else {
                LOG_WARN("MIC_INIT_FAILED suppressed (stopping due to mic removal)");
            }
            LOG_ERROR("Mic init failed in reinit");
            return; 
        }
        if (pSysDevice) {
            hr = InitializeAudioClient(pSysDevice, &pSysClient, &pSysCaptureClient, true);
            if (FAILED(hr)) { LOG_WARN("System init failed in reinit"); SendError("SYS_INIT_FAILED", "시스템 오디오 초기화 실패"); }
        }
        InitializeAudioProcessing(AudioConfig::SAMPLE_RATE, AudioConfig::CHANNELS);

        // 시작
        if (pMicClient) pMicClient->Start();
        if (pSysClient) pSysClient->Start();
        isRunning.store(true, std::memory_order_release);
        micThread = std::thread(&AudioHelper::MicrophoneCaptureThread, this);
        if (currentMode != CaptureMode::MicOnly && pSysClient) {
            sysThread = std::thread(&AudioHelper::SystemCaptureThread, this);
        }
        mixThread = std::thread(&AudioHelper::MixingThread, this);

        json ev; ev.set("ev", "audio_reinited");
        ev.set("mic", (!bindMicId.empty()? WStringToString(bindMicId) : ""));
        ev.set("render", reqRenderId.empty()?"default":WStringToString(reqRenderId));
        SendEvent(ev);
        LOG_INFO("Audio reinit done");
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("Reinit failed: ") + e.what());
        SendError("REINIT_FAILED", e.what());
    }
}