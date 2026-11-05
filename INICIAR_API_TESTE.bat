@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Execute PREPARAR_TESTE_WINDOWS.bat primeiro.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py
pause
