#pragma once

#include <string>
#include <mutex>
#include <fstream>
#include <vector>

// 로그는 영어, 주석은 한글
// 요구사항: 연-월-일 시:분:초, 파일명, 라인 포함 + 10MB 회전, 최대 5개 보관

enum class LogLevel {
    Debug = 0,
    Info  = 1,
    Warn  = 2,
    Error = 3,
    Critical = 4
};

class Logger {
public:
    static Logger& instance();

    // 로그 출력
    void log(LogLevel level, const char* file, int line, const std::string& message);

    // 최소 출력 레벨 설정/조회 (level 미만은 파일에 쓰지 않음)
    void setMinLevel(LogLevel level);
    LogLevel getMinLevel() const;

    // 로그 디렉터리 지정(선택) – 지정 없으면 실행 파일 경로 사용
    void setLogDirectory(const std::wstring& directory);

private:
    Logger();
    ~Logger();
    Logger(const Logger&) = delete;
    Logger& operator=(const Logger&) = delete;

    std::wstring computeDefaultLogPath() const; // AudioHelper.log 위치
    void openIfNeeded();
    void rotateIfNeededLocked();
    std::string formatPrefix(LogLevel level, const char* file, int line) const;

private:
    std::mutex mutex_;
    std::wstring logDirectory_; // 디렉터리 경로
    std::wstring logPath_;      // 파일 전체 경로(AudioHelper.log)
    std::ofstream stream_;
    LogLevel minLevel_;

    static constexpr size_t kMaxBytes = 10 * 1024 * 1024; // 10MB
    static constexpr int kMaxBackups = 5;                 // 최대 5개
};

#define LOG_INFO(msg)  Logger::instance().log(LogLevel::Info,  __FILE__, __LINE__, (msg))
#define LOG_WARN(msg)  Logger::instance().log(LogLevel::Warn,  __FILE__, __LINE__, (msg))
#define LOG_ERROR(msg) Logger::instance().log(LogLevel::Error, __FILE__, __LINE__, (msg))
#define LOG_DEBUG(msg) Logger::instance().log(LogLevel::Debug, __FILE__, __LINE__, (msg))
#define LOG_CRITICAL(msg) Logger::instance().log(LogLevel::Critical, __FILE__, __LINE__, (msg))
// #define _DEBUG_LOG


