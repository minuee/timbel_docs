#pragma once
#include <string>
#include <sstream>
#include <nlohmann/json.hpp>

// nlohmann::json을 내부에 사용하면서, 기존 코드의 간단 API(set/contains/dump)와 호환되는 래퍼
class SimpleJson {
private:
    nlohmann::json j_;

public:
    SimpleJson() = default;
    explicit SimpleJson(const std::string& jsonStr) { parse(jsonStr); }

    void parse(const std::string& jsonStr) {
        try {
            j_ = nlohmann::json::parse(jsonStr);
        } catch (...) {
            j_ = nlohmann::json::object();
        }
    }

    static SimpleJson fromString(const std::string& jsonStr) {
        SimpleJson json; json.parse(jsonStr); return json;
    }

    std::string operator[](const std::string& key) const {
        if (!j_.contains(key)) return std::string();
        const auto& v = j_.at(key);
        if (v.is_string()) return v.get<std::string>();
        if (v.is_number_integer() || v.is_number_unsigned() || v.is_number_float()) return v.dump();
        if (v.is_boolean()) return v.get<bool>() ? "true" : "false";
        return v.dump();
    }

    bool contains(const std::string& key) const {
        return j_.contains(key);
    }

    std::string dump() const {
        return j_.dump();
    }

    // 값 설정
    void set(const std::string& key, const std::string& value) { j_[key] = value; }
    // 문자열 리터럴(const char*)이 bool 오버로드로 잘못 매칭되는 것을 방지
    void set(const std::string& key, const char* value) { j_[key] = value ? nlohmann::json(value) : nlohmann::json(""); }
    void set(const std::string& key, int value) { j_[key] = value; }
    void set(const std::string& key, double value) { j_[key] = value; }
    void set(const std::string& key, uint64_t value) { j_[key] = value; }
    void set(const std::string& key, bool value) { j_[key] = value; }

    // 배열 지원
    static SimpleJson array() {
        SimpleJson json; json.j_ = nlohmann::json::array(); return json;
    }
    void push_back(const SimpleJson& item) { j_.push_back(item.j_); }

    // 배열 접근 (간단 호환; 실제 사용은 드묾)
    SimpleJson& operator[](size_t index) {
        static SimpleJson tmp; tmp.j_ = (index < j_.size() ? j_.at(index) : nlohmann::json()); return tmp;
    }
    const SimpleJson& operator[](size_t index) const {
        static SimpleJson tmp; tmp.j_ = (index < j_.size() ? j_.at(index) : nlohmann::json()); return tmp;
    }

    size_t size() const { return j_.size(); }
};

using json = SimpleJson;