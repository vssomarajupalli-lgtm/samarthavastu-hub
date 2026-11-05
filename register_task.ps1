# register_task.ps1
# Registers SamarthaVastu_Daily_8AM scheduled task in Windows Task Scheduler
#
# Triggers:
#   1. AtLogOn trigger for current user (runs on every boot/logon)
#      - No hourly repetition, no 1-hour polling
#      - Runs once per logon session
#   2. Optional Daily trigger at 06:00 AM (NO repetition)
#      - Only fires if PC stayed on overnight and is already logged in at 6 AM
#
# Settings:
#   - StartWhenAvailable: runs missed tasks immediately on boot/logon
#   - Battery restrictions removed (runs on AC or Battery)
#   - Interactive logon in user desktop session
#   - Execution time limit: 1 hour

$TaskName = "SamarthaVastu_Daily_8AM"
$PythonExe = "C:\Users\vssom\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
$ScriptArg = "E:\samarthavastu-hub\auto_publisher.py --daily-run"
$WorkingDir = "E:\samarthavastu-hub"

# Define Action
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $ScriptArg -WorkingDirectory $WorkingDir

# Trigger 1: At Logon trigger for current user (runs on every boot/logon)
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn
$TriggerLogon.Delay = 'PT45S'

# Trigger 2: Optional Daily trigger at 06:00 AM with ZERO repetition
# (only fires if PC is already on and logged in at 6 AM)
$TriggerDaily = New-ScheduledTaskTrigger -Daily -At "06:00AM"
# No Repetition set - runs once at 06:00 AM only

# Define Settings:
# StartWhenAvailable: runs missed tasks immediately on boot/logon
# AllowStartIfOnBatteries / DontStopIfGoingOnBatteries: runs on AC or Battery
# ExecutionTimeLimit: 1 hour max
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($TriggerLogon, $TriggerDaily) -Settings $Settings -Principal $Principal -Description "Samartha Vastu Daily - Logon trigger with optional 06:00 AM trigger, NO hourly polling" -Force -ErrorAction Stop | Out-Null
    Write-Host "Register-ScheduledTask registered task successfully."
} catch {
    Write-Error "Task registration failed: $_"
}

Write-Host "`nTask status:"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State
$TaskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "Next Run Time: $($TaskInfo.NextRunTime)"
Write-Host "Last Run Time: $($TaskInfo.LastRunTime)"

# Verify repetition settings
Write-Host "`nRepetition settings:"
$task = Get-ScheduledTask -TaskName $TaskName
foreach ($tr in $task.Triggers) {
    Write-Host "  Trigger: $($tr.GetType().Name)"
    Write-Host "    Enabled: $($tr.Enabled)"
    if ($tr.Repetition) {
        Write-Host "    Repetition Interval: $($tr.Repetition.Interval)"
        Write-Host "    Repetition Duration: $($tr.Repetition.Duration)"
    } else {
        Write-Host "    Repetition: None (no hourly polling)"
    }
}
