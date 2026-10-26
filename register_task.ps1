# register_task.ps1
# Registers SamarthaVastu_Daily_8AM scheduled task in Windows Task Scheduler
# Includes:
#   1. Daily trigger at 08:00 AM, repeating every 1 hour for 16 hours
#   2. User Logon trigger with 45s delay
#   3. Battery restrictions removed (runs on AC or Battery)
#   4. StartWhenAvailable enabled (runs missed tasks immediately)
#   5. Interactive logon in user desktop session

$TaskName = "SamarthaVastu_Daily_8AM"
$PythonExe = "C:\Users\vssom\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
$ScriptArg = "E:\samarthavastu-hub\auto_publisher.py --daily-run"
$WorkingDir = "E:\samarthavastu-hub"

# Define Action
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $ScriptArg -WorkingDirectory $WorkingDir

# Define Repetition Pattern using a helper trigger
$Helper = New-ScheduledTaskTrigger -Once -At "08:00AM" -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 16)

# 1. Daily trigger at 08:00 AM with 16h hourly repetition
$TriggerDaily = New-ScheduledTaskTrigger -Daily -At "08:00AM"
$TriggerDaily.Repetition = $Helper.Repetition

# 2. At Logon trigger with 45s delay
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn
$TriggerLogon.Delay = 'PT45S'

# Define Settings:
# StartWhenAvailable ($true): if machine was off at 8:00 AM, task runs upon boot/logon
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($TriggerDaily, $TriggerLogon) -Settings $Settings -Principal $Principal -Description "Samartha Vastu Daily 8AM with 16h Hourly Catch-up and Logon Trigger" -Force -ErrorAction Stop | Out-Null
    Write-Host "Register-ScheduledTask registered task successfully."
} catch {
    Write-Error "Task registration failed: $_"
}

Write-Host "`nTask status:"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State
$TaskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "Next Run Time: $($TaskInfo.NextRunTime)"
Write-Host "Last Run Time: $($TaskInfo.LastRunTime)"
