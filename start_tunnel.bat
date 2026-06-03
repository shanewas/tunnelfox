@echo off
setlocal EnableDelayedExpansion

:: --- CONFIGURATION ---
set "CONFIG=.\config.ini"
if not exist "%CONFIG%" (
    echo [ERROR] config.ini not found!
    pause & exit /b 1
)

:: Parse config.ini
for /f "usebackq tokens=1,2 delims==" %%A in ("%CONFIG%") do (
    set "key=%%A"
    set "val=%%B"
    for /f "tokens=* delims= " %%k in ("!key!") do set "key=%%k"
    for /f "tokens=* delims= " %%v in ("!val!") do set "val=%%v"
    set "key=!key: =!"
    if /i "!key!"=="vm_ip"     set "VM_IP=!val!"
    if /i "!key!"=="key_path"  set "KEY_PATH=!val!"
    if /i "!key!"=="vm_user"   set "VM_USER=!val!"
    if /i "!key!"=="local_port" set "LOCAL_PORT=!val!"
)

if not defined LOCAL_PORT set "LOCAL_PORT=1080"

:: --- CLEANUP ---
echo [1/2] Force-closing previous SSH instances...
:: We use /T to kill child processes and 2>nul to ignore "Process not found" errors
taskkill /f /t /im ssh.exe >nul 2>&1
timeout /t 1 /nobreak >nul

:: --- EXECUTION ---
echo [2/2] Attempting connection to %VM_IP%...
echo      Port: %LOCAL_PORT% ^| User: %VM_USER%
echo      Press Ctrl+C to close the tunnel.
echo ---------------------------------------------------

ssh -v -i "%KEY_PATH%" ^
    -D %LOCAL_PORT% ^
    -N ^
    -o ExitOnForwardFailure=yes ^
    -o ServerAliveInterval=60 ^
    -o ConnectTimeout=10 ^
    -o StrictHostKeyChecking=no ^
    -o IdentitiesOnly=no ^
    %VM_USER%@%VM_IP%

echo.
echo [INFO] SSH Session ended or failed to start.
pause