//
//  AudioHelperController.swift
//  AudioHelper
//
//  Created by 장준호 on 10/23/25.
//

import Foundation
import AVFoundation
import ScreenCaptureKit
import CoreMedia
import os
import CryptoSwift

@available(macOS 15.0, *)
final class AudioHelperController: NSObject {
    // Output
    private var outputBaseDirURL: URL?
    private var debugRawEnabled: Bool = false
    private var encryptionEnabled: Bool = false // true: .pcm (암호화), false: .raw (평문)
    private var levelMeterEnabled: Bool = true
    private var startedByLevelMeter: Bool = false
    private var startedByTest: Bool = false
    private var currentTestMode: String?
    private var currentMode: String = "MicPlusSystem"  // 전역 모드 추적 (C++ Helper와 동일)
    private var selectedMicId: String?                  // UI가 선택한 영구 마이크 ID
    private var sessionMicId: String?                   // 현재 세션에서 사용 중인 마이크 ID
    private var lastMicLevelEmitMs: UInt64 = 0
    private var lastSysLevelEmitMs: UInt64 = 0
    private var isRecording: Bool = false
    private var muteMic: Bool = false
    private var muteSystem: Bool = false

    // Segmentation (버퍼링 방식)
    private var segmentManager: SegmentManager?
    private let MAX_SEGMENTS: Int = 60             // up to 3 hours
    private var sessionId: String = ""
    private var outputDirURL: URL?
    private var fileExtension: String = ".raw"
    private var runtimeSampleRate: Int = 16000
    private var runtimeChannels: Int = 1  // 강제 모노 (시스템+마이크 믹싱)
    private var totalFramesWritten: UInt64 = 0
    private var totalMicFramesCaptured: UInt64 = 0
    private var lastProgressEmitMs: UInt64 = 0
    
    // Recording duration limit (Windows Helper와 동일)
    private var maxDurationMs: UInt64 = 0          // 0 = unlimited
    private var startTimeMs: UInt64 = 0
    private var stopAtBoundary: Bool = false       // 워치독이 세그먼트 경계에서 정지 요청
    private var watchdogTimer: DispatchSourceTimer?

    // Disk status
    private var lastDiskStatus: String? = nil
    private var lastDiskEmitMs: UInt64 = 0
    private var diskTimerSource: DispatchSourceTimer?
    private let OK_THRESHOLD_BYTES: Int64 = 500 * 1024 * 1024
    private let LOW_THRESHOLD_BYTES: Int64 = 50 * 1024 * 1024

    // Silence detection
    private var silenceActive: Bool = false
    private var silenceStartMs: UInt64 = 0
    private var lastEarlyIndex: Int = 0 // 0..4 for 7,14,21,28 sec
    private var sustainedSent: Bool = false
    private let SILENCE_RMS_THRESHOLD: Double = 0.02
    private var silenceCandidateStartMs: UInt64 = 0  // 연속 무음 진입 후보 시작 시각
    private var soundCandidateStartMs: UInt64 = 0    // 연속 유음 해제 후보 시작 시각
    private let MIN_SILENCE_ENTER_MS: UInt64 = 1000  // 무음 진입 확정 최소 지속 시간
    private let MIN_SOUND_EXIT_MS: UInt64 = 300      // 무음 해제 확정 최소 지속 시간
    private var silenceDetectionDisabled: Bool = false // off/sustained 후 감지 비활성화
    private var lastMicRms: Double = 0.0
    private var lastSysRms: Double = 0.0

    // Capture
    private var stream: SCStream?
    private let audioQueue = DispatchQueue(label: "audio.stream.queue")
    private var audioEngine: AVAudioEngine?
    private var micDeviceId: String?
    private var captureSession: AVCaptureSession?
    private var captureAudioOutput: AVCaptureAudioDataOutput?
    private let micOutputQueue = DispatchQueue(label: "mic.capture.queue")
    private var deviceDisconnectObserver: NSObjectProtocol?
    private var deviceConnectObserver: NSObjectProtocol?
    private var sessionErrorObserver: NSObjectProtocol?
    private var reconnectTimer: Timer?
    private var reconnectTimerSource: DispatchSourceTimer?
    private var reconnectAttempts: Int = 0
    
    // Capture running state (C++ Helper와 동일)
    private var isRunning: Bool {
        return stream != nil && captureSession != nil
    }

    // Mix state
    private var isPaused = false
    private var sysBufferF32: [Float] = []   // system mono Float32 samples
    private var micBufferF32: [Float] = []   // mic mono Float32 samples
    private let framesPerChunk: Int = 2048   // processing quantum
    private var micConverter: AVAudioConverter?
    private var micDstFormat: AVAudioFormat?

    func postEvent(_ ev: Event) {
        print(ev.jsonString())
        fflush(stdout)
        FileLogger.shared.log(.debug, category: "event", message: ev.jsonString())
    }
    
    /// SegmentManager가 MAX_SEGMENTS 도달 시 호출 (internal access for SegmentManager)
    func requestStopAtBoundary() {
        stopAtBoundary = true
    }

    // MARK: - Command handling
    func handle(_ cmd: Command) async {
        switch cmd.cmd {
        case "get_version":
            do {
                FileLogger.shared.log(.info, category: "cmd", message: "get_version")
                
                // Bundle에서 버전 정보 읽기
                let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0"
                let buildNumber = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
                let versionFull = "\(version).\(buildNumber)"
                
                // 빌드 날짜/시간 생성
                let df = DateFormatter()
                df.locale = Locale(identifier: "en_US_POSIX")
                df.dateFormat = "MMM dd yyyy"
                let buildDate = df.string(from: Date())
                df.dateFormat = "HH:mm:ss"
                let buildTime = df.string(from: Date())
                
                postEvent(.versionInfo(
                    version: version,
                    version_full: versionFull,
                    product_name: "AudioHelper",
                    description: "macOS audio capture helper",
                    webrtc_aec: false,
                    noise_suppression: false,
                    gain_control: false,
                    build_date: buildDate,
                    build_time: buildTime,
                    copyright: "Copyright (C) 2025"
                ))
            } catch {
                postEvent(.errorCode(code: "GET_VERSION_ERROR", 
                                    message: "버전 정보를 조회할 수 없습니다: \(error.localizedDescription)"))
                FileLogger.shared.log(.error, category: "cmd", message: "get_version failed: \(error)")
            }
        case "set_output_dir":
            FileLogger.shared.log(.info, category: "cmd", message: "set_output_dir", metadata: ["dir": cmd.directory ?? cmd.outputDir ?? ""])
            
            guard let dir = cmd.directory ?? cmd.outputDir, !dir.isEmpty else {
                postEvent(.errorCode(code: "SET_OUTPUT_DIR_ERROR", 
                                    message: "출력 디렉터리 경로가 지정되지 않았습니다."))
                FileLogger.shared.log(.warn, category: "cmd", message: "set_output_dir missing")
                break
            }
            
            do {
                let expanded = (dir as NSString).expandingTildeInPath
                let baseURL = URL(fileURLWithPath: expanded).standardizedFileURL
                
                // Bundle 내부 경로 체크
                guard !baseURL.path.hasPrefix(Bundle.main.bundlePath) else {
                    postEvent(.errorCode(code: "SET_OUTPUT_DIR_ERROR", 
                                        message: "앱 번들 내부에는 디렉터리를 생성할 수 없습니다."))
                    FileLogger.shared.log(.warn, category: "path", 
                                        message: "reject set_output_dir inside bundle", 
                                        metadata: ["path": baseURL.path])
                    break
                }
                
                // 디렉터리 생성
                try FileManager.default.createDirectory(at: baseURL, 
                                                       withIntermediateDirectories: true)
                outputBaseDirURL = baseURL
                postEvent(.outputDirSet(directory: baseURL.path))
                FileLogger.shared.log(.info, category: "path", 
                                    message: "outputDir set", 
                                    metadata: ["path": baseURL.path])
                
                // Emit one-time disk status right after setting output dir
                emitDiskStatusOnce(for: baseURL)
                
            } catch {
                postEvent(.errorCode(code: "SET_OUTPUT_DIR_ERROR", 
                                    message: "출력 디렉터리를 생성할 수 없습니다: \(error.localizedDescription)"))
                FileLogger.shared.log(.error, category: "path", 
                                    message: "set_output_dir failed: \(error)")
            }
        case "set_debug_files":
            // Note: SET_DEBUG_FILES_ERROR는 인터페이스 명세에 정의되어 있으나,
            // 현재 Swift/macOS 구현에서는 실제로 에러가 발생하지 않음 (non-throwing)
            let raw = (cmd.enabledAny?.raw ?? "false").lowercased()
            let on = (raw == "true" || raw == "1" || raw == "on")
            debugRawEnabled = on
            FileLogger.shared.setLevel(on ? .debug : .info)
            postEvent(.debugFilesSet(enabled: on ? "true" : "false"))
            FileLogger.shared.log(.info, category: "cmd", 
                                message: "debug_files set", 
                                metadata: ["enabled": on])
        case "set_segment_config":
            do {
                FileLogger.shared.log(.info, category: "cmd", message: "set_segment_config")
                let encRaw = (cmd.encryptionEnabled ?? "false").lowercased()
                encryptionEnabled = (encRaw == "true" || encRaw == "1" || encRaw == "on")
                let segSeconds = cmd.segmentSeconds ?? "180"
                // 세그먼트 길이는 3분 고정 유지 (적용하지 않음)
                let (status, freeBytes) = currentDiskStatus()
                postEvent(.segmentConfigSet(encryptionEnabled: encryptionEnabled ? "true" : "false",
                                            segmentSeconds: segSeconds,
                                            diskStatus: status,
                                            freeBytes: freeBytes))
                FileLogger.shared.log(.info, category: "cmd", 
                                    message: "segment_config set", 
                                    metadata: ["encrypted": encryptionEnabled])
            } catch {
                postEvent(.errorCode(code: "SET_SEGMENT_CONFIG_ERROR", 
                                    message: "세그먼트 설정을 변경할 수 없습니다: \(error.localizedDescription)"))
                FileLogger.shared.log(.error, category: "cmd", message: "set_segment_config failed: \(error)")
            }
        case "start":
            // 파라미터 검증
            let sr = cmd.sampleRate ?? cmd.out?.sr ?? 16000
            let ch = cmd.channels ?? cmd.out?.ch ?? 1
            
            // SampleRate 검증 (8kHz ~ 96kHz)
            guard sr >= 8000 && sr <= 96000 else {
                postEvent(.errorCode(code: "BAD_PARAM", 
                                    message: "잘못된 샘플레이트입니다: \(sr) (범위: 8000-96000Hz)"))
                FileLogger.shared.log(.warn, category: "cmd", 
                                    message: "invalid sampleRate", 
                                    metadata: ["sr": sr])
                break
            }
            
            // Channels 검증 (1 또는 2만 지원)
            guard ch == 1 || ch == 2 else {
                postEvent(.errorCode(code: "BAD_PARAM", 
                                    message: "잘못된 채널 수입니다: \(ch) (1 또는 2만 지원)"))
                FileLogger.shared.log(.warn, category: "cmd", 
                                    message: "invalid channels", 
                                    metadata: ["ch": ch])
                break
            }
            
            FileLogger.shared.log(.info, category: "cmd", message: "start", metadata: [
                "sr": sr,
                "ch": ch,
                "mic": cmd.mic ?? cmd.micDeviceId ?? "",
                "encrypted": encryptionEnabled
            ])
            
            // 확장자 결정: encryptionEnabled(true→.pcm, false→.raw)
            let micId = cmd.mic ?? cmd.micDeviceId
            if !isMicAvailable(for: micId) {
                postEvent(.micState(state: "unavailable"))
                postEvent(.errorCode(code: "NO_MIC_DEVICE", message: "Selected mic is not available"))
                break
            }
            await start(sessionId: cmd.sessionId,
                        outputDir: cmd.outputDir,
                        sr: sr,
                        ch: ch,
                        micDeviceId: micId,
                        maxMs: cmd.maxMs,
                        segmentingConfig: cmd.segmenting)
        case "list_devices":
            listAudioDevices()
        case "pause": pause()
        case "resume": resume()
        case "stop": await stop()
        case "status": postEvent(.status(paused: isPaused))
        case "start_test":
            // Mode 검증
            if let mode = cmd.mode {
                let validModes = ["MicPlusSystem", "MicOnly", "SystemOnly"]
                guard validModes.contains(mode) else {
                    postEvent(.errorCode(code: "BAD_PARAM", 
                                        message: "잘못된 모드입니다: \(mode) (지원: \(validModes.joined(separator: ", ")))"))
                    FileLogger.shared.log(.warn, category: "cmd", 
                                        message: "invalid mode", 
                                        metadata: ["mode": mode])
                    break
                }
            }
            
            FileLogger.shared.log(.info, category: "cmd", message: "start_test", metadata: ["mode": cmd.mode ?? ""]) 
            let wantMic = cmd.mic ?? cmd.micDeviceId
            if !isMicAvailable(for: wantMic) {
                postEvent(.micState(state: "unavailable"))
                postEvent(.errorCode(code: "NO_MIC_DEVICE", message: "Selected mic is not available"))
                break
            }
            await startTest(mode: cmd.mode, micId: wantMic)
        case "stop_test":
            FileLogger.shared.log(.info, category: "cmd", message: "stop_test")
            await stopTest()
        case "set_level_meter":
            do {
                let enabledStr = (cmd.enabledAny?.raw ?? "true").lowercased()
                let enabled = (enabledStr == "true" || enabledStr == "1" || enabledStr == "on")
                levelMeterEnabled = enabled
                postEvent(.levelMeterState(enabled: enabled))
                
                if enabled {
                    // 캡쳐 파이프라인 보장 (파일 기록 없이)
                    if !isMicAvailable(for: selectedMicId ?? micDeviceId) {
                        postEvent(.micState(state: "unavailable"))
                    } else {
                        // currentMode 사용하여 캡처 보장 (재사용 가능하도록)
                        await ensureCaptureForLevelMeter(mode: currentMode)
                    }
                } else {
                    // 0 RMS 1회 전송
                    let now = uptimeMs()
                    postEvent(.level(source: "mic", rms: 0.0, t: now))
                    postEvent(.level(source: "system", rms: 0.0, t: now))
                    // 레벨미터로 시작한 캡쳐는 종료 (녹음 중이 아닐 때만)
                    if startedByLevelMeter && !isRecording {
                        await stopCaptureOnly()
                        startedByLevelMeter = false
                    }
                }
                
                FileLogger.shared.log(.info, category: "cmd", 
                                    message: "level_meter set", 
                                    metadata: ["enabled": enabled])
            } catch {
                postEvent(.errorCode(code: "SET_LEVEL_METER_ERROR", 
                                    message: "레벨미터 설정을 변경할 수 없습니다: \(error.localizedDescription)"))
                FileLogger.shared.log(.error, category: "cmd", message: "set_level_meter failed: \(error)")
            }
        case "set_mute":
            do {
                let tgt = (cmd.target ?? "").lowercased()
                let vraw = (cmd.valueAny?.raw ?? "").lowercased()
                let on = (vraw == "true" || vraw == "1" || vraw == "on")
                
                guard !tgt.isEmpty else {
                    postEvent(.errorCode(code: "SET_MUTE_ERROR", 
                                        message: "음소거 대상이 지정되지 않았습니다."))
                    FileLogger.shared.log(.warn, category: "cmd", message: "set_mute: empty target")
                    break
                }
                
                switch tgt {
                case "mic":
                    muteMic = on
                case "system":
                    muteSystem = on
                case "both", "all":
                    muteMic = on
                    muteSystem = on
                default:
                    postEvent(.errorCode(code: "SET_MUTE_ERROR", 
                                        message: "잘못된 음소거 대상입니다: \(tgt)"))
                    FileLogger.shared.log(.warn, category: "cmd", 
                                        message: "set_mute: invalid target", 
                                        metadata: ["target": tgt])
                    break
                }
                
                postEvent(.muteState(mic: muteMic, system: muteSystem))
                FileLogger.shared.log(.info, category: "cmd", 
                                    message: "mute set", 
                                    metadata: ["target": tgt, "value": on])
            } catch {
                postEvent(.errorCode(code: "SET_MUTE_ERROR", 
                                    message: "음소거 설정을 변경할 수 없습니다: \(error.localizedDescription)"))
                FileLogger.shared.log(.error, category: "cmd", message: "set_mute failed: \(error)")
            }
        
        // NOT_IMPLEMENTED: 미구현 기능 처리 예시
        // 향후 WebRTC AEC, Noise Suppression, Gain Control 등의 명령이 추가될 경우:
        // case "enable_aec", "enable_noise_suppression", "enable_gain_control":
        //     postEvent(.errorCode(code: "NOT_IMPLEMENTED", 
        //                         message: "이 기능은 macOS에서 아직 구현되지 않았습니다: \(cmd.cmd)"))
        //     FileLogger.shared.log(.warn, category: "cmd", 
        //                         message: "not_implemented", 
        //                         metadata: ["cmd": cmd.cmd])
        
        default: postEvent(.errorCode(code: "UNKNOWN_COMMAND", message: cmd.cmd))
            FileLogger.shared.log(.warn, category: "cmd", message: "unknown_cmd", metadata: ["cmd": cmd.cmd])
        }
    }

    // MARK: - Device enumeration
    private func listAudioDevices() {
        // Note: ENUMERATOR_FAILED는 인터페이스 명세에 정의되어 있으나,
        // AVCaptureDevice.DiscoverySession은 throwing initializer가 아니며,
        // 장치 열거 실패 시 빈 배열을 반환하므로 실제로 에러가 발생하지 않음
        var result: [DeviceInfo] = []
        let session = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external], mediaType: .audio, position: .unspecified)
        let devices = session.devices
        let defaultDevice = AVCaptureDevice.default(for: .audio)
        for d in devices {
            let info = DeviceInfo(id: d.uniqueID, name: d.localizedName, isDefault: (d.uniqueID == defaultDevice?.uniqueID))
            result.append(info)
        }
        postEvent(.devices(result))
        FileLogger.shared.log(.info, category: "device", message: "device enumeration success", metadata: ["count": devices.count])
    }

    // MARK: - Start capture (macOS 15+ : SCStream(system) + AVAudioEngine(mic))
    @MainActor
    private func start(sessionId: String?, outputDir: String?, sr: Int, ch: Int, micDeviceId: String?, maxMs: String?, segmentingConfig: SegmentingConfig?) async {
        do {
            // Initialize session and output directory
            self.sessionId = sessionId ?? UUID().uuidString
            self.runtimeSampleRate = sr
            self.runtimeChannels = 1  // 강제 모노 (ch 파라미터 무시)
            self.fileExtension = encryptionEnabled ? ".pcm" : ".raw"
            
            // 모드 및 마이크 ID 추적 (C++ Helper와 동일)
            self.currentMode = "MicPlusSystem"  // 현재는 MicPlusSystem 고정
            self.sessionMicId = micDeviceId
            self.micDeviceId = micDeviceId
            
            // 우선순위: start.outputDir > set_output_dir(base)/sessionId
            let dirURL: URL
            if let outDirPath = outputDir, !outDirPath.isEmpty {
                let expanded = (outDirPath as NSString).expandingTildeInPath
                dirURL = URL(fileURLWithPath: expanded).standardizedFileURL
            } else if let base = outputBaseDirURL {
                dirURL = base.appendingPathComponent(self.sessionId)
            } else {
                throw NSError(domain: "path", code: -1002, userInfo: [NSLocalizedDescriptionKey: "outputDir required"])
            }
            // Preflight disk check
            let free = bytesAvailable(at: dirURL) ?? 0
            if free < LOW_THRESHOLD_BYTES { // <50MB critical → reject start
                postEvent(.errorCode(code: "DISK_SPACE_CRITICAL", message: "디스크 여유 공간이 50MB 미만이어서 녹음을 시작할 수 없습니다."))
                return
            }
            try FileManager.default.createDirectory(at: dirURL, withIntermediateDirectories: true)
            self.outputDirURL = dirURL
            self.totalFramesWritten = 0
            self.totalMicFramesCaptured = 0
            self.lastProgressEmitMs = 0
            // 녹음 시작 전 버퍼 완전 초기화 (test/레벨미터에서 쌓인 데이터 제거)
            audioQueue.sync {
                self.sysBufferF32.removeAll(keepingCapacity: true)
                self.micBufferF32.removeAll(keepingCapacity: true)
            }
            
            // max_ms 파싱 (Windows Helper와 동일)
            self.maxDurationMs = 0
            if let msStr = maxMs, !msStr.isEmpty {
                if let parsed = UInt64(msStr), parsed > 0 {
                    self.maxDurationMs = parsed
                }
            }
            
            // 녹음 시작 시각 기록
            self.startTimeMs = uptimeMs()
            self.stopAtBoundary = false
            
            // 세그먼트 길이 결정: segmentingConfig.duration_ms 우선, 없으면 기본값 3분
            let segmentDurationMs: UInt64
            if let durationMs = segmentingConfig?.duration_ms, durationMs > 0 {
                segmentDurationMs = UInt64(durationMs)
                FileLogger.shared.log(.info, category: "recording", 
                                    message: "Custom segment duration", 
                                    metadata: ["duration_ms": durationMs])
            } else {
                segmentDurationMs = 180_000  // 기본값: 3분 (180,000ms)
                FileLogger.shared.log(.info, category: "recording", 
                                    message: "Default segment duration", 
                                    metadata: ["duration_ms": segmentDurationMs])
            }
            
            let segmentDurationSeconds = Int(segmentDurationMs / 1000)
            
            // max_ms와 duration_ms 기반 MAX_SEGMENTS 계산
            let dynamicMaxSegments: Int
            if maxDurationMs > 0 {
                // max_ms가 설정된 경우: max_ms ÷ duration_ms (올림)
                dynamicMaxSegments = Int(ceil(Double(maxDurationMs) / Double(segmentDurationMs)))
                
                FileLogger.shared.log(.info, category: "recording", 
                                    message: "MAX_SEGMENTS calculated", 
                                    metadata: [
                                        "max_ms": maxDurationMs,
                                        "segment_duration_ms": segmentDurationMs,
                                        "max_segments": dynamicMaxSegments
                                    ])
                
                // 경고: max_ms < segment_duration_ms인 경우
                if maxDurationMs < segmentDurationMs {
                    FileLogger.shared.log(.warn, category: "recording", 
                                        message: "max_ms is less than segment duration, will stop at first segment", 
                                        metadata: [
                                            "max_ms": maxDurationMs,
                                            "segment_duration_ms": segmentDurationMs,
                                            "actual_stop_time_ms": segmentDurationMs
                                        ])
                }
            } else {
                // max_ms=0 (무제한): 3시간 기준으로 MAX_SEGMENTS 계산
                let defaultMaxDurationMs: UInt64 = 10_800_000  // 3시간
                dynamicMaxSegments = Int(ceil(Double(defaultMaxDurationMs) / Double(segmentDurationMs)))
                
                FileLogger.shared.log(.info, category: "recording", 
                                    message: "MAX_SEGMENTS calculated (unlimited mode, 3hr base)", 
                                    metadata: [
                                        "base_duration_ms": defaultMaxDurationMs,
                                        "segment_duration_ms": segmentDurationMs,
                                        "max_segments": dynamicMaxSegments
                                    ])
            }
            
            // SegmentManager 초기화
            let segMgr = SegmentManager(controller: self, 
                                        sampleRate: sr, 
                                        channels: 1,
                                        segmentDurationSeconds: segmentDurationSeconds)  // 동적 값 전달
            segMgr.setOutputDirectory(dirURL)
            segMgr.setSessionId(self.sessionId)
            segMgr.setEncryptionEnabled(encryptionEnabled)
            segMgr.setFileExtension(self.fileExtension)
            segMgr.setMaxSegments(dynamicMaxSegments)  // 동적으로 계산된 값 설정
            self.segmentManager = segMgr
            
            self.isRecording = true
            startDiskPolling()
            startWatchdogIfNeeded()  // 워치독 타이머 시작
            
            FileLogger.shared.log(.info, category: "recording", message: "recording started with buffering", metadata: ["sessionId": self.sessionId, "sampleRate": sr, "encrypted": encryptionEnabled])

            // 2) ScreenCaptureKit 구성 (시스템 오디오만)
            let content: SCShareableContent
            do {
                content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            } catch {
                FileLogger.shared.log(.error, category: "system", message: "시스템 콘텐츠 가져오기 실패: \(error)")
                postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "시스템 오디오 콘텐츠를 가져올 수 없습니다: \(error.localizedDescription)"))
                throw error
            }
            
            guard let display = content.displays.first else {
                let error = NSError(domain: "sc", code: -10, userInfo: [NSLocalizedDescriptionKey: "no display found"])
                FileLogger.shared.log(.error, category: "system", message: "사용 가능한 디스플레이 없음")
                postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "사용 가능한 디스플레이를 찾을 수 없습니다."))
                throw error
            }
            let filter = SCContentFilter(display: display, excludingWindows: [])

            let config = SCStreamConfiguration()
            config.capturesAudio = true            // system audio
            config.sampleRate = sr
            config.channelCount = 2                // 시스템은 스테레오일 수 있음 → 다운믹스 예정
            config.captureMicrophone = false       // 마이크는 AVAudioEngine으로 별도 캡처

            // ✅ delegate 파라미터 추가
            let s = SCStream(filter: filter, configuration: config, delegate: self)

            // ✅ .audio 를 완전수식
            do {
                try s.addStreamOutput(self, type: SCStreamOutputType.audio, sampleHandlerQueue: audioQueue)
            } catch {
                FileLogger.shared.log(.error, category: "system", message: "시스템 오디오 출력 추가 실패: \(error)")
                postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "시스템 오디오 출력을 추가할 수 없습니다: \(error.localizedDescription)"))
                throw error
            }

            do {
                try await s.startCapture()
            } catch {
                FileLogger.shared.log(.error, category: "system", message: "시스템 오디오 캡처 시작 실패: \(error)")
                postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "시스템 오디오 캡처를 시작할 수 없습니다: \(error.localizedDescription)"))
                throw error
            }
            self.stream = s
            FileLogger.shared.log(.info, category: "system", message: "시스템 오디오 캡처 시작 성공")

            // 3) Mic capture 시작 (AVCaptureSession 기반 강제 바인딩)
            try await startMicCaptureSession(sampleRate: sr)
            // Device observers는 Helper 시작 시 이미 등록되어 있음

            isPaused = false
            postEvent(.recordingStarted)
            FileLogger.shared.log(.info, category: "recording", message: "started", metadata: ["sessionId": self.sessionId])
            // reset silence state at start
            resetSilence()
        } catch {
            postEvent(.error(message: "start_failed", details: "\(error)"))
            FileLogger.shared.log(.error, category: "recording", message: "start_failed: \(error)")
        }
    }
    
    // 기존 makeWritableOutputURL 대체 → WAV/PCM 출력 경로 준비
    private func prepareOutputURL(from filePath: String?) throws -> URL {
        let defaultPath = FileManager.default.temporaryDirectory
            .appendingPathComponent("audio_\(UUID().uuidString).wav").path
        let path = (filePath?.isEmpty == false ? filePath! : defaultPath)
        let expanded = (path as NSString).expandingTildeInPath
        let url = URL(fileURLWithPath: expanded).standardizedFileURL
        if url.path.hasPrefix(Bundle.main.bundlePath) {
            throw NSError(domain: "path", code: -1001, userInfo: [NSLocalizedDescriptionKey: "cannot write inside app bundle"])
        }
        let dir = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        if FileManager.default.fileExists(atPath: url.path) {
            try? FileManager.default.removeItem(at: url)
        }
        return url
    }

    // MARK: - Pause/Resume/Stop
    private func pause() {
        isPaused = true
        // 세그먼트 시간 동결: 남은 버퍼 비우고(잔여 쓰기/롤오버 방지), 진행 이벤트 중단
        sysBufferF32.removeAll(keepingCapacity: true)
        micBufferF32.removeAll(keepingCapacity: true)
        postEvent(.paused)
    }
    private func resume() {
        isPaused = false
        postEvent(.resumed)
    }

    @MainActor
    private func stop() async {
        do { try await stream?.stopCapture() } catch {}
        stream = nil

        // 마이크 정리 (AVAudioEngine/AVCaptureSession 모두 정리)
        if let engine = audioEngine {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
            audioEngine = nil
        }
        if let s = captureSession {
            s.stopRunning()
            captureSession = nil
        }

        // Device observers는 Helper 프로세스가 살아있는 동안 유지 (stop에서 해제하지 않음)
        stopDiskPolling()
        stopWatchdog()  // 워치독 타이머 정리
        reconnectTimer?.invalidate()
        reconnectTimer = nil
        reconnectTimerSource?.cancel()
        reconnectTimerSource = nil
        reconnectAttempts = 0

        // SegmentManager로 세그먼트 완료 처리
        segmentManager?.finalizeCurrentSegment()
        segmentManager = nil
        
        FileLogger.shared.log(.info, category: "recording", message: "stopped")
        // 총합 샘플 카운트 산출
        let totalSamples = Int(totalFramesWritten * UInt64(runtimeChannels))
        let perChannelFrames = Int(totalFramesWritten)
        postEvent(.recordingStopped(totalSamples: totalSamples,
                                    micSamplesWritten: perChannelFrames,
                                    sysSamplesWritten: perChannelFrames))
        isRecording = false
        // stop silence evaluation
        resetSilence()
        // 녹음 종료 이후에도 레벨미터 유지 (currentMode로)
        if levelMeterEnabled {
            await ensureCaptureForLevelMeter(mode: currentMode)
        }
    }

    // MARK: - Mic availability
    private func isMicAvailable(for micId: String?) -> Bool {
        let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external], mediaType: .audio, position: .unspecified)
        if let id = micId, !id.isEmpty {
            return discovery.devices.contains(where: { $0.uniqueID == id })
        }
        // 명세상 default 사용 금지이나, 가용성 판단은 기본장치 존재 여부로
        return AVCaptureDevice.default(for: .audio) != nil
    }
    
    // MARK: - Device Observers (Public for main)
    func startDeviceObservers() {
        // 중복 등록 방지
        if deviceDisconnectObserver != nil {
            FileLogger.shared.log(.debug, category: "device", message: "Device observers already registered")
            return
        }
        
        let nc = NotificationCenter.default
        deviceDisconnectObserver = nc.addObserver(forName: AVCaptureDevice.wasDisconnectedNotification, object: nil, queue: .main) { [weak self] note in
            guard let self else { return }
            guard let dev = note.object as? AVCaptureDevice else { return }
            if let wantId = self.micDeviceId, !wantId.isEmpty, dev.uniqueID == wantId {
       
                // 1. 장치 변경 알림 전송
                self.postEvent(.audioDeviceChange(changeType: "removed", deviceType: "audio"))
                
                // 2. 녹음 중 일때 만 MIC_DEVICE_LOST 전송
                if self.isRecording {
                    self.postEvent(.errorCode(code: "MIC_DEVICE_LOST", message: dev.localizedName))
                    Task { @MainActor in
                        await self.stop()
                    }
                }
                
                FileLogger.shared.log(.warn, category: "device", 
                                    message: "Microphone device lost", 
                                    metadata: ["name": dev.localizedName, "recording": self.isRecording])
            }
        }
        deviceConnectObserver = nc.addObserver(forName: AVCaptureDevice.wasConnectedNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self else { return }
            // 장치 추가 알림 전송
            self.postEvent(.audioDeviceChange(changeType: "added", deviceType: "audio"))
            FileLogger.shared.log(.info, category: "device", message: "Audio device connected")
        }
        sessionErrorObserver = nc.addObserver(forName: AVCaptureSession.runtimeErrorNotification, object: nil, queue: .main) { [weak self] note in
            guard let self else { return }
            
            // 녹음 중이 아니라면 에러 무시( 장치 변경은 정상 동작)
            guard self.isRecording else {
                FileLogger.shared.log(.debug, category: "device", message: "AVCaptureSession runtime error ignored (not recording)")
                return
            }
            
            self.postEvent(.errorCode(code: "COMMAND_ERROR", message: (note.userInfo?[AVCaptureSessionErrorKey] as? NSError)?.localizedDescription ?? "runtimeError"))
        }
    }
    
    func stopDeviceObservers() {
        let nc = NotificationCenter.default
        if let o = deviceDisconnectObserver { nc.removeObserver(o) }
        if let o = deviceConnectObserver { nc.removeObserver(o) }
        if let o = sessionErrorObserver { nc.removeObserver(o) }
        deviceDisconnectObserver = nil
        deviceConnectObserver = nil
        sessionErrorObserver = nil
    }
}

// MARK: - SCStreamOutput & SCStreamDelegate
@available(macOS 15.0, *)
extension AudioHelperController: SCStreamOutput, SCStreamDelegate {
    func stream(_ stream: SCStream, didOutputSampleBuffer sbuf: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        // 일시정지: 레벨미터는 유지하되 파일기록 버퍼에는 추가하지 않음
        let paused = isPaused
        if paused && !levelMeterEnabled { return }

        // System audio → 다운믹스(모노 Float32)
        let frameCount = Int(CMSampleBufferGetNumSamples(sbuf))
        if frameCount <= 0 { return }
        
        // 실제 샘플레이트 추출
        guard let fmt = CMSampleBufferGetFormatDescription(sbuf),
              let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(fmt) else { return }
        let asbd = asbdPtr.pointee
        let actualSampleRate = extractSampleRate(from: asbd)

        var ablSize: Int = 0
        CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(sbuf,
                                                                bufferListSizeNeededOut: &ablSize,
                                                                bufferListOut: nil,
                                                                bufferListSize: 0,
                                                                blockBufferAllocator: kCFAllocatorDefault,
                                                                blockBufferMemoryAllocator: kCFAllocatorDefault,
                                                                flags: 0,
                                                                blockBufferOut: nil)
        let ablRaw = UnsafeMutableRawPointer.allocate(byteCount: ablSize, alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { ablRaw.deallocate() }
        var block: CMBlockBuffer?
        CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(sbuf,
                                                                bufferListSizeNeededOut: nil,
                                                                bufferListOut: ablRaw.assumingMemoryBound(to: AudioBufferList.self),
                                                                bufferListSize: ablSize,
                                                                blockBufferAllocator: kCFAllocatorDefault,
                                                                blockBufferMemoryAllocator: kCFAllocatorDefault,
                                                                flags: 0,
                                                                blockBufferOut: &block)
        let ablPtr = ablRaw.assumingMemoryBound(to: AudioBufferList.self)
        let ablp = UnsafeMutableAudioBufferListPointer(ablPtr)

        var mono = [Float](repeating: 0, count: frameCount)
        let denom = Float(max(1, ablp.count))
        for buf in ablp {
            guard let mData = buf.mData else { continue }
            let samples = mData.bindMemory(to: Float.self, capacity: frameCount)
            for i in 0..<frameCount { mono[i] += samples[i] }
        }
        if denom > 1 {
            for i in 0..<frameCount { mono[i] /= denom }
        }
        
        // 리샘플링 (실제 샘플레이트 → 목표 샘플레이트)
        let resampled: [Float]
        if actualSampleRate != runtimeSampleRate {
            resampled = resampleLinear(mono, from: actualSampleRate, to: runtimeSampleRate)
            // 디버그 로그 (첫 실행 시에만)
            if debugRawEnabled {
                FileLogger.shared.log(.debug, category: "system", 
                                    message: "리샘플링 수행", 
                                    metadata: ["from": actualSampleRate, 
                                              "to": runtimeSampleRate,
                                              "in": mono.count,
                                              "out": resampled.count])
            }
        } else {
            resampled = mono
        }

        // 레벨 계산/전송 (100ms) — 시스템 음소거 시 0 RMS 전송
        if muteSystem {
            let now = uptimeMs()
            if (now &- lastSysLevelEmitMs >= 100) {
                lastSysLevelEmitMs = now
                lastSysRms = 0.0
                postEvent(.level(source: "system", rms: 0.0, t: now))
                if isRecording && !isPaused && !silenceDetectionDisabled {
                    let eff = max(lastMicRms, lastSysRms)
                    evaluateSilence(withRms: eff, nowMs: now)
                }
            }
        } else {
            emitLevelIfDue(source: "system", mono: resampled)
        }
        // 같은 큐(audioQueue)에서 믹싱(레벨미터 전용일 때는 파일 기록 안 함)
        if !paused {
            if muteSystem {
                sysBufferF32.append(contentsOf: Array(repeating: 0.0, count: resampled.count))
            } else {
                sysBufferF32.append(contentsOf: resampled)
            }
            if isRecording { tryMixAndBuffer() }
        }
    }

    // (선택) 스트림 에러 콜백
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        // 시스템 스트림이 중단되면 재연결 시도 후 실패 시 에러 전송
        // mac에서는 aec_reset 개념 없음 → 재연결 성공 시 aec_reset:false
        Task { @MainActor in
            do {
                try await stream.startCapture() // 간단 재시도
                postEvent(.deviceReconnected(type: "system", aec_reset: false))
            } catch {
                postEvent(.errorCode(code: "DEVICE_RECONNECT_FAILED", message: "system stream restart failed"))
            }
        }
        FileLogger.shared.log(.error, category: "scstream", message: "stopped_with_error: \(error)")
    }
}

// MARK: - Mic capture with AVCaptureAudioDataOutput
@available(macOS 15.0, *)
extension AudioHelperController: AVCaptureAudioDataOutputSampleBufferDelegate {
    func captureOutput(_ output: AVCaptureOutput, didOutput sbuf: CMSampleBuffer, from connection: AVCaptureConnection) {
        let paused = isPaused
        if paused && !levelMeterEnabled { return }
        let frameCount = Int(CMSampleBufferGetNumSamples(sbuf))
        if frameCount <= 0 { return }

        guard let fmt = CMSampleBufferGetFormatDescription(sbuf),
              let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(fmt) else { return }
        let asbd = asbdPtr.pointee
        
        // 실제 샘플레이트 추출
        let actualSampleRate = extractSampleRate(from: asbd)
        
        // Expect Float32 LPCM
        let isFloat = asbd.mFormatID == kAudioFormatLinearPCM && (asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0
        if !isFloat { return }

        var ablSize: Int = 0
        CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(sbuf,
                                                                bufferListSizeNeededOut: &ablSize,
                                                                bufferListOut: nil,
                                                                bufferListSize: 0,
                                                                blockBufferAllocator: kCFAllocatorDefault,
                                                                blockBufferMemoryAllocator: kCFAllocatorDefault,
                                                                flags: 0,
                                                                blockBufferOut: nil)
        let ablRaw = UnsafeMutableRawPointer.allocate(byteCount: ablSize, alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { ablRaw.deallocate() }
        var block: CMBlockBuffer?
        CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(sbuf,
                                                                bufferListSizeNeededOut: nil,
                                                                bufferListOut: ablRaw.assumingMemoryBound(to: AudioBufferList.self),
                                                                bufferListSize: ablSize,
                                                                blockBufferAllocator: kCFAllocatorDefault,
                                                                blockBufferMemoryAllocator: kCFAllocatorDefault,
                                                                flags: 0,
                                                                blockBufferOut: &block)
        let ablPtr = ablRaw.assumingMemoryBound(to: AudioBufferList.self)
        let ablp = UnsafeMutableAudioBufferListPointer(ablPtr)

        var mono = [Float](repeating: 0, count: frameCount)
        let denom = Float(max(1, ablp.count))
        for buf in ablp {
            guard let mData = buf.mData else { continue }
            let samples = mData.bindMemory(to: Float.self, capacity: frameCount)
            for i in 0..<frameCount { mono[i] += samples[i] }
        }
        if denom > 1 {
            for i in 0..<frameCount { mono[i] /= denom }
        }
        
        // 리샘플링 (실제 샘플레이트 → 목표 샘플레이트)
        let resampled: [Float]
        if actualSampleRate != runtimeSampleRate {
            resampled = resampleLinear(mono, from: actualSampleRate, to: runtimeSampleRate)
            // 디버그 로그 (첫 실행 시에만)
            if debugRawEnabled {
                FileLogger.shared.log(.debug, category: "mic", 
                                    message: "리샘플링 수행", 
                                    metadata: ["from": actualSampleRate, 
                                              "to": runtimeSampleRate,
                                              "in": mono.count,
                                              "out": resampled.count])
            }
        } else {
            resampled = mono
        }

        audioQueue.async {
            // pause 중 혹은 녹음 중이 아닐 때는 mic 누적 프레임을 증가시키지 않음
            if !paused && self.isRecording {
                self.totalMicFramesCaptured &+= UInt64(resampled.count)
            }
            if self.muteMic {
                let now = self.uptimeMs()
                if (now &- self.lastMicLevelEmitMs >= 100) {
                    self.lastMicLevelEmitMs = now
                    self.lastMicRms = 0.0
                    self.postEvent(.level(source: "mic", rms: 0.0, t: now))
                    if self.isRecording && !self.isPaused && !self.silenceDetectionDisabled {
                        let eff = max(self.lastMicRms, self.lastSysRms)
                        self.evaluateSilence(withRms: eff, nowMs: now)
                    }
                }
            } else {
                self.emitLevelIfDue(source: "mic", mono: resampled)
            }
            if !paused {
                if self.muteMic {
                    self.micBufferF32.append(contentsOf: Array(repeating: 0.0, count: resampled.count))
                } else {
                    self.micBufferF32.append(contentsOf: resampled)
                }
                if self.isRecording { self.tryMixAndBuffer() }
            }
        }
    }
}

// MARK: - Mic capture with AVAudioEngine
@available(macOS 15.0, *)
private extension AudioHelperController {
    @MainActor
    func startTest(mode: String?, micId: String?) async {
        // 1. 녹음 중이면 테스트 거부 (헬퍼 종료 금지)
        if isRecording {
            postEvent(.error(message: "TEST_BUSY", details: "Recording active"))
            FileLogger.shared.log(.warn, category: "test", message: "test rejected: recording active")
            return
        }

        let desiredMode = mode ?? "MicPlusSystem"
        let desiredMicId = micId ?? selectedMicId ?? ""
        
        // 2. 재사용 조건 체크 (C++ Helper와 동일: isRunning && !isRecording)
        if isRunning && !isRecording {
            let sameMic = (sessionMicId ?? "") == desiredMicId
            let sameMode = currentMode == desiredMode
            
            if sameMic && sameMode {
                // 재사용 성공: isPaused 해제만
                isPaused = false
                postEvent(.testStarted(mode: desiredMode, reuse: true))
                FileLogger.shared.log(.info, category: "test", 
                                    message: "test_started (reused)", 
                                    metadata: ["mode": desiredMode])
                return
            }
            
            // 재사용 불가: 기존 캡처 정리 후 재초기화
            FileLogger.shared.log(.info, category: "test", 
                                message: "capture reinit required", 
                                metadata: ["reason": sameMic ? "mode changed" : "mic changed"])
            await stopCaptureOnly()
        }

        // 3. 신규 시작
        do {
            // UI 직접 호출이면 selectedMicId 업데이트
            if micId != nil {
                selectedMicId = micId
            }
            
            sessionMicId = desiredMicId
            currentMode = desiredMode
            micDeviceId = desiredMicId
            currentTestMode = desiredMode

            // System
            if stream == nil {
                let content: SCShareableContent
                do {
                    content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
                } catch {
                    FileLogger.shared.log(.error, category: "system", message: "테스트: 시스템 콘텐츠 가져오기 실패: \(error)")
                    postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "시스템 오디오 콘텐츠를 가져올 수 없습니다: \(error.localizedDescription)"))
                    throw error
                }
                
                guard let display = content.displays.first else {
                    let error = NSError(domain: "sc", code: -10, userInfo: [NSLocalizedDescriptionKey: "no display found"])
                    FileLogger.shared.log(.error, category: "system", message: "테스트: 사용 가능한 디스플레이 없음")
                    postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "사용 가능한 디스플레이를 찾을 수 없습니다."))
                    throw error
                }
                let filter = SCContentFilter(display: display, excludingWindows: [])
                let cfg = SCStreamConfiguration()
                cfg.capturesAudio = true
                cfg.sampleRate = runtimeSampleRate
                cfg.channelCount = 2
                cfg.captureMicrophone = false
                let s = SCStream(filter: filter, configuration: cfg, delegate: self)
                
                do {
                    try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: audioQueue)
                } catch {
                    FileLogger.shared.log(.error, category: "system", message: "테스트: 시스템 오디오 출력 추가 실패: \(error)")
                    postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "시스템 오디오 출력을 추가할 수 없습니다: \(error.localizedDescription)"))
                    throw error
                }
                
                do {
                    try await s.startCapture()
                } catch {
                    FileLogger.shared.log(.error, category: "system", message: "테스트: 시스템 오디오 캡처 시작 실패: \(error)")
                    postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "시스템 오디오 캡처를 시작할 수 없습니다: \(error.localizedDescription)"))
                    throw error
                }
                stream = s
                FileLogger.shared.log(.info, category: "system", message: "테스트: 시스템 오디오 캡처 시작 성공")
            }

            // Mic
            if captureSession == nil {
                try await startMicCaptureSession(sampleRate: runtimeSampleRate)
            }

            startedByTest = true
            // 파일 기록 금지: isRecording을 false로 유지 → tryMixAndBuffer 호출 차단
            postEvent(.testStarted(mode: desiredMode, reuse: false))
            FileLogger.shared.log(.info, category: "test", 
                                message: "test_started (new)", 
                                metadata: ["mode": desiredMode])
        } catch {
            postEvent(.errorCode(code: "START_TEST_ERROR", message: "테스트 시작에 실패했습니다: \(error.localizedDescription)"))
            FileLogger.shared.log(.error, category: "test", message: "start_test failed: \(error)")
        }
    }

    @MainActor
    func stopTest() async {
        // 테스트로 시작된 캡처만 정리 (녹음과 독립)
        if startedByTest {
            await stopCaptureOnly()
            startedByTest = false
        }
        // test 모드에서 쌓인 버퍼 완전 제거
        audioQueue.async { [weak self] in
            self?.sysBufferF32.removeAll(keepingCapacity: true)
            self?.micBufferF32.removeAll(keepingCapacity: true)
        }
        postEvent(.testStopped)
        // 테스트 종료 이후에도 레벨미터 유지 (currentMode로)
        if levelMeterEnabled {
            await ensureCaptureForLevelMeter(mode: currentMode)
        }
    }
    func startMicCapture(sampleRate: Int) throws {
        let engine = AVAudioEngine()
        let input: AVAudioNode
        if let micId = self.micDeviceId, !micId.isEmpty {
            // Try set preferred input to a specific device (AVAudioEngine supports only system default; precise device binding requires AVCaptureSession)
            // For simplicity in this iteration, we'll keep AVAudioEngine and rely on system default if specific binding isn't supported here.
            input = engine.inputNode
        } else {
            input = engine.inputNode
        }

        let srcFormat = input.outputFormat(forBus: 0)
        let dstFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                      sampleRate: Double(sampleRate),
                                      channels: 1,
                                      interleaved: false)!
        self.micDstFormat = dstFormat
        self.micConverter = AVAudioConverter(from: srcFormat, to: dstFormat)

        input.installTap(onBus: 0, bufferSize: AVAudioFrameCount(framesPerChunk), format: nil) { [weak self] (buffer, _time) in
            guard let self else { return }
            if self.isPaused { return }
            guard let converter = self.micConverter, let dstFormat = self.micDstFormat else { return }

            // 출력 버퍼 용량 추정(샘플레이트 차이를 고려해 약간 여유)
            let ratio = dstFormat.sampleRate / buffer.format.sampleRate
            let expected = max(1, Int((Double(buffer.frameLength) * ratio).rounded(.up) + 64))
            guard let outBuf = AVAudioPCMBuffer(pcmFormat: dstFormat, frameCapacity: AVAudioFrameCount(expected)) else { return }

            var convError: NSError?
            let status = converter.convert(to: outBuf, error: &convError) { _, inStatus in
                inStatus.pointee = .haveData
                return buffer
            }
            if status != .haveData || convError != nil || outBuf.frameLength == 0 {
                return
            }

            let count = Int(outBuf.frameLength)
            if count > 0, let ch0 = outBuf.floatChannelData?[0] {
                let mono = Array(UnsafeBufferPointer(start: ch0, count: count))
                self.audioQueue.async {
                    if self.isRecording {
                        self.micBufferF32.append(contentsOf: mono)
                        self.tryMixAndBuffer()
                    }
                }
            }
        }

        try engine.start()
        self.audioEngine = engine
    }

    // AVCaptureSession 기반 강제 바인딩 캡처 시작
    func startMicCaptureSession(sampleRate: Int) async throws {
        // 1. 마이크 권한 확인 및 요청
        let status = AVCaptureDevice.authorizationStatus(for: .audio)
        FileLogger.shared.log(.info, category: "mic", message: "마이크 권한 상태 확인", metadata: ["status": "\(status.rawValue)"])
        
        if status == .denied || status == .restricted {
            let error = NSError(domain: "mic", code: -2000, userInfo: [NSLocalizedDescriptionKey: "마이크 권한이 거부되었습니다."])
            FileLogger.shared.log(.error, category: "mic", message: "마이크 권한 거부됨")
            postEvent(.errorCode(code: "MIC_PERMISSION_DENIED", message: "마이크 권한이 필요합니다. 시스템 설정에서 권한을 허용해주세요."))
            throw error
        }
        
        // 2. 권한이 아직 결정되지 않았으면 요청하고 대기
        if status == .notDetermined {
            FileLogger.shared.log(.info, category: "mic", message: "마이크 권한 요청 중...")
            let granted = await AVCaptureDevice.requestAccess(for: .audio)
            FileLogger.shared.log(.info, category: "mic", message: "마이크 권한 요청 결과", metadata: ["granted": "\(granted)"])
            
            if !granted {
                let error = NSError(domain: "mic", code: -2000, userInfo: [NSLocalizedDescriptionKey: "마이크 권한이 거부되었습니다."])
                FileLogger.shared.log(.error, category: "mic", message: "사용자가 마이크 권한 거부")
                postEvent(.errorCode(code: "MIC_PERMISSION_DENIED", message: "마이크 권한이 필요합니다."))
                throw error
            }
        }
        
        // 3. 권한이 허용된 후 세션 시작
        do {
            let session = AVCaptureSession()

            // 선택 장치 찾기
            let device: AVCaptureDevice?
            if let wantId = micDeviceId, !wantId.isEmpty {
                let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external], mediaType: .audio, position: .unspecified)
                device = discovery.devices.first(where: { $0.uniqueID == wantId }) ?? AVCaptureDevice.default(for: .audio)
            } else {
                device = AVCaptureDevice.default(for: .audio)
            }
            guard let dev = device else {
                let error = NSError(domain: "mic", code: -2001, userInfo: [NSLocalizedDescriptionKey: "no audio device"])
                FileLogger.shared.log(.error, category: "mic", message: "마이크 장치를 찾을 수 없음")
                postEvent(.errorCode(code: "MIC_INIT_FAILED", message: "마이크 장치를 찾을 수 없습니다."))
                throw error
            }

            // 입력 구성
            let input: AVCaptureDeviceInput
            do {
                input = try AVCaptureDeviceInput(device: dev)
            } catch {
                FileLogger.shared.log(.error, category: "mic", message: "마이크 입력 생성 실패: \(error)")
                postEvent(.errorCode(code: "MIC_INIT_FAILED", message: "마이크 입력을 생성할 수 없습니다: \(error.localizedDescription)"))
                throw error
            }
            
            guard session.canAddInput(input) else {
                let error = NSError(domain: "mic", code: -2002, userInfo: [NSLocalizedDescriptionKey: "cannot add input"])
                FileLogger.shared.log(.error, category: "mic", message: "세션에 입력 추가 불가")
                postEvent(.errorCode(code: "MIC_INIT_FAILED", message: "마이크 입력을 세션에 추가할 수 없습니다."))
                throw error
            }
            session.addInput(input)

            // 출력 구성
            let out = AVCaptureAudioDataOutput()
            out.setSampleBufferDelegate(self, queue: micOutputQueue)
            guard session.canAddOutput(out) else {
                let error = NSError(domain: "mic", code: -2003, userInfo: [NSLocalizedDescriptionKey: "cannot add output"])
                FileLogger.shared.log(.error, category: "mic", message: "세션에 출력 추가 불가")
                postEvent(.errorCode(code: "MIC_INIT_FAILED", message: "마이크 출력을 세션에 추가할 수 없습니다."))
                throw error
            }
            session.addOutput(out)

            session.startRunning()
            self.captureSession = session
            self.captureAudioOutput = out
            FileLogger.shared.log(.info, category: "mic", message: "마이크 캡처 세션 시작 성공", metadata: ["device": dev.localizedName])
        } catch {
            // 이미 위에서 에러 이벤트를 전송했으므로 여기서는 throw만
            throw error
        }
    }

    // beginReconnect() 및 tryReconnectNow() 함수 제거
    // 마이크 장치 분리 시 재연결 시도 없이 즉시 녹음 중지 (Windows Helper와 동일)

    // Rebind capture session input to a specific device id; if nil, bind to default audio device
    @discardableResult
    @MainActor
    func rebindMicToDevice(_ deviceId: String?) -> String? {
        guard let session = captureSession else { return nil }
        let device: AVCaptureDevice?
        if let id = deviceId, !id.isEmpty {
            let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external], mediaType: .audio, position: .unspecified)
            device = discovery.devices.first(where: { $0.uniqueID == id }) ?? AVCaptureDevice.default(for: .audio)
        } else {
            device = AVCaptureDevice.default(for: .audio)
        }
        guard let dev = device else { return nil }

        session.beginConfiguration()
        for input in session.inputs {
            if let ai = input as? AVCaptureDeviceInput, ai.device.hasMediaType(.audio) {
                session.removeInput(ai)
            }
        }
        do {
            let newInput = try AVCaptureDeviceInput(device: dev)
            if session.canAddInput(newInput) { session.addInput(newInput) } else { session.commitConfiguration(); return nil }
        } catch {
            session.commitConfiguration(); return nil
        }
        if captureAudioOutput == nil {
            let out = AVCaptureAudioDataOutput()
            out.setSampleBufferDelegate(self, queue: micOutputQueue)
            if session.canAddOutput(out) { session.addOutput(out); captureAudioOutput = out } else {
                session.commitConfiguration(); return nil
            }
        }
        session.commitConfiguration()
        if !session.isRunning { session.startRunning() }
        micDeviceId = dev.uniqueID
        return dev.uniqueID
    }
}

// MARK: - Mixing and Buffering (3분 버퍼링 방식)
@available(macOS 15.0, *)
private extension AudioHelperController {
    func tryMixAndBuffer() {
        if isPaused { return }
        guard let segMgr = segmentManager else { return }
        
        let available = min(sysBufferF32.count, micBufferF32.count)
        if available < framesPerChunk { return }
        let frames = available - (available % framesPerChunk)
        if frames <= 0 { return }

        // 믹싱: Float32 → Int16
        var samples = [Int16]()
        samples.reserveCapacity(frames)
        for i in 0..<frames {
            // 시스템 + 마이크 평균 믹싱 (모노)
            let mixed = (sysBufferF32[i] + micBufferF32[i]) / 2.0
            samples.append(floatToS16(mixed))
        }

        // SegmentManager 버퍼에 추가 (파일 쓰기는 3분마다 자동)
        let segmentCompleted = segMgr.addSamples(samples)
        
        totalFramesWritten &+= UInt64(frames)
        sysBufferF32.removeFirst(frames)
        micBufferF32.removeFirst(frames)
        
        // stopAtBoundary: 워치독이나 MAX_SEGMENTS 도달 시 세그먼트 경계에서 안전 정지
        if segmentCompleted && stopAtBoundary {
            FileLogger.shared.log(.info, category: "recording", 
                                message: "Stopping at segment boundary (watchdog/max_segments)")
            Task { @MainActor [weak self] in
                await self?.stop()
            }
            return
        }

        // progress throttle ~200ms
        let nowMs = uptimeMs()
        if nowMs &- lastProgressEmitMs >= 200 && !isPaused {
            lastProgressEmitMs = nowMs
            let seconds = Double(totalFramesWritten) / Double(runtimeSampleRate)
            let samples = Int(totalFramesWritten * UInt64(runtimeChannels))
            let micSeconds = Double(totalMicFramesCaptured) / Double(runtimeSampleRate)
            postEvent(.progress(seconds: seconds,
                                samples: samples,
                                micSamples: Int(totalMicFramesCaptured),
                                micSeconds: micSeconds))
        }
    }

    @inline(__always)
    func floatToS16(_ x: Float) -> Int16 {
        let clamped = max(-1.0, min(1.0, Double(x)))
        return Int16(clamped * Double(Int16.max))
    }
}

// MARK: - Utility Methods
@available(macOS 15.0, *)
private extension AudioHelperController {
    // monotonic millisecond clock
    func uptimeMs() -> UInt64 {
        let t = DispatchTime.now().uptimeNanoseconds
        return t / 1_000_000
    }

    // Emit level events every ~100ms (Windows 동작과 정렬: 항상 전송, levelMeterEnabled=false면 0 RMS)
    // 마이크와 시스템 오디오는 독립적인 타이머 사용하여 서로 간섭하지 않음
    func emitLevelIfDue(source: String, mono: [Float]) {
        guard !mono.isEmpty else { return }
        let now = uptimeMs()
        
        // 소스별로 다른 타이머 사용
        if source == "mic" {
            if now &- lastMicLevelEmitMs < 100 { return }
            lastMicLevelEmitMs = now
        } else if source == "system" {
            if now &- lastSysLevelEmitMs < 100 { return }
            lastSysLevelEmitMs = now
        } else {
            return // unknown source
        }
        
        // RMS 계산
        var sum: Double = 0
        for x in mono { let d = Double(x); sum += d*d }
        let rms = sqrt(sum / Double(mono.count))
        // levelMeterEnabled가 false면 0 RMS 전송 (Windows 동작과 정렬)
        let effectiveRms = levelMeterEnabled ? rms : 0.0
        postEvent(.level(source: source, rms: effectiveRms, t: now))
        // silence detection only when recording and not paused
        if source == "mic" { lastMicRms = rms } else if source == "system" { lastSysRms = rms }
        if isRecording && !isPaused && !silenceDetectionDisabled {
            let effective = max(lastMicRms, lastSysRms)
            evaluateSilence(withRms: effective, nowMs: now)
        }
    }

    // Ensure capture running without file recording (for level meter only)
    @MainActor
    func ensureCaptureForLevelMeter(mode: String = "MicPlusSystem") async {
        if !isRunning {
            // currentMode 적용하여 캡처 시작 (재사용 가능하도록)
            self.currentMode = mode
            
            do {
                if stream == nil {
                    let content: SCShareableContent
                    do {
                        content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
                    } catch {
                        FileLogger.shared.log(.error, category: "system", message: "레벨미터: 시스템 콘텐츠 가져오기 실패: \(error)")
                        postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "시스템 오디오 콘텐츠를 가져올 수 없습니다: \(error.localizedDescription)"))
                        throw error
                    }
                    
                    guard let display = content.displays.first else {
                        let error = NSError(domain: "sc", code: -10, userInfo: [NSLocalizedDescriptionKey: "no display found"])
                        FileLogger.shared.log(.error, category: "system", message: "레벨미터: 사용 가능한 디스플레이 없음")
                        postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "사용 가능한 디스플레이를 찾을 수 없습니다."))
                        throw error
                    }
                    let filter = SCContentFilter(display: display, excludingWindows: [])
                    let cfg = SCStreamConfiguration()
                    cfg.capturesAudio = true
                    cfg.sampleRate = runtimeSampleRate
                    cfg.channelCount = 2
                    cfg.captureMicrophone = false
                    let s = SCStream(filter: filter, configuration: cfg, delegate: self)
                    
                    do {
                        try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: audioQueue)
                    } catch {
                        FileLogger.shared.log(.error, category: "system", message: "레벨미터: 시스템 오디오 출력 추가 실패: \(error)")
                        postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "시스템 오디오 출력을 추가할 수 없습니다: \(error.localizedDescription)"))
                        throw error
                    }
                    
                    do {
                        try await s.startCapture()
                    } catch {
                        FileLogger.shared.log(.error, category: "system", message: "레벨미터: 시스템 오디오 캡처 시작 실패: \(error)")
                        postEvent(.errorCode(code: "SYS_INIT_FAILED", message: "시스템 오디오 캡처를 시작할 수 없습니다: \(error.localizedDescription)"))
                        throw error
                    }
                    stream = s
                    FileLogger.shared.log(.info, category: "system", message: "레벨미터: 시스템 오디오 캡처 시작 성공")
                }
                if captureSession == nil {
                    try await startMicCaptureSession(sampleRate: runtimeSampleRate)
                }
                startedByLevelMeter = true
            } catch {
                FileLogger.shared.log(.error, category: "levelmeter", message: "레벨미터 캡처 시작 실패: \(error)")
                // 이미 위에서 구체적인 에러를 전송했으므로 여기서는 추가 에러 전송 없음
            }
        }
    }

    // Stop capture if running (without emitting stop recording)
    @MainActor
    func stopCaptureOnly() async {
        do { try await stream?.stopCapture() } catch {}
        stream = nil
        if let s = captureSession { s.stopRunning(); captureSession = nil }
    }
}

// MARK: - Disk status
@available(macOS 15.0, *)
private extension AudioHelperController {
    func bytesAvailable(at url: URL?) -> Int64? {
        guard let url else { return nil }
        // Check volume for the directory; if it doesn't exist yet, use its parent
        let checkURL = url.hasDirectoryPath ? url : url.deletingLastPathComponent()
        do {
            let values = try checkURL.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
            if let v = values.volumeAvailableCapacityForImportantUsage { return Int64(v) }
        } catch {
            // fallback below
        }
        do {
            let attrs = try FileManager.default.attributesOfFileSystem(forPath: checkURL.path)
            if let n = attrs[.systemFreeSize] as? NSNumber { return n.int64Value }
        } catch {
            return nil
        }
        return nil
    }

    func categorizeDiskStatus(_ freeBytes: Int64?) -> String {
        guard let b = freeBytes else { return "unknown" }
        if b < LOW_THRESHOLD_BYTES { return "critical" }
        if b < OK_THRESHOLD_BYTES { return "low" }
        return "ok"
    }

    func currentDiskStatus() -> (String, Int64) {
        let url = outputDirURL ?? outputBaseDirURL
        let free = bytesAvailable(at: url) ?? 0
        let st = categorizeDiskStatus(free)
        return (st, free)
    }

    func emitDiskStatusOnce(for url: URL) {
        let free = bytesAvailable(at: url) ?? 0
        let st = categorizeDiskStatus(free)
        postEvent(.diskStatus(status: st, freeBytes: free))
        lastDiskStatus = st
        lastDiskEmitMs = uptimeMs()
    }

    func startDiskPolling() {
        stopDiskPolling()
        let src = DispatchSource.makeTimerSource(queue: DispatchQueue.global(qos: .utility))
        src.setEventHandler { [weak self] in
            guard let self else { return }
            if !self.isRecording { return }
            let (st, free) = self.currentDiskStatus()
            let now = self.uptimeMs()
            
            // 디스크 상태 전송
            if self.lastDiskStatus != st || (now &- self.lastDiskEmitMs) >= 5000 {
                self.lastDiskStatus = st
                self.lastDiskEmitMs = now
                self.postEvent(.diskStatus(status: st, freeBytes: free))
            }
            
            // critical 상태 시 녹음 자동 중지
            if st == "critical" {
                FileLogger.shared.log(.warn, category: "disk",
                                    message: "Disk space critical, stopping recording",
                                    metadata: ["freeBytes": free])
                self.postEvent(.errorCode(
                    code: "DISK_SPACE_LOW_STOP",
                    message: "디스크 여유 공간이 \(free / 1024 / 1024)MB 미만입니다. 녹음을 안전하게 중지합니다."
                ))
                
                // Main Actor 컨텍스트에서 stop 호출
                Task { @MainActor [weak self] in
                    await self?.stop()
                }
            }
        }
        src.schedule(deadline: .now() + 1.0, repeating: 1.0)
        src.resume()
        diskTimerSource = src
    }

    func stopDiskPolling() {
        diskTimerSource?.cancel()
        diskTimerSource = nil
        lastDiskStatus = nil
        lastDiskEmitMs = 0
    }
}

// MARK: - Watchdog timer (Windows Helper와 동일)
@available(macOS 15.0, *)
private extension AudioHelperController {
    /// 워치독 타이머 시작 (max_ms 설정 시)
    func startWatchdogIfNeeded() {
        // max_ms가 0이면 무제한 녹음 (워치독 없음)
        guard maxDurationMs > 0 else {
            FileLogger.shared.log(.info, category: "watchdog", 
                                message: "Watchdog skipped: max_ms==0 (unlimited recording)")
            return
        }
        
        // 이미 실행 중이면 스킵
        guard watchdogTimer == nil else {
            FileLogger.shared.log(.info, category: "watchdog", 
                                message: "Watchdog skipped: already running")
            return
        }
        
        let localStart = startTimeMs
        let deadline = localStart + maxDurationMs
        
        FileLogger.shared.log(.info, category: "watchdog", 
                            message: "Watchdog started", 
                            metadata: [
                                "max_ms": maxDurationMs,
                                "start_ms": localStart,
                                "deadline_ms": deadline
                            ])
        
        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global(qos: .utility))
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            guard self.isRecording else { return }
            
            let now = self.uptimeMs()
            if now >= deadline {
                // Windows Helper와 동일: 즉시 중지 대신 세그먼트 경계에서 안전 정지
                if !self.stopAtBoundary {
                    FileLogger.shared.log(.info, category: "watchdog", 
                                        message: "Watchdog timeout reached, will stop at next segment boundary")
                    self.stopAtBoundary = true
                }
                // 실제 정지는 tryMixAndBuffer()에서 세그먼트 완료 시 처리됨
            }
        }
        
        // 50ms마다 체크 (Windows Helper와 동일)
        timer.schedule(deadline: .now(), repeating: .milliseconds(50))
        timer.resume()
        watchdogTimer = timer
    }
    
    /// 워치독 타이머 정지
    func stopWatchdog() {
        watchdogTimer?.cancel()
        watchdogTimer = nil
        maxDurationMs = 0
        startTimeMs = 0
        stopAtBoundary = false
    }
}

// MARK: - Silence detection
@available(macOS 15.0, *)
private extension AudioHelperController {
    func resetSilence() {
        silenceActive = false
        silenceStartMs = 0
        lastEarlyIndex = 0
        sustainedSent = false
        silenceCandidateStartMs = 0
        soundCandidateStartMs = 0
        silenceDetectionDisabled = false
        lastMicRms = 0.0
        lastSysRms = 0.0
    }

    func evaluateSilence(withRms rms: Double, nowMs: UInt64) {
        if silenceDetectionDisabled { return }
        // treat mute as silence by upstream: level emits 0 when muted
        let isSilentNow = rms < SILENCE_RMS_THRESHOLD
        if !isSilentNow {
            silenceCandidateStartMs = 0
            // 유음 지속 시간이 충분할 때에만 무음 해제를 1회 전송
            if silenceActive {
                if soundCandidateStartMs == 0 { soundCandidateStartMs = nowMs }
                if (nowMs &- soundCandidateStartMs) >= MIN_SOUND_EXIT_MS {
                    let elapsed = Int(nowMs &- silenceStartMs)
                    postEvent(.silence(state: "off", elapsedMs: elapsed))
                    resetSilence()
                    silenceDetectionDisabled = true
                }
            } else {
                soundCandidateStartMs = 0
            }
            return
        }
        // silent
        soundCandidateStartMs = 0
        if !silenceActive {
            if silenceCandidateStartMs == 0 { silenceCandidateStartMs = nowMs }
            if (nowMs &- silenceCandidateStartMs) >= MIN_SILENCE_ENTER_MS {
                // 무음 진입 확정
                silenceActive = true
                // early/sustained 기준은 최초 조용해진 시점을 기준으로 유지
                if silenceStartMs == 0 { silenceStartMs = silenceCandidateStartMs }
                lastEarlyIndex = 0
                sustainedSent = false
            }
            return
        }
        let elapsed = Int(nowMs &- silenceStartMs)
        // early thresholds at 7/14/21/28 sec
        let thresholds = [7, 14, 21, 28]
        if lastEarlyIndex < thresholds.count {
            let targetMs = thresholds[lastEarlyIndex] * 1000
            if elapsed >= targetMs {
                postEvent(.silence(state: "early", elapsedMs: elapsed))
                lastEarlyIndex += 1
            }
        }
        // sustained at 30 sec once
        if !sustainedSent && elapsed >= 30_000 {
            postEvent(.silence(state: "sustained", elapsedMs: elapsed))
            sustainedSent = true
            // sustained 후에도 감지 지속 (유음 감지 시 off 전송 위해)
        }
    }
}

// MARK: - Resampling Utilities
@available(macOS 15.0, *)
private extension AudioHelperController {
    /// 선형 보간 리샘플링 (Windows Helper의 ResampleLinearMonoStateful 참고)
    /// - Parameters:
    ///   - input: 입력 Float32 모노 샘플
    ///   - inputRate: 입력 샘플레이트 (Hz)
    ///   - outputRate: 출력 샘플레이트 (Hz)
    /// - Returns: 리샘플링된 Float32 모노 샘플
    func resampleLinear(_ input: [Float], from inputRate: Int, to outputRate: Int) -> [Float] {
        guard inputRate != outputRate else { return input }
        guard !input.isEmpty else { return [] }
        
        let ratio = Double(outputRate) / Double(inputRate)
        let outputCount = Int(Double(input.count) * ratio)
        var output = [Float](repeating: 0, count: outputCount)
        
        for i in 0..<outputCount {
            let srcPos = Double(i) / ratio
            let srcIdx = Int(srcPos)
            let frac = Float(srcPos - Double(srcIdx))
            
            if srcIdx + 1 < input.count {
                // 선형 보간
                output[i] = input[srcIdx] * (1.0 - frac) + input[srcIdx + 1] * frac
            } else if srcIdx < input.count {
                output[i] = input[srcIdx]
            }
        }
        
        return output
    }
    
    /// 실제 샘플레이트 추출 (AudioStreamBasicDescription에서)
    func extractSampleRate(from asbd: AudioStreamBasicDescription) -> Int {
        return Int(asbd.mSampleRate)
    }
}

// 주석
