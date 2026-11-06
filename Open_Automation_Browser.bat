@echo off
REM ============================================================================
REM Samartha Vastu - Open Automation Browser (Chrome CDP on port 9222)
REM Launches Chrome with the isolated automation profile for manual browsing.
REM Keep this browser open - it stays alive for subsequent automation runs.
REM ============================================================================

set "CHROME_BIN=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_BIN%" (
    set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
)
if not exist "%CHROME_BIN%" (
    set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

echo [Open Automation Browser] Launching Chrome with CDP on port 9222...
echo [Open Automation Browser] Profile: E:\samarthavastu-hub\chrome_whatsapp_profile
echo.

start "" "%CHROME_BIN%" --remote-debugging-port=9222 --user-data-dir="E:\samarthavastu-hub\chrome_whatsapp_profile" --no-first-run --no-default-browser-check "https://studio.youtube.com" "https://web.whatsapp.com/"

echo.
echo [Open Automation Browser] Chrome launched on port 9222.
echo [Open Automation Browser] YouTube Studio and WhatsApp Web tabs are open.
echo [Open Automation Browser] Keep this browser window open for automation runs.
echo.

timeout /t 5 /nobreak
