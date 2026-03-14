@echo off
setlocal EnableDelayedExpansion
title TunnelFox - Local Build

:: ============================================================
::  TunnelFox v2.0 — Local Build Script
::  Run from the repo root. Output lands in .\dist\NotepadHelper\
::
::  CRITICAL: --contents-directory is intentionally ABSENT.
::  PyQtWebEngine's QtWebEngineProcess.exe resolves python3XX.dll
::  relative to its own directory. Relocating DLLs into a
::  subdirectory breaks that lookup and causes:
::    "Failed to start embedded python interpreter"
:: ============================================================

echo.
echo  TunnelFox Build System v2.0
echo  ============================
echo.

:: Read app name from config.ini
set "APP_NAME=NotepadHelper"
for /f "usebackq tokens=1,* delims= = " %%A in (".\config.ini") do (
    if /i "%%A"=="app_name" set "APP_NAME=%%B"
)

:: --- Clean ---
echo [1/5] Cleaning previous artifacts...
if exist ".\dist"       rd /s /q ".\dist"
if exist ".\build_temp" rd /s /q ".\build_temp"

:: --- Ensure assets folder + version file exist ---
echo [2/5] Preparing assets...
if not exist ".\assets" mkdir ".\assets"
if not exist ".\assets\file_version_info.txt" (
    set "VF=.\assets\file_version_info.txt"
    echo VSVersionInfo(                                                      > !VF!
    echo ffi=FixedFileInfo(                                                 >> !VF!
    echo filevers=(2, 0, 0, 0),                                            >> !VF!
    echo prodvers=(2, 0, 0, 0),                                            >> !VF!
    echo mask=0x3f,                                                         >> !VF!
    echo flags=0x0,                                                         >> !VF!
    echo OS=0x40004,                                                        >> !VF!
    echo fileType=0x1,                                                      >> !VF!
    echo subtype=0x0,                                                       >> !VF!
    echo date=(0, 0)                                                        >> !VF!
    echo ),                                                                 >> !VF!
    echo kids=[                                                             >> !VF!
    echo StringFileInfo(                                                    >> !VF!
    echo [StringTable(                                                      >> !VF!
    echo '040904B0',                                                        >> !VF!
    echo [StringStruct('CompanyName', 'Private'),                          >> !VF!
    echo StringStruct('FileDescription', 'Notepad Helper'),                >> !VF!
    echo StringStruct('FileVersion', '2.0.0.0'),                          >> !VF!
    echo StringStruct('InternalName', 'NotepadHelper'),                    >> !VF!
    echo StringStruct('OriginalFilename', 'NotepadHelper.exe'),            >> !VF!
    echo StringStruct('ProductName', 'Notepad Helper'),                    >> !VF!
    echo StringStruct('ProductVersion', '2.0.0.0')]                       >> !VF!
    echo )]                                                                 >> !VF!
    echo ),                                                                 >> !VF!
    echo VarFileInfo([VarStruct('Translation', [1033, 1200])])             >> !VF!
    echo ]                                                                  >> !VF!
    echo )                                                                  >> !VF!
    echo  [INFO] Created .\assets\file_version_info.txt
)

:: --- Validate environment ---
echo [3/5] Validating environment...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python not found. Install Python 3.11+ and add to PATH.
    pause & exit /b 1
)
pyinstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] PyInstaller not found. Run: pip install -r requirements.txt
    pause & exit /b 1
)
python -c "import PyQt6.QtWebEngineWidgets" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] PyQt6-WebEngine not found. Run: pip install PyQt6 PyQt6-WebEngine
    pause & exit /b 1
)

:: --- Build ---
echo [4/5] Building (this takes 2-5 minutes)...
echo.

pyinstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name="%APP_NAME%" ^
    --distpath=".\dist" ^
    --workpath=".\build_temp" ^
    --version-file=".\assets\file_version_info.txt" ^
    --collect-all PyQt6 ^
    --collect-all PyQt6-WebEngine ^
    --hidden-import="PyQt6.QtWebEngineWidgets" ^
    --hidden-import="PyQt6.QtWebEngineCore" ^
    --hidden-import="PyQt6.QtWebChannel" ^
    --hidden-import="PyQt6.QtNetwork" ^
    --hidden-import="PyQt6.QtPrintSupport" ^
    --add-data="config.ini;." ^
    .\src\tunnelfox.py

if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Build failed. See output above.
    pause & exit /b 1
)

:: --- Rename renderer process to blend in ---
echo [5/5] Finalising distribution...
if exist ".\dist\%APP_NAME%\QtWebEngineProcess.exe" (
    ren ".\dist\%APP_NAME%\QtWebEngineProcess.exe" "%APP_NAME%_renderer.exe"
    echo  [OK] QtWebEngineProcess.exe  ->  %APP_NAME%_renderer.exe
) else (
    echo  [WARN] QtWebEngineProcess.exe not found, skipping rename
)

echo.
echo  Build complete.
echo  Output : .\dist\%APP_NAME%\%APP_NAME%.exe
echo  Launch : start_fox.bat
echo.
pause