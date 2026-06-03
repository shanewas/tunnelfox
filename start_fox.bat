@echo off
setlocal EnableDelayedExpansion
title System Startup Helper

:: ============================================================
::  TunnelFox — Session Launcher
::  Reads config, starts ssh -D tunnel with retry/polling,
::  then launches the disguised browser.
::  Run from repo root after BUILD.bat has completed.
:: ============================================================

:: --- Read config.ini ---
set "CONFIG=.\config.ini"
if not exist "%CONFIG%" (
    echo  [ERROR] config.ini not found in current directory.
    pause & exit /b 1
)

for /f "usebackq tokens=1,2 delims==" %%A in ("%CONFIG%") do (
    set "key=%%A"
    set "val=%%B"
    
    :: Remove leading/trailing spaces from key and value
    for /f "tokens=* delims= " %%k in ("!key!") do set "key=%%k"
    for /f "tokens=* delims= " %%v in ("!val!") do set "val=%%v"
    set "key=!key: =!"

    if /i "!key!"=="vm_ip"      set "VM_IP=!val!"
    if /i "!key!"=="key_path"   set "KEY_PATH=!val!"
    if /i "!key!"=="vm_user"    set "VM_USER=!val!"
    if /i "!key!"=="local_port" set "LOCAL_PORT=!val!"
    if /i "!key!"=="app_name"   set "APP_NAME=!val!"
)

:: --- Defaults if not set ---
if not defined LOCAL_PORT set "LOCAL_PORT=1080"
if not defined APP_NAME   set "APP_NAME=NotepadHelper"

:: --- Validate ---
if not defined VM_IP (
    echo  [ERROR] vm_ip not found in config.ini
    pause & exit /b 1
)
if not defined KEY_PATH (
    echo  [ERROR] key_path not found in config.ini
    pause & exit /b 1
)
if not defined VM_USER (
    echo  [ERROR] vm_user not found in config.ini
    pause & exit /b 1
)
if not exist "%KEY_PATH%" (
    echo  [ERROR] Key file not found: %KEY_PATH%
    pause & exit /b 1
)

set "EXE_PATH=.\dist\%APP_NAME%\%APP_NAME%.exe"

echo.
echo [1/3] Cleaning existing sessions...
taskkill /f /im "%APP_NAME%.exe" 2>nul
taskkill /f /im ssh.exe           2>nul
timeout /t 1 /nobreak >nul

echo [2/3] Initialising secure tunnel...
echo       %VM_USER%@%VM_IP%  (SOCKS5 -> 127.0.0.1:%LOCAL_PORT%)
start /b "" ssh ^
    -i "%KEY_PATH%" ^
    -D %LOCAL_PORT% ^
    -N ^
    -o ExitOnForwardFailure=yes ^
    -o ServerAliveInterval=60 ^
    -o StrictHostKeyChecking=no ^
    -o IdentitiesOnly=no ^
    %VM_USER%@%VM_IP%

:: --- Wait for SOCKS5 listener with backoff (more reliable than fixed sleep) ---
echo [3/3] Waiting for tunnel to become ready on port %LOCAL_PORT%...
set "MAX_WAIT=20"
set "WAITED=0"
:wait_loop
timeout /t 1 /nobreak >nul
set /a WAITED+=1

:: Use PowerShell to test TCP listener (portable on Win10/11, no extra tools)
powershell -NoProfile -Command ^
    "$c=New-Object System.Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', %LOCAL_PORT%); $c.Close(); exit 0 } catch { exit 1 }" ^
    >nul 2>&1

if %errorlevel% equ 0 (
    echo       Tunnel listener detected after !WAITED!s.
    goto tunnel_ready
)

if !WAITED! lss %MAX_WAIT% (
    <nul set /p ="."
    goto wait_loop
)

echo.
echo  [WARN] Tunnel did not open port %LOCAL_PORT% after %MAX_WAIT%s.
echo         The browser will likely fail the preflight check.
echo         You can try running start_tunnel.bat manually for verbose output.
echo.

:tunnel_ready

if not exist "%EXE_PATH%" (
    echo.
    echo  [ERROR] Executable not found: %EXE_PATH%
    echo          Run BUILD.bat first.
    echo.
    pause & exit /b 1
)

echo Launching TunnelFox...
start "" "%EXE_PATH%"

echo.
echo  TunnelFox active. Tunnel on port %LOCAL_PORT%. Safe browsing engaged.
timeout /t 2 /nobreak >nul
exit