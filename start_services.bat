@echo off
setlocal

set "ROOT=%~dp0"
set "UV_EXE="

where uv >nul 2>&1
if not errorlevel 1 set "UV_EXE=uv"
if not defined UV_EXE if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" set "UV_EXE=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
if not defined UV_EXE if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV_EXE if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UV_EXE=%USERPROFILE%\.cargo\bin\uv.exe"

if not defined UV_EXE (
    echo [WARN] uv was not found. Trying the official installer...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
    if not defined UV_EXE (
        echo [ERROR] uv installation failed. Install it from https://docs.astral.sh/uv/
        pause
        exit /b 1
    )
)

if not exist "%ROOT%pyproject.toml" (
    echo [ERROR] pyproject.toml was not found. Run this file from the project folder.
    pause
    exit /b 1
)

set "UV_CACHE_DIR=%ROOT%.uv-cache"

if not exist "%ROOT%.env" (
    echo [ERROR] Required project configuration .env was not found.
    pause
    exit /b 1
)

echo [INFO] Installing or updating Python 3.11...
"%UV_EXE%" python find 3.11 >nul 2>&1
if errorlevel 1 "%UV_EXE%" python install 3.11
if errorlevel 1 (
    echo [ERROR] Could not install Python 3.11 through uv.
    pause
    exit /b 1
)

echo [INFO] Syncing application and model dependencies...
"%UV_EXE%" sync --extra models
if errorlevel 1 (
    echo [ERROR] Model dependency installation failed.
    pause
    exit /b 1
)
echo [INFO] Checking and downloading model assets if needed...
"%UV_EXE%" run python scripts/bootstrap_models.py
if errorlevel 1 (
    echo [ERROR] Model setup is incomplete. Services were not started.
    pause
    exit /b 1
)

call :check_locate
if errorlevel 1 (
    call :check_port 9000
    if errorlevel 1 (
        echo [INFO] Starting Locate Anything 4bit CLI service on port 9000...
        start "Auto Cat Locate Anything" powershell.exe -NoProfile -NoExit -ExecutionPolicy Bypass -Command ^
            "Set-Location -LiteralPath '%ROOT%'; $env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'; & '%UV_EXE%' run python scripts/locate_anything_server.py --host 127.0.0.1 --port 9000"

        echo [INFO] Waiting for Locate Anything model to finish loading...
        powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
            "$deadline = (Get-Date).AddMinutes(10); do { try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:9000/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } } catch {}; Start-Sleep -Seconds 3 } while ((Get-Date) -lt $deadline); exit 1"
        if errorlevel 1 (
            echo [ERROR] Locate Anything service did not become healthy on port 9000.
            echo [ERROR] Check the Auto Cat Locate Anything service window for model errors.
            pause
            exit /b 1
        )
    ) else (
        echo [ERROR] Port 9000 is occupied, but Locate Anything health check failed.
        echo [ERROR] Stop the conflicting process, then run this script again.
        pause
        exit /b 1
    )
) else (
    echo [OK] Reusing healthy Locate Anything service on port 9000.
)

call :check_backend
if errorlevel 1 (
    call :check_port 8000
    if errorlevel 1 (
        echo [INFO] Starting Auto Cat backend...
        start "Auto Cat Backend" powershell.exe -NoProfile -NoExit -ExecutionPolicy Bypass -Command ^
            "Set-Location -LiteralPath '%ROOT%'; $env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'; & '%UV_EXE%' run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000"
        powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
            "$deadline = (Get-Date).AddMinutes(1); do { try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3; if ($r.status -eq 'ok' -and $r.runtime -eq 'local_models') { exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); exit 1"
        if errorlevel 1 (
            echo [ERROR] Backend did not become healthy on port 8000.
            pause
            exit /b 1
        )
    ) else (
        echo [ERROR] Port 8000 is occupied, but the Auto Cat backend health check failed.
        echo [ERROR] Stop the conflicting process, then run this script again.
        pause
        exit /b 1
    )
) else (
    echo [OK] Reusing healthy Auto Cat backend on port 8000.
)

call :check_frontend
if errorlevel 1 (
    call :check_port 5173
    if errorlevel 1 (
        echo [INFO] Starting Auto Cat frontend...
        start "Auto Cat Frontend" powershell.exe -NoProfile -NoExit -ExecutionPolicy Bypass -Command ^
            "Set-Location -LiteralPath '%ROOT%'; $env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'; & '%UV_EXE%' run python frontend/server.py"
        powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
            "$deadline = (Get-Date).AddSeconds(30); do { try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
        if errorlevel 1 (
            echo [ERROR] Frontend did not become healthy on port 5173.
            pause
            exit /b 1
        )
    ) else (
        echo [ERROR] Port 5173 is occupied, but the Auto Cat frontend health check failed.
        echo [ERROR] Stop the conflicting process, then run this script again.
        pause
        exit /b 1
    )
) else (
    echo [OK] Reusing healthy Auto Cat frontend on port 5173.
)

if not defined AUTO_CAT_NO_BROWSER start "" http://127.0.0.1:5173

echo [OK] Backend:  http://127.0.0.1:8000
echo [OK] Frontend: http://127.0.0.1:5173
echo [OK] Locate:   http://127.0.0.1:9000/v1/chat/completions
echo [OK] PixAI:    local ONNX model ready for Review Submit
echo [INFO] Running healthy services are reused when this script is launched again.
echo [INFO] To stop all Auto Cat services, double-click stop_services.bat.

endlocal
exit /b 0

:check_locate
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:9000/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%

:check_backend
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3; if ($r.status -eq 'ok' -and $r.runtime -eq 'local_models') { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%

:check_frontend
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%

:check_port
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$client = [Net.Sockets.TcpClient]::new(); try { $client.Connect('127.0.0.1', [int]'%~1'); exit 0 } catch { exit 1 } finally { $client.Dispose() }" >nul 2>&1
exit /b %errorlevel%
