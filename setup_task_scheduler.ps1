# PowerShell script to create/update Windows Task Scheduler for auto_publisher.py
# Run as Administrator

$TaskName = "SamarthaVastu_AutoPublisher"
$ScriptPath = "E:\samarthavastu-hubuto_publisher.py"
$PythonExe = (Get-Command python).Source  # Use current python from PATH
$WorkingDir = "E:\samarthavastu-hub"

# Delete existing task if it exists
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Deleted existing task: $TaskName"
}

# Create action
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "--daily-run" -WorkingDirectory $WorkingDir

# Trigger 1: At Logon (with 2-minute delay for Wi-Fi)
$Trigger1 = New-ScheduledTaskTrigger -AtLogOn -Delay "00:02:00"

# Trigger 2: Daily at 07:05 AM, repeating every 1 hour indefinitely
$Trigger2 = New-ScheduledTaskTrigger -Daily -At "07:05" -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration ([TimeSpan]::MaxValue)

# Settings
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DisallowStartIfOnBatteries:$false `
    -StopIfGoingOnBatteries:$false `
    -AllowStartIfOnBatteries `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -Hidden `
    -RunOnlyIfNetworkAvailable

# Register task
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger1, $Trigger2 -Settings $Settings -Description "Samartha Vastu Auto Publisher - runs daily from 07:05 AM every hour, plus at logon with 2-min delay" -Force

Write-Host "Task '$TaskName' created successfully!"
Write-Host "Triggers:"
Write-Host "  1. At Logon (with 2-minute delay)"
Write-Host "  2. Daily at 07:05 AM, repeating every 1 hour"
Write-Host "Settings: StartWhenAvailable=True, DisallowStartIfOnBatteries=False"

# Verify
$task = Get-ScheduledTask -TaskName $TaskName
$task.Triggers
