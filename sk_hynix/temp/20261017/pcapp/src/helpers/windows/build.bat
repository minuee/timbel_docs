@echo off
chcp 65001 >nul
echo Building Windows Audio Helper (Release)...

rem WebRTC library path setup (project internal)
set WEBRTC_ROOT=%~dp0..\..\..\WebRTCLib
set WEBRTC_INCLUDE_DIR=%WEBRTC_ROOT%\include
set WEBRTC_LIB_DIR=%WEBRTC_ROOT%\release

rem Check WebRTC library paths
if not exist "%WEBRTC_ROOT%" (
    echo ERROR: WebRTC root directory not found: %WEBRTC_ROOT%
    echo Please check WebRTCLib directory exists
    pause
    exit /b 1
)

if not exist "%WEBRTC_INCLUDE_DIR%" (
    echo ERROR: WebRTC include directory not found: %WEBRTC_INCLUDE_DIR%
    pause
    exit /b 1
)

if not exist "%WEBRTC_LIB_DIR%\webrtc.lib" (
    echo ERROR: WebRTC library not found: %WEBRTC_LIB_DIR%\webrtc.lib
    pause
    exit /b 1
)

rem Clean previous build
if exist build (
    echo Cleaning previous build...
    rmdir /s /q build
)

rem Create build directory
mkdir build
cd build

echo Configuring with CMake... (Release)
cmake .. -G "Visual Studio 17 2022" -A x64 ^
    -DUSE_WEBRTC_AEC=ON ^
    -DWEBRTC_APM_INCLUDE_DIR="%WEBRTC_INCLUDE_DIR%" ^
    -DWEBRTC_APM_LIB="%WEBRTC_LIB_DIR%\webrtc.lib"

if %ERRORLEVEL% neq 0 (
    echo CMake configuration failed!
    pause
    exit /b 1
)

echo Building... (Release)
cmake --build . --config Release

if %ERRORLEVEL% neq 0 (
    echo Build failed!
    pause
    exit /b 1
)

echo Copying executable... (Release)
copy Release\AudioHelper.exe ..\AudioHelper.exe

if %ERRORLEVEL% neq 0 (
    echo Failed to copy executable!
    pause
    exit /b 1
)

cd ..
echo Build completed successfully! (Release)
echo AudioHelper.exe is ready with WebRTC AEC enabled. (Release)
pause