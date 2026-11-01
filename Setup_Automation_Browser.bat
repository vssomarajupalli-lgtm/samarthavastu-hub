@echo off
title Samartha Vastu - Setup Automation Chrome Profile
echo ============================================================================
echo   SAMARTHA VASTU - ISOLATED AUTOMATION BROWSER SETUP
echo ============================================================================
echo.
echo This will launch a dedicated Chrome instance with:
echo   User Data Dir: E:\samarthavastu-hub\chrome_whatsapp_profile
echo   Remote Debugging Port: 9222
echo   Tabs: https://web.whatsapp.com  https://studio.youtube.com
echo.
echo Please log into WhatsApp Web and YouTube Studio (@samarthavastu999) ONCE
echo inside this isolated profile. Subsequent automated runs will reuse this
echo profile and will never touch your personal Chrome browsers.
echo.
pause
echo.
echo Launching Chrome...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="E:\samarthavastu-hub\chrome_whatsapp_profile" --profile-directory=Default --remote-debugging-port=9222 "https://web.whatsapp.com" "https://studio.youtube.com/channel/UCDtcb0drjmLgG3ARTh4e7jw"
echo.
echo Chrome launched. Complete the logins above, then close this window.
echo The automation profile is now ready for use by youtube_shorts_uploader.py
echo and whatsapp_sender.py.
pause
