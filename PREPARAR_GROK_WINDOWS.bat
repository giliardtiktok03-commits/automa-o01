@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente do MPT nao encontrado. Prepare o MPT primeiro.
  pause
  exit /b 1
)
where uv >nul 2>nul
if not errorlevel 1 (
  uv pip install --python ".venv\Scripts\python.exe" "xai-sdk==1.21.0" "packaging==25.0"
) else (
  ".venv\Scripts\python.exe" -m ensurepip --upgrade
  ".venv\Scripts\python.exe" -m pip install "xai-sdk==1.21.0" "packaging==25.0"
)
if errorlevel 1 (
  echo Falha ao instalar o SDK xAI. Copie a mensagem de erro para revisao.
  pause
  exit /b 1
)
echo SDK oficial xAI instalado. Abra webui.bat e configure sua chave Grok.
pause
