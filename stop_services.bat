@echo off
setlocal

set "ROOT=%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent()); if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 0 } else { exit 1 }"

if errorlevel 1 (
    echo [INFO] Administrator permission is required to stop the service processes.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
        "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\stop_services.ps1"
if errorlevel 1 (
    echo.
    echo [WARN] Some ports were not stopped. Review the messages above.
) else (
    echo.
    echo [OK] Backend, frontend, and Locate Anything have been stopped.
)

pause
endlocal
