@echo off
setlocal
title TunnelFox Diagnostics

:: ============================================================
::  TunnelFox — Diagnostics Launcher
::  Runs the Python diagnostics script with clear output.
::  Double-click this file or run from cmd.
:: ============================================================

echo.
echo  TunnelFox Tunnel Diagnostics
echo  =============================
echo.

:: Try to find a usable Python
set "PYTHON=python"
where python >nul 2>&1
if %errorlevel% neq 0 (
    set "PYTHON=py"
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Python not found.
        echo         Please install Python 3.11+ and add it to PATH.
        echo.
        pause
        exit /b 1
    )
)

:: Run the diagnostics script (same directory)
"%PYTHON%" "%~dp0diagnose_tunnel.py"

echo.
echo  Diagnostics script finished.
pause
exit /b 0
