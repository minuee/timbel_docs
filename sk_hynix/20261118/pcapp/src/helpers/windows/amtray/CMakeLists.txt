cmake_minimum_required(VERSION 3.16)
project(AmHelper CXX)

# AM-Tray(SSO) DLL 호출 중계 exe. 외부 라이브러리 없음.
# Mac 크로스 빌드: ./build-mingw.sh   /   회사 Windows(Visual Studio): build.bat

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(AmHelper AmHelper.cpp)
target_compile_definitions(AmHelper PRIVATE UNICODE _UNICODE NOMINMAX WIN32_LEAN_AND_MEAN)
target_link_libraries(AmHelper PRIVATE shell32)

if(MSVC)
    set_property(TARGET AmHelper PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    target_compile_options(AmHelper PRIVATE /utf-8 /W3)
elseif(MINGW)
    target_compile_options(AmHelper PRIVATE -Wall -Wextra -Wno-cast-function-type -finput-charset=UTF-8 -fexec-charset=UTF-8)
    # 런타임 DLL 없이 exe 하나로 돌도록 정적 링크
    target_link_options(AmHelper PRIVATE -static -static-libgcc -static-libstdc++)
endif()
