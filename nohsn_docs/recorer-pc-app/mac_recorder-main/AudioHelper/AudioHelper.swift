//
//  main.swift
//  AudioHelper
//
//  Created by 장준호 on 10/23/25.
//

import Foundation
import os


@main
struct AudioHelper {
    static func main() {
        let controller = AudioHelperController()

        FileLogger.shared.log(.info, category: "bootstrap", message: "AudioHelper starting")

        // helper_info: 앱 시작 직후 1회 전송 (Windows 동작과 정렬)
        // Bundle에서 버전 정보 읽기
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.1.0"
        
        let df = DateFormatter()
        df.locale = Locale(identifier: "en_US_POSIX")
        df.dateFormat = "MMM dd yyyy"
        let buildDate = df.string(from: Date())
        
        controller.postEvent(.helperInfo(utf8: true, version: version, webrtc_aec: false, build_date: buildDate))
        
        // 장치 변경 감지를 Helper 시작 시 등록 (녹음/테스트/대기 모든 상태에서 감지)
        controller.startDeviceObservers()
        FileLogger.shared.log(.info, category: "bootstrap", message: "Device observers registered")

        // NDJSON (한 줄에 하나의 JSON 명령) - 버퍼링하여 개행 단위로 안전 파싱
        var stdinBuffer = ""
        FileHandle.standardInput.readabilityHandler = { handle in
            guard let chunk = String(data: handle.availableData, encoding: .utf8), !chunk.isEmpty else { return }
            stdinBuffer.append(chunk)
            // CRLF 정규화
            stdinBuffer = stdinBuffer.replacingOccurrences(of: "\r\n", with: "\n")
            while let nlRange = stdinBuffer.range(of: "\n") {
                let line = String(stdinBuffer[..<nlRange.lowerBound]).trimmingCharacters(in: .whitespacesAndNewlines)
                stdinBuffer.removeSubrange(..<nlRange.upperBound)
                if line.isEmpty { continue }
                guard let data = line.data(using: .utf8) else { continue }
                do {
                    let cmd = try JSONDecoder().decode(Command.self, from: data)
                    Task { await controller.handle(cmd) }
                } catch {
                    controller.postEvent(.errorCode(code: "JSON_PARSE_ERROR", message: "\(error)"))
                }
            }
        }

        // 앱이 살아있도록 RunLoop 유지
        RunLoop.current.run()
    }
}


