@echo off
title Samartha Vastu - Daily Auto Publisher
color 0A
cd /d E:\samarthavastu-hub
echo ============================================================================
echo   SAMARTHA VASTU - DAILY AUTO PUBLISHER & CATCH-UP
echo ============================================================================
echo.
echo Running daily publishing cycle...
echo.
"C:\Users\vssom\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" auto_publisher.py --daily-run
echo.
echo ============================================================================
echo   Execution finished. Check logs above or in logs\daily_run.log.
echo ============================================================================
echo.
pause
