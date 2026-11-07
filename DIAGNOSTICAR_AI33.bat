@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Execute este arquivo na pasta do MPT, onde ficam webui.bat e .venv.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "scripts\diagnose_ai33.py" %*
echo.
pause
