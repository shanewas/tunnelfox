@echo off
setlocal
title System Startup Helper

:: ============================================================
::  TunnelFox ? Session Teardown
::  Terminates browser, SSH tunnel, and flushes DNS cache.
:: ============================================================

echo.
echo [1/3] Terminating TunnelFox Browser...
taskkill /f /im NotepadHelper.exe 2>nul
taskkill /f /im QtWebEngineProcess.exe 2>nul

echo [2/3] Terminating SSH tunnel...
taskkill /f /im ssh.exe 2>nul

echo [3/3] Flushing DNS cache...
ipconfig /flushdns >nul

echo.
echo  All processes cleared. DNS cache flushed.
echo.
timeout /t 2 >nul
exit