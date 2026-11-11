@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%"
echo AUTOPILOT - worker de pesquisa, roteiro e recuperacao.
echo Configure os canais e ative o AUTOPILOT no painel do MPT.
echo Este worker nao publica videos. Para encerrar, pressione Ctrl+C.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m app.services.autopilot
    exit /b
)
if exist "lib\python\python.exe" (
    "lib\python\python.exe" -m app.services.autopilot
    exit /b
)
where uv >nul 2>nul
if not errorlevel 1 (
    uv run python -m app.services.autopilot
    exit /b
)
echo Python do projeto nao encontrado. Use o mesmo ambiente do MPT.
pause
exit /b 1
