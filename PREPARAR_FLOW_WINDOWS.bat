@echo off
setlocal
cd /d "%~dp0"
set "FLOW_PY="
if exist ".venv\Scripts\python.exe" set FLOW_PY="%CD%\.venv\Scripts\python.exe"
if not defined FLOW_PY if exist "lib\python\python.exe" set FLOW_PY="%CD%\lib\python\python.exe"
if not defined FLOW_PY (
 echo Primeiro prepare o MPT e seu ambiente Python. Nenhum Python do projeto foi encontrado.
 pause
 exit /b 1
)
where uv >nul 2>nul
if not errorlevel 1 (
 uv pip install --python %FLOW_PY% -r requirements-flow.txt
) else (
 %FLOW_PY% -m pip install -r requirements-flow.txt
)
if errorlevel 1 (
 echo Falha ao instalar Playwright. Confira o erro acima.
 pause
 exit /b 1
)
echo Pronto. Requer Google Chrome instalado. Reabra webui.bat e escolha Google Flow no modo misto.
echo Esta integracao usa o navegador visivel e login manual. Nao instala navegador nem copia senhas.
pause
