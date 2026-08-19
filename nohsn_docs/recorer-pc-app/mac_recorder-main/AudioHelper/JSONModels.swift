//
//  JSONModels.swift
//  AudioHelper
//
//  Created by 장준호 on 10/23/25.
//

import Foundation

struct Command: Decodable {
    let cmd: String            // start, pause, resume, stop, status, set_output_dir, set_debug_files, set_segment_config, get_version, start_test, stop_test, set_level_meter, set_mute
    let sessionId: String?
    let filePath: String?
    let outputDir: String?
    let sampleRate: Int?
    let channels: Int?
    let micDeviceId: String?
    let mode: String?
    let target: String?
    let valueAny: BoolOrString?

    // Electron renderer parity
    let mic: String?           // start.mic
    let out: StartOut?

    // Extended fields for helper interface parity
    let directory: String?
    let enabledAny: BoolOrString?
    let encryptionEnabled: String?
    let segmentSeconds: String?
    let maxMsAny: StringOrInt?      // max_ms: 최대 녹음 시간 (밀리초, 문자열 또는 숫자)
    let segmenting: SegmentingConfig?  // 세그먼트 설정
    
    var maxMs: String? {
        return maxMsAny?.raw
    }

    enum CodingKeys: String, CodingKey {
        case cmd, sessionId, filePath, outputDir, sampleRate, channels, micDeviceId, mode
        case mic
        case out
        case directory
        case enabledAny = "enabled"
        case encryptionEnabled = "encryption_enabled"
        case segmentSeconds = "segment_seconds"
        case target
        case valueAny = "value"
        case maxMsAny = "max_ms"
        case segmenting = "segmenting"
    }
}

struct StartOut: Decodable {
    let sr: Int?
    let ch: Int?
}

struct SegmentingConfig: Decodable {
    let duration_ms: Int?           // 세그먼트 길이 (밀리초)
    let max_cipher_bytes: Int?      // 최대 암호화 바이트
    let align_to_block: Bool?       // 블록 정렬 여부
}

// Accepts either "true"/"false" or boolean/integer flags
struct BoolOrString: Decodable {
    let raw: String
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let s = try? c.decode(String.self) {
            raw = s
        } else if let b = try? c.decode(Bool.self) {
            raw = b ? "true" : "false"
        } else if let i = try? c.decode(Int.self) {
            raw = (i != 0) ? "true" : "false"
        } else {
            raw = ""
        }
    }
}

// Accepts either string or integer (for max_ms, etc.)
struct StringOrInt: Decodable {
    let raw: String
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let s = try? c.decode(String.self) {
            raw = s
        } else if let i = try? c.decode(Int.self) {
            raw = String(i)
        } else if let i64 = try? c.decode(Int64.self) {
            raw = String(i64)
        } else if let u64 = try? c.decode(UInt64.self) {
            raw = String(u64)
        } else {
            raw = ""
        }
    }
}

struct DeviceInfo: Encodable {
    let id: String
    let name: String
    let isDefault: Bool
}

enum Event: Encodable {
    case recordingStarted
    case segmentReady(index: Int, path: String, samples: Int, durationMs: Int, sizeBytes: Int, encrypted: Bool)
    case devices([DeviceInfo])
    case deviceReconnected(type: String, aec_reset: Bool)
    case audioDeviceChange(changeType: String, deviceType: String)
    case progress(seconds: Double, samples: Int, micSamples: Int, micSeconds: Double)
    case level(source: String, rms: Double, t: UInt64)
    case paused
    case resumed
    case recordingStopped(totalSamples: Int, micSamplesWritten: Int, sysSamplesWritten: Int)
    case status(paused: Bool)
    case outputDirSet(directory: String)
    case debugFilesSet(enabled: String)
    case segmentConfigSet(encryptionEnabled: String, segmentSeconds: String, diskStatus: String, freeBytes: Int64)
    case levelMeterState(enabled: Bool)
    case muteState(mic: Bool, system: Bool)
    case testStarted(mode: String?, reuse: Bool?)
    case testStopped
    case diskStatus(status: String, freeBytes: Int64)
    case silence(state: String, elapsedMs: Int)
    case micState(state: String)
    case versionInfo(
        version: String,
        version_full: String,
        product_name: String,
        description: String,
        webrtc_aec: Bool,
        noise_suppression: Bool,
        gain_control: Bool,
        build_date: String,
        build_time: String,
        copyright: String
    )
    case helperInfo(utf8: Bool, version: String, webrtc_aec: Bool, build_date: String)
    case error(message: String, details: String?)
    case errorCode(code: String, message: String)

    func jsonString() -> String {
        let enc = JSONEncoder()
        enc.outputFormatting = []
        let data = (try? enc.encode(self)) ?? Data()
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    enum CodingKeys: String, CodingKey {
        case ev, file, sessionId, paused, message, details
        case index, path, samples, duration_ms, size_bytes, encrypted
        case devices
        case deviceId, type
        case aec_reset
        case change_type, device_type
        case seconds, mic_samples, mic_seconds
        case source, rms, t
        case state
        case directory
        case enabled
        case encryption_enabled, segment_seconds
        case status, free_bytes
        case totalSamples, micSamplesWritten, sysSamplesWritten
        case mic, system
        case mode, reuse
        case version, version_full, product_name, description, webrtc_aec, noise_suppression, gain_control, build_date, build_time, copyright
        case utf8
        case code
        case elapsedMs
    }
    enum EventType: String, Encodable { case recording_started, paused, resumed, recording_stopped, status, error, segment_ready, devices, device_reconnected, audio_device_change, progress, level, output_dir_set, debug_files_set, segment_config_set, level_meter_state, mute_state, test_started, test_stopped, version_info, helper_info, disk_status, silence, mic_state }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .recordingStarted:
            try c.encode(EventType.recording_started, forKey: .ev)
        case let .segmentReady(index, path, samples, durationMs, sizeBytes, encrypted):
            try c.encode(EventType.segment_ready, forKey: .ev)
            try c.encode(index, forKey: .index)
            try c.encode(path, forKey: .path)
            try c.encode(samples, forKey: .samples)
            try c.encode(durationMs, forKey: .duration_ms)
            try c.encode(sizeBytes, forKey: .size_bytes)
            try c.encode(encrypted, forKey: .encrypted)
        case let .devices(list):
            try c.encode(EventType.devices, forKey: .ev)
            try c.encode(list, forKey: .devices)
        case let .deviceReconnected(type, aec_reset):
            try c.encode(EventType.device_reconnected, forKey: .ev)
            try c.encode(type, forKey: .type)
            try c.encode(aec_reset, forKey: .aec_reset)
        case let .audioDeviceChange(changeType, deviceType):
            try c.encode(EventType.audio_device_change, forKey: .ev)
            try c.encode(changeType, forKey: .change_type)
            try c.encode(deviceType, forKey: .device_type)
        
        case let .progress(seconds, samples, micSamples, micSeconds):
            try c.encode(EventType.progress, forKey: .ev)
            try c.encode(seconds, forKey: .seconds)
            try c.encode(samples, forKey: .samples)
            try c.encode(micSamples, forKey: .mic_samples)
            try c.encode(micSeconds, forKey: .mic_seconds)
        case let .level(source, rms, t):
            try c.encode(EventType.level, forKey: .ev)
            try c.encode(source, forKey: .source)
            try c.encode(rms, forKey: .rms)
            try c.encode(t, forKey: .t)
        case .paused:
            try c.encode(EventType.paused, forKey: .ev)
        case .resumed:
            try c.encode(EventType.resumed, forKey: .ev)
        case let .recordingStopped(total, mic, sys):
            try c.encode(EventType.recording_stopped, forKey: .ev)
            try c.encode(total, forKey: .totalSamples)
            try c.encode(mic, forKey: .micSamplesWritten)
            try c.encode(sys, forKey: .sysSamplesWritten)
        case let .status(paused):
            try c.encode(EventType.status, forKey: .ev)
            try c.encode(paused, forKey: .paused)
        case let .outputDirSet(directory):
            try c.encode(EventType.output_dir_set, forKey: .ev)
            try c.encode(directory, forKey: .directory)
        case let .debugFilesSet(enabled):
            try c.encode(EventType.debug_files_set, forKey: .ev)
            try c.encode(enabled, forKey: .enabled)
        case let .segmentConfigSet(encryptionEnabled, segmentSeconds, diskStatus, freeBytes):
            try c.encode(EventType.segment_config_set, forKey: .ev)
            try c.encode(encryptionEnabled, forKey: .encryption_enabled)
            try c.encode(segmentSeconds, forKey: .segment_seconds)
            try c.encode(diskStatus, forKey: .status)
            try c.encode(freeBytes, forKey: .free_bytes)
        case let .levelMeterState(enabled):
            try c.encode(EventType.level_meter_state, forKey: .ev)
            try c.encode(enabled, forKey: .enabled)
        case let .muteState(mic, system):
            try c.encode(EventType.mute_state, forKey: .ev)
            try c.encode(mic, forKey: .mic)
            try c.encode(system, forKey: .system)
        case let .testStarted(mode, reuse):
            try c.encode(EventType.test_started, forKey: .ev)
            if let m = mode { try c.encode(m, forKey: .mode) }
            if let r = reuse { try c.encode(r, forKey: .reuse) }
        case .testStopped:
            try c.encode(EventType.test_stopped, forKey: .ev)
        case let .diskStatus(status, freeBytes):
            try c.encode(EventType.disk_status, forKey: .ev)
            try c.encode(status, forKey: .status)
            try c.encode(freeBytes, forKey: .free_bytes)
        case let .versionInfo(version, version_full, product_name, description, webrtc_aec, noise_suppression, gain_control, build_date, build_time, copyright):
            try c.encode(EventType.version_info, forKey: .ev)
            try c.encode(version, forKey: .version)
            try c.encode(version_full, forKey: .version_full)
            try c.encode(product_name, forKey: .product_name)
            try c.encode(description, forKey: .description)
            try c.encode(webrtc_aec, forKey: .webrtc_aec)
            try c.encode(noise_suppression, forKey: .noise_suppression)
            try c.encode(gain_control, forKey: .gain_control)
            try c.encode(build_date, forKey: .build_date)
            try c.encode(build_time, forKey: .build_time)
            try c.encode(copyright, forKey: .copyright)
        case let .helperInfo(utf8, version, webrtc_aec, build_date):
            try c.encode(EventType.helper_info, forKey: .ev)
            try c.encode(utf8, forKey: .utf8)
            try c.encode(version, forKey: .version)
            try c.encode(webrtc_aec, forKey: .webrtc_aec)
            try c.encode(build_date, forKey: .build_date)
        case let .error(message, details):
            try c.encode(EventType.error, forKey: .ev)
            try c.encode(message, forKey: .message)
            if let d = details { try c.encode(d, forKey: .details) }
        case let .errorCode(code, message):
            try c.encode(EventType.error, forKey: .ev)
            try c.encode(code, forKey: .code)
            try c.encode(message, forKey: .message)
        case let .silence(state, elapsedMs):
            try c.encode(EventType.silence, forKey: .ev)
            try c.encode(state, forKey: .state)
            try c.encode(elapsedMs, forKey: .elapsedMs)
        case let .micState(state):
            try c.encode(EventType.mic_state, forKey: .ev)
            try c.encode(state, forKey: .state)
        }
    }
}
