cmake_minimum_required(VERSION 3.16)
project(AudioHelper)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# nlohmann/json 헤더만 포함 (헤더 온리 라이브러리)
# 기본: 이 폴더의 json.hpp(3.12.0)를 쓴다. 망분리 PC 에서는 GitHub 다운로드(FetchContent)가 막혀 있다.
# simple_json.hpp 가 <nlohmann/json.hpp> 로 include 하므로 빌드 폴더에 그 구조로 복사해 둔다.
option(AUDIOHELPER_FETCH_JSON "Download nlohmann/json from GitHub instead of bundled json.hpp" OFF)
if(AUDIOHELPER_FETCH_JSON)
    include(FetchContent)
    FetchContent_Declare(json URL https://github.com/nlohmann/json/releases/download/v3.11.2/json.tar.xz)
    FetchContent_MakeAvailable(json)
else()
    configure_file(${CMAKE_CURRENT_SOURCE_DIR}/json.hpp ${CMAKE_CURRENT_BINARY_DIR}/bundled/include/nlohmann/json.hpp COPYONLY)
    add_library(nlohmann_json INTERFACE)
    target_include_directories(nlohmann_json INTERFACE ${CMAKE_CURRENT_BINARY_DIR}/bundled/include)
    add_library(nlohmann_json::nlohmann_json ALIAS nlohmann_json)
endif()

# 실행 파일 생성
add_executable(AudioHelper
    main.cpp
    AudioHelper.cpp
    AudioHelper.h
    Logger.cpp
    Logger.h
    WavWriter.cpp
    WavWriter.h
)

if(MSVC)
    # 타겟에 MSVC 런타임을 정적으로 설정 (/MT, /MTd)
    set_property(TARGET AudioHelper PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

# WebRTC AEC 옵션 (선택)
option(USE_WEBRTC_AEC "Use WebRTC Audio Processing AEC" OFF)
if(USE_WEBRTC_AEC)
    if(DEFINED WEBRTC_APM_INCLUDE_DIR AND DEFINED WEBRTC_APM_LIB)
        message(STATUS "Building with WebRTC AEC (prebuilt library)")
        
        # WebRTC 헤더 경로 추가
        target_include_directories(AudioHelper PRIVATE ${WEBRTC_APM_INCLUDE_DIR})
        
        # Abseil 헤더 경로 (WebRTC에서 사용)
        if(EXISTS ${WEBRTC_APM_INCLUDE_DIR}/third_party/abseil-cpp)
            target_include_directories(AudioHelper PRIVATE ${WEBRTC_APM_INCLUDE_DIR}/third_party/abseil-cpp)
        endif()
        
        # WebRTC 라이브러리 링크
        target_link_libraries(AudioHelper PRIVATE ${WEBRTC_APM_LIB})
        
        # WebRTC 컴파일 정의
        target_compile_definitions(AudioHelper PRIVATE 
            WEBRTC_APM_AVAILABLE
            WEBRTC_WIN
            NOMINMAX
        )
        
        # WebRTC가 요구하는 시스템 라이브러리들
        target_link_libraries(AudioHelper PRIVATE 
            winmm
            ws2_32
            secur32
            dmoguids
            wmcodecdspuuid
            msdmo
            strmiids
        )
        
    else()
        message(WARNING "USE_WEBRTC_AEC=ON but WEBRTC_APM_INCLUDE_DIR/WEBRTC_APM_LIB not set; building without WebRTC AEC")
    endif()
endif()

# 링크 라이브러리
target_link_libraries(AudioHelper 
    PRIVATE 
    ole32
    oleaut32
    avrt
    nlohmann_json::nlohmann_json
)

# Windows 특정 설정
if(WIN32)
    # Unicode 지원
    target_compile_definitions(AudioHelper PRIVATE UNICODE _UNICODE NOMINMAX WIN32_LEAN_AND_MEAN)
    
    # UTF-8 컴파일 설정 (MSVC 전용 옵션. mingw 크로스 빌드는 아래 else 에서 처리)
    if(MSVC)
        target_compile_options(AudioHelper PRIVATE 
            /utf-8           # UTF-8 소스 파일 처리
            /W3             # 경고 레벨 3으로 줄임 (4는 너무 많은 경고)
        )
    endif()
    
    # MSVC 런타임을 정적(/MT)으로 설정하여 WebRTC 산출물과 일치시킴
    if(MSVC)
        set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    endif()

    # 릴리스 모드에서 콘솔 설정 (MSVC 링커 옵션)
    if(MSVC AND CMAKE_BUILD_TYPE STREQUAL "Release")
        set_target_properties(AudioHelper PROPERTIES
            WIN32_EXECUTABLE TRUE
            LINK_FLAGS "/SUBSYSTEM:CONSOLE"
        )
    endif()
endif()

# 컴파일러별 설정
if(MSVC)
    # MSVC 특정 옵션
    target_compile_options(AudioHelper PRIVATE 
        /bigobj          # 큰 오브젝트 파일 지원
    )
else()
    target_compile_options(AudioHelper PRIVATE -Wall -Wextra)
    # mingw 크로스 빌드(Mac → Windows): 런타임 DLL 없이 exe 하나로 돌도록 정적 링크
    if(MINGW)
        target_compile_options(AudioHelper PRIVATE -finput-charset=UTF-8 -fexec-charset=UTF-8)
        target_link_options(AudioHelper PRIVATE -static -static-libgcc -static-libstdc++)
        # MSVC 는 소스의 #pragma comment(lib) 로 붙지만 mingw 는 무시하므로 직접 링크
        target_link_libraries(AudioHelper PRIVATE bcrypt winmm uuid)
    endif()
endif()