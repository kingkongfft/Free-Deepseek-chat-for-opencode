<#
.SYNOPSIS
    Wrapper launched by Task Scheduler at logon.
    Activates the venv and starts app.py in the background.
    Logs to logs\startup.log in the repo directory.
#>

$RepoDir   = $PSScriptRoot
$PythonExe = Join-Path $RepoDir "venv\Scripts\python.exe"
$AppPy     = Join-Path $RepoDir "app.py"
$LogDir    = Join-Path $RepoDir "logs"
$LogFile   = Join-Path $LogDir  "startup.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Load .env if present
$EnvFile = Join-Path $RepoDir ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
        $parts = $_ -split '=', 2
        [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
    }
}

# Default env if not set by .env
if (-not $env:HOST)  { $env:HOST  = "127.0.0.1" }
if (-not $env:PORT)  { $env:PORT  = "8000" }

# Kill any existing instance — try Get-NetTCPConnection first (reliable),
# fall back to netstat parsing (works across session boundaries).
$portPid = $null
try {
    $conn = Get-NetTCPConnection -LocalPort ([int]$env:PORT) -ErrorAction SilentlyContinue
    if ($conn) { $portPid = $conn.OwningProcess | Select-Object -First 1 }
} catch {}
if (-not $portPid) {
    $portPid = (netstat -ano 2>$null | Select-String ":$($env:PORT)\s.*LISTENING" | ForEach-Object {
        ($_ -split '\s+')[-1]
    }) | Select-Object -First 1
}
if ($portPid) {
    Stop-Process -Id ([int]$portPid) -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

# Start app.py, redirect output to log file
"[$(Get-Date)] Starting DeepSeek API on $($env:HOST):$($env:PORT)" | Out-File $LogFile -Append
$proc = Start-Process `
    -FilePath       $PythonExe `
    -ArgumentList   $AppPy `
    -WorkingDirectory $RepoDir `
    -RedirectStandardOutput (Join-Path $LogDir "app.log") `
    -RedirectStandardError  (Join-Path $LogDir "app-error.log") `
    -WindowStyle    Hidden `
    -PassThru

"[$(Get-Date)] Started PID $($proc.Id)" | Out-File $LogFile -Append
