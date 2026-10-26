# register_task.ps1
# Registers SamarthaVastu_Daily_8AM scheduled task in Windows Task Scheduler

$TaskName = "SamarthaVastu_Daily_8AM"
$PythonExe = "C:\Users\vssom\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
$ScriptArg = "E:\samarthavastu-hub\auto_publisher.py --daily-run"
$WorkingDir = "E:\samarthavastu-hub"

# Define Action
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $ScriptArg -WorkingDirectory $WorkingDir

# Define Triggers:
# 1. Daily at 08:00 AM
$TriggerDaily = New-ScheduledTaskTrigger -Daily -At "08:00AM"

# 2. At Logon with 60s delay
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn
$TriggerLogon.Delay = 'PT1M'

# Define Settings:
# StartWhenAvailable ($true): if machine was off at 8:00 AM, task runs upon boot
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)

try {
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    $Task = Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($TriggerDaily, $TriggerLogon) -Settings $Settings -Principal $Principal -Description "Samartha Vastu Daily 8:00 AM and Boot Catch-up Auto Publisher" -Force
} catch {
    Write-Warning "Could not register with RunLevel Highest (requires Admin). Updating existing task with interactive settings..."
    Set-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $TriggerDaily -Settings $Settings
}

Write-Host "`nTask successfully registered:"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, Description
Get-ScheduledTaskInfo -TaskName $TaskName | Format-List
