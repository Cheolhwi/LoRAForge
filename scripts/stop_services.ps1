param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$cleanProjectRoot = $ProjectRoot.Trim().Trim('"').TrimEnd("\")
$resolvedRoot = (Resolve-Path -LiteralPath $cleanProjectRoot).Path.TrimEnd("\")
$hadFailure = $false

function Get-ListeningProcessIds {
    param([int]$Port)

    $pattern = "^\s*TCP\s+127\.0\.0\.1:$Port\s+0\.0\.0\.0:0\s+LISTENING\s+(\d+)\s*$"
    $processIds = foreach ($line in (netstat -ano -p tcp)) {
        if ($line -match $pattern) {
            [int]$Matches[1]
        }
    }
    return @($processIds | Sort-Object -Unique)
}

function Test-ServiceHealth {
    param([string]$Name)

    try {
        if ($Name -eq "Backend") {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 3
            return $response.status -eq "ok"
        }
        if ($Name -eq "Locate Anything") {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:9000/health" -TimeoutSec 3
            return $response.status -eq "ok"
        }
        if ($Name -eq "Frontend") {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:5173/" -TimeoutSec 3 -UseBasicParsing
            return $response.StatusCode -eq 200 -and $response.Content -match "Auto Cat"
        }
    }
    catch {
        return $false
    }
    return $false
}

function Test-ProjectProcess {
    param(
        [int]$TargetProcessId,
        [string]$ExpectedToken
    )

    try {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $TargetProcessId"
        $commandLine = [string]$process.CommandLine
        return $commandLine -like "*$resolvedRoot*" -or $commandLine -match $ExpectedToken
    }
    catch {
        return $false
    }
}

$services = @(
    @{ Name = "Backend"; Port = 8000; Token = "uvicorn.+app\.main:app" },
    @{ Name = "Frontend"; Port = 5173; Token = "frontend[\\/]server\.py" },
    @{ Name = "Locate Anything"; Port = 9000; Token = "locate_anything_server\.py" }
)

foreach ($service in $services) {
    $processIds = @(Get-ListeningProcessIds -Port $service.Port)
    if ($processIds.Count -eq 0) {
        Write-Host "[OK] $($service.Name) is already stopped (port $($service.Port))."
        continue
    }

    $healthy = Test-ServiceHealth -Name $service.Name
    foreach ($processId in $processIds) {
        if (-not $healthy -and -not (Test-ProjectProcess -TargetProcessId $processId -ExpectedToken $service.Token)) {
            Write-Host "[WARN] Skipped PID $processId on port $($service.Port): it was not verified as an Auto Cat process."
            $hadFailure = $true
            continue
        }

        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "[OK] Stopped $($service.Name) (PID $processId, port $($service.Port))."
        }
        catch {
            Write-Host "[ERROR] Could not stop $($service.Name) PID $processId`: $($_.Exception.Message)"
            $hadFailure = $true
        }
    }
}

Start-Sleep -Milliseconds 500
foreach ($service in $services) {
    if (@(Get-ListeningProcessIds -Port $service.Port).Count -gt 0) {
        Write-Host "[WARN] Port $($service.Port) is still listening."
        $hadFailure = $true
    }
}

if ($hadFailure) {
    exit 1
}

Write-Host "[OK] Auto Cat services are stopped."
exit 0
