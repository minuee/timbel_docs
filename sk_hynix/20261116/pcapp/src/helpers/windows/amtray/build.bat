@echo off
chcp 65001 >nul
rem 회사 Windows(Visual Studio + CMake)에서 AmHelper.exe 빌드. 보통은 집에서 만든 bin\AmHelper.exe 를 그대로 쓰면 된다.
rem 결과: bin\AmHelper.exe
cd /d %~dp0
if exist build rmdir /s /q build
cmake -S . -B build -A x64
if errorlevel 1 exit /b 1
cmake --build build --config Release
if errorlevel 1 exit /b 1
if not exist bin mkdir bin
copy /y build\Release\AmHelper.exe bin\AmHelper.exe
echo Done: %~dp0bin\AmHelper.exe
