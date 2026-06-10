@echo off
echo.
echo ============================================
echo  Apple Health Converter -- Build Script
echo ============================================
echo.

REM Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH. Please install Python 3.11+
    pause
    exit /b 1
)

REM Install PyInstaller if needed
echo [1/3] Installing PyInstaller...
pip install pyinstaller>=6.0 --quiet

REM Clean previous build artifacts
echo [2/3] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

REM Build the exe
echo [3/3] Building standalone exe...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "AppleHealthConverter" ^
    --add-data "writers.py;." ^
    --add-data "parser.py;." ^
    main.py

echo.
if exist dist\AppleHealthConverter.exe (
    echo SUCCESS! Executable created at:
    echo   dist\AppleHealthConverter.exe
    echo.
    echo You can now distribute AppleHealthConverter.exe standalone.
    echo No Python installation required on the target machine.
) else (
    echo BUILD FAILED. Check output above for errors.
)
echo.
pause
