//
//  FileLogger.swift
//  AudioHelper
//
//  Creates JSON-lines file logs with size-based rotation and OSLog bridging.
//

import Foundation
import os

@available(macOS 12.0, *)
enum LogLevel: String, Comparable {
    case trace, debug, info, warn, error

    static func < (lhs: LogLevel, rhs: LogLevel) -> Bool {
        return Self.rank(lhs) < Self.rank(rhs)
    }
    private static func rank(_ v: LogLevel) -> Int {
        switch v {
        case .trace: return 0
        case .debug: return 1
        case .info:  return 2
        case .warn:  return 3
        case .error: return 4
        }
    }
}

@available(macOS 12.0, *)
final class FileLogger {
    static let shared = FileLogger()

    private let queue = DispatchQueue(label: "audiohelper.logger.queue")
    private var fileHandle: FileHandle?
    private var currentSize: UInt64 = 0

    private var logDirectoryURL: URL
    private var logFileURL: URL
    private let fileBaseName = "AudioHelper.log"
    private let maxFileBytes: UInt64 = 5 * 1024 * 1024
    private let maxFiles: Int = 5

    private var level: LogLevel = .info
    private let osLogger: Logger

    private init() {
        let bundleId = Bundle.main.bundleIdentifier ?? "AudioHelper"
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent(bundleId).appendingPathComponent("Logs")
        self.logDirectoryURL = dir
        self.logFileURL = dir.appendingPathComponent(fileBaseName)
        self.osLogger = Logger(subsystem: bundleId, category: "default")
        setupIfNeeded()
        // Ensure flushing on process exit
        atexit_b {
            FileLogger.shared.flushAndClose()
        }
    }

    func setLevel(_ new: LogLevel) {
        queue.async { self.level = new }
    }

    func setDirectory(_ url: URL) {
        queue.async {
            // Reject app bundle path
            if url.path.hasPrefix(Bundle.main.bundlePath) { return }
            self.flushAndClose()
            self.logDirectoryURL = url
            self.logFileURL = url.appendingPathComponent(self.fileBaseName)
            self.setupIfNeeded()
        }
    }

    func directoryURL() -> URL { return logDirectoryURL }

    func log(_ level: LogLevel, category: String, message: String, metadata: [String: Any] = [:]) {
        queue.async {
            if level < self.level { return }

            // Bridge to OSLog
            switch level {
            case .error: self.osLogger.error("\(category): \(message, privacy: .public)")
            case .warn:  self.osLogger.warning("\(category): \(message, privacy: .public)")
            case .info:  self.osLogger.info("\(category): \(message, privacy: .public)")
            case .debug: self.osLogger.debug("\(category): \(message, privacy: .public)")
            case .trace: self.osLogger.trace("\(category): \(message, privacy: .public)")
            }

            // JSON line
            var dict: [String: Any] = [
                "ts": Self.iso8601String(Date()),
                "level": level.rawValue,
                "category": category,
                "message": message,
                "pid": getpid()
            ]
            if !metadata.isEmpty { dict["metadata"] = metadata }
            guard let data = try? JSONSerialization.data(withJSONObject: dict) else { return }
            var line = data; line.append(0x0A)

            if self.currentSize + UInt64(line.count) > self.maxFileBytes { self.rotate() }
            do {
                try self.fileHandle?.write(contentsOf: line)
                self.currentSize &+= UInt64(line.count)
            } catch {
                // Try reopen once
                self.setupIfNeeded()
            }
        }
    }

    func flushAndClose() {
        do { try queue.sync { try self.fileHandle?.synchronize(); try self.fileHandle?.close(); self.fileHandle = nil } } catch {}
    }

    // MARK: - Private
    private func setupIfNeeded() {
        do {
            try FileManager.default.createDirectory(at: logDirectoryURL, withIntermediateDirectories: true)
            var rv = URLResourceValues(); rv.isExcludedFromBackup = true
            try? logDirectoryURL.setResourceValues(rv)
            if !FileManager.default.fileExists(atPath: logFileURL.path) {
                FileManager.default.createFile(atPath: logFileURL.path, contents: nil)
            }
            self.fileHandle = try FileHandle(forWritingTo: logFileURL)
            if let fh = self.fileHandle {
                do { try fh.seekToEnd() } catch {}
            }
            let attrs = try FileManager.default.attributesOfItem(atPath: logFileURL.path)
            self.currentSize = (attrs[.size] as? NSNumber)?.uint64Value ?? 0
        } catch {
            // Fallback: attempt under temporary directory
            let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("AudioHelperLogs")
            try? FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
            self.logDirectoryURL = tmp
            self.logFileURL = tmp.appendingPathComponent(fileBaseName)
            FileManager.default.createFile(atPath: logFileURL.path, contents: nil)
            self.fileHandle = try? FileHandle(forWritingTo: logFileURL)
            if let fh = self.fileHandle {
                do { try fh.seekToEnd() } catch {}
            }
            self.currentSize = 0
        }
    }

    private func rotate() {
        do { try fileHandle?.close() } catch {}
        let fm = FileManager.default
        let oldest = logDirectoryURL.appendingPathComponent("\(fileBaseName).\(maxFiles)")
        if fm.fileExists(atPath: oldest.path) { try? fm.removeItem(at: oldest) }
        if maxFiles > 1 {
            for i in stride(from: maxFiles - 1, through: 1, by: -1) {
                let src = logDirectoryURL.appendingPathComponent("\(fileBaseName).\(i)")
                let dst = logDirectoryURL.appendingPathComponent("\(fileBaseName).\(i+1)")
                if fm.fileExists(atPath: src.path) { try? fm.moveItem(at: src, to: dst) }
            }
            try? fm.moveItem(at: logFileURL, to: logDirectoryURL.appendingPathComponent("\(fileBaseName).1"))
        } else {
            try? fm.removeItem(at: logFileURL)
        }
        fm.createFile(atPath: logFileURL.path, contents: nil)
        setupIfNeeded()
    }

    private static func iso8601String(_ date: Date) -> String {
        struct Holder { static let f: DateFormatter = {
            let f = DateFormatter()
            f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSZZZZZ"
            f.timeZone = TimeZone.current  // 로컬 시스템 시간대 사용
            f.locale = Locale(identifier: "en_US_POSIX")
            return f
        }() }
        return Holder.f.string(from: date)
    }
}


