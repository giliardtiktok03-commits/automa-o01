@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if not errorlevel 1 (
    uv sync --frozen
    if errorlevel 1 goto failed
    goto ready
)
py -m uv --version >nul 2>nul
if not errorlevel 1 (
    py -m uv sync --frozen
    if errorlevel 1 goto failed
    goto ready
)
python -m uv --version >nul 2>nul
if not errorlevel 1 (
    python -m uv sync --frozen
    if errorlevel 1 goto failed
    goto ready
)
echo Instale Python e uv antes de continuar.
echo Com Python instalado, execute: py -m pip install --user uv
pause
exit /b 1
:failed
echo A instalacao falhou. Guarde a mensagem exibida acima.
pause
exit /b 1
:ready
echo Ambiente preparado. Agora abra webui.bat nesta pasta.
pause
exit /b 0
