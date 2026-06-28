<#
.SYNOPSIS
    Remove the DeepSeek API Task Scheduler task and stop the running process.

.EXAMPLE
    .\unregister-startup.ps1
#>

$TaskName = "DeepSeekAPI"
$Port     = if ($env:PORT) { $env:PORT } else { "8000" }

# Stop running process on the port
$pid = (netstat -ano 2>$null | Select-String ":${Port}\s.*LISTENING" | ForEach-Object {
    ($_ -split '\s+')[-1]
}) | Select-Object -First 1
if ($pid) {
    Write-Host "Stopping process on port $Port (PID $pid)..." -ForegroundColor Cyan
    Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue
}

# Remove scheduled task
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Task '$TaskName' removed." -ForegroundColor Green
} else {
    Write-Host "Task '$TaskName' not found." -ForegroundColor Yellow
}
