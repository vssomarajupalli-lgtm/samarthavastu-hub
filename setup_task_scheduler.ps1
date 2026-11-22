# PowerShell script to create/update Windows Task Scheduler for auto_publisher.py
# Run as Administrator

$ErrorActionPreference = "Stop"

$TaskName = "SamarthaVastu_AutoPublisher"
$ScriptPath = "E:\samarthavastu-hubuto_publisher.py"
$PythonExe = (Get-Command python).Source  # Use current python from PATH
$WorkingDir = "E:\samarthavastu-hub"

# Delete existing task if it exists
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Deleted existing task: $TaskName"
}

# Create action with FULL python path and working directory
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "auto_publisher.py --daily-run" -WorkingDirectory $WorkingDir

# Trigger 1: At Logon (with 2-minute delay for Wi-Fi)
$Trigger1 = New-ScheduledTaskTrigger -AtLogOn
$Trigger1.Delay = "PT2M"

# Trigger 2: Daily from 07:05 AM repeating every 1 hour indefinitely
$Trigger2 = New-ScheduledTaskTrigger -Once -At "07:05" -RepetitionInterval (New-TimeSpan -Hours 1)

# Settings: PowerShell 5.1 compatible
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable

# Principal: Run in INTERACTIVE desktop session (NOT Session 0)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

# Register task with Principal
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($Trigger1, $Trigger2) -Settings $Settings -Principal $Principal -Description "Samartha Vastu Auto Publisher - runs in interactive desktop session from 07:05 AM every hour, plus at logon with 2-min delay" -Force

Write-Host "Task '$TaskName' created successfully!"
Write-Host "Triggers:"
Write-Host "  1. At Logon (with 2-minute delay)"
Write-Host "  2. Daily at 07:05 AM, repeating every 1 hour"
Write-Host "Settings: StartWhenAvailable=True, AllowStartIfOnBatteries=True, DontStopIfGoingOnBatteries=True"
Write-Host "Principal: $env:USERDOMAIN\$env:USERNAME (Interactive, Limited)"

# Verify
$task = Get-ScheduledTask -TaskName $TaskName
$task.Triggers
$task.Principal
