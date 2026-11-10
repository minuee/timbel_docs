#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <fstream>
#include <mutex>

// 간단 WAV 파일 작성기 (PCM S16LE, mono)
class WavWriter {
public:
    WavWriter();
    ~WavWriter();

    bool open(const std::wstring& path, uint32_t sampleRate, uint16_t channels = 1, uint16_t bitsPerSample = 16);
    void writeSamples(const int16_t* samples, size_t count);
    void close();

private:
    void writeHeader();
    void finalizeHeader();

private:
    std::ofstream stream_;
    std::mutex mutex_;
    uint32_t sampleRate_ = 16000;
    uint16_t channels_ = 1;
    uint16_t bitsPerSample_ = 16;
    uint32_t dataBytes_ = 0;
    bool opened_ = false;
};



