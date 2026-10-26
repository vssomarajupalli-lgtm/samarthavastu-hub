Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c timeout /t 45 /nobreak >nul && powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""E:\samarthavastu-hub\run_daily.ps1""", 0, False
