# run_daily.ps1
# Runner for Samartha Vastu 2-Stage Daily Auto Publisher
# Handles working directory and launches the Python engine (which manages its own logs)

$ErrorActionPreference = "Continue"
$WorkspaceDir = "E:\samarthavastu-hub"
$PythonExe = "C:\Users\vssom\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"

Set-Location -Path $WorkspaceDir

& $PythonExe "$WorkspaceDir\auto_publisher.py" --daily-run
