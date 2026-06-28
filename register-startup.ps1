<#
.SYNOPSIS
    Register DeepSeek API as a Windows Task Scheduler task that runs at logon.
    No admin rights required.

.EXAMPLE
    .\register-startup.ps1
#>

$TaskName   = "DeepSeekAPI"
$RepoDir    = $PSScriptRoot
$StartupPs1 = Join-Path $RepoDir "startup.ps1"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartupPs1`"" -WorkingDirectory $RepoDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT10S"

$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Start DeepSeek API server (http://127.0.0.1:8000) at logon" | Out-Null

Write-Host "Task '$TaskName' registered." -ForegroundColor Green
Write-Host "  Runs at:   logon of $env:USERNAME (+ 10 s delay)"
Write-Host "  Script:    $StartupPs1"
Write-Host "  Logs:      $RepoDir\logs\app.log"
Write-Host ""
Write-Host "Starting now for immediate test..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 8

$state = (Get-ScheduledTask -TaskName $TaskName).State
Write-Host "Task state: $state"

try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz" -UseBasicParsing -TimeoutSec 10
    Write-Host "Health check: $($r.Content)" -ForegroundColor Green
} catch {
    Write-Host "Health check failed - check logs\app-error.log" -ForegroundColor Yellow
    Get-Content (Join-Path $RepoDir "logs\app-error.log") -Tail 15 -ErrorAction SilentlyContinue
}
