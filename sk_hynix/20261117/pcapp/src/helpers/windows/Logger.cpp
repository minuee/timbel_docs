#include "Logger.h"

#include <Windows.h>
#include <ShlObj.h>
#include <filesystem>
#include <chrono>
#include <iomanip>
#include <sstream>

namespace fs = std::filesystem;

// 간단한 유틸: wstring → string(UTF-8)
static std::string WStringToUtf8(const std::wstring& w) {
    if (w.empty()) return std::string();
    int size_needed = WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), nullptr, 0, nullptr, nullptr);
    std::string result;
    result.resize(size_needed);
    WideCharToMultiByte(CP_UTF8, 0, w.data(), (int)w.size(), result.data(), size_needed, nullptr, nullptr);
    return result;
}

Logger& Logger::instance() {
    static Logger inst;
    return inst;
}

Logger::Logger() {
    logPath_ = computeDefaultLogPath();
    // 기본 최소 레벨: _DEBUG_LOG 정의 시 Info, 미정의 시 Warn
#ifdef _DEBUG_LOG
    minLevel_ = LogLevel::Info;
#else
    minLevel_ = LogLevel::Warn;
#endif
}

Logger::~Logger() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (stream_.is_open()) stream_.close();
}

void Logger::setLogDirectory(const std::wstring& directory) {
    std::lock_guard<std::mutex> lock(mutex_);
    logDirectory_ = directory;
    logPath_ = (fs::path(directory) / L"AudioHelper.log").wstring();
    if (stream_.is_open()) stream_.close();
}

std::wstring Logger::computeDefaultLogPath() const {
    wchar_t modulePath[MAX_PATH] = {0};
    GetModuleFileNameW(nullptr, modulePath, MAX_PATH);
    fs::path p = fs::path(modulePath).parent_path() / L"AudioHelper.log";
    return p.wstring();
}

void Logger::openIfNeeded() {
    if (!stream_.is_open()) {
        fs::create_directories(fs::path(logPath_).parent_path());
        stream_.open(fs::path(logPath_), std::ios::out | std::ios::app | std::ios::binary); // fs::path: MSVC·mingw 공통(C++17)
    }
}

void Logger::rotateIfNeededLocked() {
    try {
        if (!fs::exists(logPath_)) return;
        const auto size = fs::file_size(logPath_);
        if (size < kMaxBytes) return;

        // 오래된 것 삭제(최대 kMaxBackups 유지)
        for (int i = kMaxBackups; i >= 1; --i) {
            fs::path src = fs::path(logPath_).parent_path() / (L"AudioHelper.log." + std::to_wstring(i));
            fs::path dst = fs::path(logPath_).parent_path() / (L"AudioHelper.log." + std::to_wstring(i + 1));
            if (i == kMaxBackups && fs::exists(src)) {
                std::error_code ec; fs::remove(src, ec);
            }
            if (fs::exists(src)) {
                std::error_code ec; fs::rename(src, dst, ec);
            }
        }

        // AudioHelper.log → AudioHelper.log.1
        {
            std::error_code ec;
            fs::path first = fs::path(logPath_).parent_path() / L"AudioHelper.log.1";
            if (stream_.is_open()) stream_.close();
            fs::rename(logPath_, first, ec);
        }
    } catch (...) {
        // 회전 중 예외는 무시
    }
}

std::string Logger::formatPrefix(LogLevel level, const char* file, int line) const {
    // yyyy-mm-dd hh:mm:ss 레벨 파일:라인
    auto now = std::chrono::system_clock::now();
    std::time_t t = std::chrono::system_clock::to_time_t(now);
    std::tm tm{};
    localtime_s(&tm, &t);
    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
    oss << " ";
    switch (level) {
        case LogLevel::Debug:    oss << "DEBUG"; break;
        case LogLevel::Info:     oss << "INFO"; break;
        case LogLevel::Warn:     oss << "WARN"; break;
        case LogLevel::Error:    oss << "ERROR"; break;
        case LogLevel::Critical: oss << "CRITICAL"; break;
    }
    oss << " ";
    oss << file << ":" << line;
    oss << " - ";
    return oss.str();
}

void Logger::log(LogLevel level, const char* file, int line, const std::string& message) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (static_cast<int>(level) < static_cast<int>(minLevel_)) {
        return; // 설정된 최소 레벨 미만은 무시
    }
    openIfNeeded();
    rotateIfNeededLocked();

    const std::string prefix = formatPrefix(level, file, line);
    stream_ << prefix << message << "\n";
    stream_.flush();
}

void Logger::setMinLevel(LogLevel level) {
    std::lock_guard<std::mutex> lock(mutex_);
    minLevel_ = level;
}

LogLevel Logger::getMinLevel() const {
    return minLevel_;
}



