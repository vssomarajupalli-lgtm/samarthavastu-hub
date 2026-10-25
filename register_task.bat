@echo off
REM ============================================================================
REM Samartha Vastu - Register Windows Scheduled Task (8:00 AM + Boot Catch-up)
REM Right-click and choose "Run as administrator"
REM ============================================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~dpnx0\"\"' -Verb RunAs"
    exit /b
)

echo Registering SamarthaVastu_Daily_8AM Scheduled Task...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_task.ps1"

echo.
echo ============================================================================
echo Task registration complete.
echo ============================================================================
pause
