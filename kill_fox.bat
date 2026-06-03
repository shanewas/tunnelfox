@echo off
setlocal EnableDelayedExpansion
title TunnelFox Teardown

:: ============================================================
::  TunnelFox — Session Teardown
::  Terminates browser (including renamed renderer), SSH tunnel,
::  and flushes DNS cache. Reads app_name from config.ini.
:: ============================================================

:: --- Read config.ini for app name (same logic as start_fox.bat) ---
set "CONFIG=.\config.ini"
set "APP_NAME=NotepadHelper"
if exist "%CONFIG%" (
    for /f "usebackq tokens=1,2 delims==" %%A in ("%CONFIG%") do (
        set "key=%%A"
        set "val=%%B"
        for /f "tokens=* delims= " %%k in ("!key!") do set "key=%%k"
        for /f "tokens=* delims= " %%v in ("!val!") do set "val=%%v"
        set "key=!key: =!"
        if /i "!key!"=="app_name" set "APP_NAME=!val!"
    )
)

echo.
echo [1/3] Terminating TunnelFox Browser (%APP_NAME%)...
taskkill /f /im "%APP_NAME%.exe" 2>nul
taskkill /f /im "%APP_NAME%_renderer.exe" 2>nul
taskkill /f /im "QtWebEngineProcess.exe" 2>nul

echo [2/3] Terminating SSH tunnel...
taskkill /f /im ssh.exe 2>nul

echo [3/3] Flushing DNS cache...
ipconfig /flushdns >nul

echo.
echo  All processes cleared. DNS cache flushed.
echo.
timeout /t 2 >nul
exit