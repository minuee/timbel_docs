#include "WavWriter.h"
#include <filesystem>

namespace fs = std::filesystem;

static void writeLE(std::ofstream& s, uint32_t v) {
    s.put(static_cast<char>(v & 0xFF));
    s.put(static_cast<char>((v >> 8) & 0xFF));
    s.put(static_cast<char>((v >> 16) & 0xFF));
    s.put(static_cast<char>((v >> 24) & 0xFF));
}

static void writeLE16(std::ofstream& s, uint16_t v) {
    s.put(static_cast<char>(v & 0xFF));
    s.put(static_cast<char>((v >> 8) & 0xFF));
}

WavWriter::WavWriter() {}
WavWriter::~WavWriter() { close(); }

bool WavWriter::open(const std::wstring& path, uint32_t sampleRate, uint16_t channels, uint16_t bitsPerSample) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (opened_) return true;
    fs::create_directories(fs::path(path).parent_path());
    stream_.open(fs::path(path), std::ios::binary | std::ios::out); // fs::path: MSVC·mingw 공통(C++17)
    if (!stream_.is_open()) return false;
    sampleRate_ = sampleRate;
    channels_ = channels;
    bitsPerSample_ = bitsPerSample;
    dataBytes_ = 0;
    writeHeader();
    opened_ = true;
    return true;
}

void WavWriter::writeSamples(const int16_t* samples, size_t count) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!opened_) return;
    stream_.write(reinterpret_cast<const char*>(samples), static_cast<std::streamsize>(count * sizeof(int16_t)));
    dataBytes_ += static_cast<uint32_t>(count * sizeof(int16_t));
    stream_.flush();
}

void WavWriter::close() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!opened_) return;
    finalizeHeader();
    stream_.close();
    opened_ = false;
}

void WavWriter::writeHeader() {
    // RIFF header placeholder
    stream_.write("RIFF", 4);
    writeLE(stream_, 36); // placeholder, updated on close
    stream_.write("WAVE", 4);

    // fmt chunk
    stream_.write("fmt ", 4);
    writeLE(stream_, 16);                 // PCM chunk size
    writeLE16(stream_, 1);                // Audio format PCM
    writeLE16(stream_, channels_);
    writeLE(stream_, sampleRate_);
    uint32_t byteRate = sampleRate_ * channels_ * (bitsPerSample_ / 8);
    writeLE(stream_, byteRate);
    uint16_t blockAlign = channels_ * (bitsPerSample_ / 8);
    writeLE16(stream_, blockAlign);
    writeLE16(stream_, bitsPerSample_);

    // data chunk header
    stream_.write("data", 4);
    writeLE(stream_, 0); // placeholder
}

void WavWriter::finalizeHeader() {
    if (!opened_) return;
    auto current = stream_.tellp();
    stream_.seekp(4, std::ios::beg);
    writeLE(stream_, 36 + dataBytes_);
    stream_.seekp(40, std::ios::beg);
    writeLE(stream_, dataBytes_);
    stream_.seekp(current, std::ios::beg);
    stream_.flush();
}



