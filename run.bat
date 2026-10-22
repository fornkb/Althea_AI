@echo off
setlocal
pushd "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
    echo Setting up Althea AI for the first time...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
    if errorlevel 1 goto failed
)
if /i "%~1"=="--check" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -Check
) else (
    echo Starting Althea AI. Keep this window open while using the app.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
)
if errorlevel 1 goto failed
popd
exit /b 0
:failed
echo.
echo Althea AI could not start. Check the message above, or run setup.ps1 again.
if /i not "%~1"=="--check" pause
popd
exit /b 1
