//
//  SegmentManager.swift
//  AudioHelper
//
//  Created by 장준호 on 10/28/25.
//

import Foundation
import CryptoSwift

/// 세그먼트 단위 오디오 버퍼 및 파일 저장을 관리하는 클래스
/// Windows Helper의 SegmentManager와 동일한 아키텍처를 사용하여
/// 3분치 데이터를 메모리에 버퍼링한 후 한 번에 파일로 저장함
@available(macOS 15.0, *)
final class SegmentManager {
    // MARK: - Properties
    
    /// 현재 세그먼트의 샘플 버퍼 (Int16 mono)
    private var segmentBuffer: [Int16] = []
    
    /// 현재 세그먼트에 누적된 샘플 수
    private var currentSegmentSamples: UInt64 = 0
    
    /// 현재 세그먼트 인덱스 (0부터 시작)
    private var segmentIndex: Int = 0
    
    /// 세그먼트 하나의 길이 (샘플 수)
    private let segmentDurationSamples: UInt64
    
    /// 최소 저장 길이 (1초 미만은 저장 안 함)
    private let minSegmentSamples: UInt64
    
    /// 출력 디렉토리
    private var outputDirectory: URL?
    
    /// 세션 ID
    private var sessionId: String = ""
    
    /// 암호화 활성화 여부
    private var encryptionEnabled: Bool = false
    
    /// 파일 확장자 (.pcm 또는 .raw)
    private var fileExtension: String = ".raw"
    
    /// 샘플 레이트 (Hz)
    private let sampleRate: Int
    
    /// 채널 수 (모노 = 1)
    private let channels: Int
    
    /// 컨트롤러 약한 참조 (이벤트 전송 및 암호화용)
    private weak var controller: AudioHelperController?
    
    /// 최대 세그먼트 수 (0 = unlimited)
    private var maxSegments: Int = 0
    
    // MARK: - Initialization
    
    /// SegmentManager 초기화
    /// - Parameters:
    ///   - controller: AudioHelperController 인스턴스
    ///   - sampleRate: 샘플 레이트 (Hz)
    ///   - channels: 채널 수 (기본값 1 = 모노)
    ///   - segmentDurationSeconds: 세그먼트 길이 (초, 기본값 180 = 3분)
    init(controller: AudioHelperController,
         sampleRate: Int,
         channels: Int = 1,
         segmentDurationSeconds: Int = 180) {
        self.controller = controller
        self.sampleRate = sampleRate
        self.channels = channels
        self.segmentDurationSamples = UInt64(segmentDurationSeconds * sampleRate * channels)
        self.minSegmentSamples = UInt64(1 * sampleRate * channels) // 1초
        
        // 버퍼 예약 (성능 최적화)
        self.segmentBuffer.reserveCapacity(Int(segmentDurationSamples))
    }
    
    deinit {
        // 남은 데이터 정리
        if currentSegmentSamples > 0 {
            finalizeCurrentSegment()
        }
    }
    
    // MARK: - Configuration
    
    /// 출력 디렉토리 설정
    func setOutputDirectory(_ url: URL) {
        self.outputDirectory = url
    }
    
    /// 세션 ID 설정
    func setSessionId(_ id: String) {
        self.sessionId = id
    }
    
    /// 암호화 활성화 여부 설정
    func setEncryptionEnabled(_ enabled: Bool) {
        self.encryptionEnabled = enabled
    }
    
    /// 파일 확장자 설정
    func setFileExtension(_ ext: String) {
        var fileExt = ext
        if !fileExt.isEmpty && !fileExt.hasPrefix(".") {
            fileExt = "." + fileExt
        }
        self.fileExtension = fileExt
    }
    
    /// 최대 세그먼트 수 설정 (0 = unlimited)
    func setMaxSegments(_ max: Int) {
        self.maxSegments = max
    }
    
    // MARK: - Sample Management
    
    /// 샘플 추가 (믹싱된 Int16 모노 샘플)
    /// - Parameter samples: 추가할 샘플 배열
    /// - Returns: 세그먼트가 완료되어 저장되었으면 true
    func addSamples(_ samples: [Int16]) -> Bool {
        guard !samples.isEmpty else { return false }
        
        var segmentCompleted = false
        
        // 버퍼에 샘플 추가
        segmentBuffer.append(contentsOf: samples)
        currentSegmentSamples += UInt64(samples.count)
        
        // 세그먼트 완료 체크
        if currentSegmentSamples >= segmentDurationSamples {
            saveSegment()
            
            // 다음 세그먼트 준비
            segmentBuffer.removeAll(keepingCapacity: true)
            currentSegmentSamples = 0
            segmentIndex += 1
            segmentCompleted = true
            
            // 최대 세그먼트 도달 체크 (Windows Helper와 동일: MAX_SEGMENTS=60)
            if maxSegments > 0 && segmentIndex >= maxSegments {
                FileLogger.shared.log(.info, category: "segment", 
                                    message: "Max segments reached", 
                                    metadata: ["index": segmentIndex, "max": maxSegments])
                controller?.requestStopAtBoundary()  // controller에게 정지 요청
            }
        }
        
        return segmentCompleted
    }
    
    /// 현재 세그먼트 완료 및 저장
    func finalizeCurrentSegment() {
        guard currentSegmentSamples > 0 else { return }
        
        // 최소 길이 체크 (1초 미만은 저장 안 함)
        if currentSegmentSamples < minSegmentSamples {
            FileLogger.shared.log(.debug, category: "segment",
                                message: "Segment too short, discarding",
                                metadata: ["samples": currentSegmentSamples])
            discardCurrentSegment()
            return
        }
        
        saveSegment()
        
        // 버퍼 정리
        segmentBuffer.removeAll(keepingCapacity: false)
        currentSegmentSamples = 0
    }
    
    /// 현재 세그먼트 폐기 (저장하지 않음)
    func discardCurrentSegment() {
        // 보안: 메모리 제로화
        for i in 0..<segmentBuffer.count {
            segmentBuffer[i] = 0
        }
        segmentBuffer.removeAll(keepingCapacity: false)
        currentSegmentSamples = 0
    }
    
    /// 상태 리셋 (새 녹음 시작 시)
    func reset() {
        // 보안: 메모리 제로화
        for i in 0..<segmentBuffer.count {
            segmentBuffer[i] = 0
        }
        segmentBuffer.removeAll(keepingCapacity: false)
        currentSegmentSamples = 0
        segmentIndex = 0
    }
    
    /// 현재 세그먼트에 대기 중인 샘플이 있는지 여부
    func hasPendingSamples() -> Bool {
        return currentSegmentSamples > 0
    }
    
    // MARK: - Private Methods
    
    /// 현재 세그먼트를 파일로 저장
    private func saveSegment() {
        guard !segmentBuffer.isEmpty else { return }
        guard let outputDir = outputDirectory else {
            FileLogger.shared.log(.error, category: "segment",
                                message: "Output directory not set")
            return
        }
        
        do {
            // 파일 경로 생성
            let filePath = generateSegmentPath(in: outputDir)
            
            // Int16 배열 → Data 변환
            let rawData = Data(bytes: segmentBuffer, count: segmentBuffer.count * MemoryLayout<Int16>.size)
            
            // 암호화 여부에 따라 저장
            if encryptionEnabled {
                do {
                    try encryptAndSave(data: rawData, to: filePath)
                } catch let encryptError as NSError {
                    // 암호화 실패 시 세그먼트 파일이 생성되었다면 삭제 (보안)
                    if FileManager.default.fileExists(atPath: filePath.path) {
                        try? FileManager.default.removeItem(at: filePath)
                    }
                    controller?.postEvent(.errorCode(
                        code: "ENCRYPT_FAILED",
                        message: "암호화 실패로 세그먼트를 저장할 수 없습니다: \(encryptError.localizedDescription)"
                    ))
                    FileLogger.shared.log(.error, category: "segment",
                                        message: "Encryption failed: \(encryptError)")
                    throw encryptError
                }
            } else {
                // 평문 저장
                do {
                    try rawData.write(to: filePath, options: .atomic)
                } catch let writeError as CocoaError {
                    // 파일 쓰기 실패 세분화
                    let errorCode: String
                    let errorMessage: String
                    
                    switch writeError.code {
                    case .fileWriteNoPermission, .fileNoSuchFile:
                        errorCode = "DISK_WRITE_OPEN_FAILED"
                        errorMessage = "세그먼트 파일을 열 수 없습니다: \(writeError.localizedDescription)"
                    case .fileWriteOutOfSpace:
                        errorCode = "DISK_SPACE_LOW_STOP"
                        errorMessage = "디스크 여유 공간 부족으로 세그먼트를 저장할 수 없습니다."
                    default:
                        errorCode = "SEGMENT_SAVE_FAILED"
                        errorMessage = "세그먼트 저장 실패: \(writeError.localizedDescription)"
                    }
                    
                    controller?.postEvent(.errorCode(code: errorCode, message: errorMessage))
                    FileLogger.shared.log(.error, category: "segment",
                                        message: "File write failed: \(writeError)",
                                        metadata: ["errorCode": errorCode])
                    throw writeError
                } catch {
                    // 기타 쓰기 오류
                    controller?.postEvent(.errorCode(
                        code: "SEGMENT_SAVE_FAILED",
                        message: "세그먼트 저장 실패: \(error.localizedDescription)"
                    ))
                    FileLogger.shared.log(.error, category: "segment",
                                        message: "File write failed: \(error)")
                    throw error
                }
            }
            
            // 파일 크기 확인
            let attributes = try FileManager.default.attributesOfItem(atPath: filePath.path)
            let sizeBytes = (attributes[.size] as? NSNumber)?.intValue ?? 0
            
            // 지속 시간 계산 (밀리초)
            let durationMs = Int((Double(currentSegmentSamples) / Double(sampleRate * channels)) * 1000.0)
            
            // segment_ready 이벤트 전송
            controller?.postEvent(.segmentReady(
                index: segmentIndex,
                path: filePath.path,
                samples: Int(currentSegmentSamples),
                durationMs: durationMs,
                sizeBytes: sizeBytes,
                encrypted: encryptionEnabled
            ))
            
            FileLogger.shared.log(.info, category: "segment",
                                message: "Segment saved",
                                metadata: [
                                    "index": segmentIndex,
                                    "samples": currentSegmentSamples,
                                    "durationMs": durationMs,
                                    "sizeBytes": sizeBytes,
                                    "encrypted": encryptionEnabled
                                ])
            
        } catch {
            // 최상위 catch - 이미 위에서 구체적인 에러를 전송했으므로 여기서는 로그만
            FileLogger.shared.log(.error, category: "segment",
                                message: "Segment save failed (final catch): \(error)")
        }
    }
    
    /// 세그먼트 파일 경로 생성 (중복 처리 포함)
    private func generateSegmentPath(in directory: URL) -> URL {
        var filename = "\(sessionId)_\(segmentIndex)\(fileExtension)"
        var filePath = directory.appendingPathComponent(filename)
        
        // 중복 파일명 처리: sessionId_n.ext → sessionId(m)_n.ext
        var duplicateIndex = 1
        while FileManager.default.fileExists(atPath: filePath.path) {
            filename = "\(sessionId)(\(duplicateIndex))_\(segmentIndex)\(fileExtension)"
            filePath = directory.appendingPathComponent(filename)
            duplicateIndex += 1
        }
        
        return filePath
    }
    
    /// 데이터 암호화 후 저장
    private func encryptAndSave(data: Data, to url: URL) throws {
        guard let controller = controller else {
            throw NSError(domain: "segment", code: -1,
                         userInfo: [NSLocalizedDescriptionKey: "Controller reference lost"])
        }
        
        // AudioHelperController의 암호화 메서드 사용
        let encryptedData: Data
        do {
            encryptedData = try controller.encryptAES256CBC(data: data)
        } catch {
            FileLogger.shared.log(.error, category: "segment",
                                message: "AES encryption failed: \(error)")
            throw error
        }
        
        // 파일 저장 (쓰기 오류 세분화)
        do {
            try encryptedData.write(to: url, options: .atomic)
        } catch let writeError as CocoaError {
            // 암호화된 파일 쓰기 실패 처리
            let errorCode: String
            let errorMessage: String
            
            switch writeError.code {
            case .fileWriteNoPermission, .fileNoSuchFile:
                errorCode = "DISK_WRITE_OPEN_FAILED"
                errorMessage = "암호화된 세그먼트 파일을 열 수 없습니다: \(writeError.localizedDescription)"
            case .fileWriteOutOfSpace:
                errorCode = "DISK_SPACE_LOW_STOP"
                errorMessage = "디스크 여유 공간 부족으로 암호화된 세그먼트를 저장할 수 없습니다."
            default:
                errorCode = "SEGMENT_SAVE_FAILED"
                errorMessage = "암호화된 세그먼트 저장 실패: \(writeError.localizedDescription)"
            }
            
            controller.postEvent(.errorCode(code: errorCode, message: errorMessage))
            FileLogger.shared.log(.error, category: "segment",
                                message: "Encrypted file write failed: \(writeError)",
                                metadata: ["errorCode": errorCode])
            throw writeError
        }
        
        FileLogger.shared.log(.debug, category: "segment",
                            message: "Segment encrypted and saved",
                            metadata: [
                                "originalSize": data.count,
                                "encryptedSize": encryptedData.count
                            ])
    }
}

// MARK: - AudioHelperController Extension (암호화 접근용)
@available(macOS 15.0, *)
extension AudioHelperController {
    /// SegmentManager가 암호화 메서드에 접근할 수 있도록 internal로 노출
    func encryptAES256CBC(data: Data) throws -> Data {
        let keyString = "b7671acf046542c4848d6162ee9733cc"
        let ivString = "baf766f829f8489a"
        
        guard let keyData = keyString.data(using: .utf8),
              let ivData = ivString.data(using: .utf8) else {
            throw NSError(domain: "encryption", code: -1,
                         userInfo: [NSLocalizedDescriptionKey: "Failed to encode key/iv as UTF-8"])
        }
        
        let keyBytes = Array(keyData)
        let ivBytes = Array(ivData)
        let dataBytes = Array(data)
        
        let aes = try AES(key: keyBytes, blockMode: CBC(iv: ivBytes), padding: .pkcs7)
        let encryptedBytes = try aes.encrypt(dataBytes)
        
        return Data(encryptedBytes)
    }
}

