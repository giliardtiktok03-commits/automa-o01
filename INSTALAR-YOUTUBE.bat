@echo off
setlocal
cd /d "%~dp0"
set "_mpt_youtube_python="
if exist ".venv\Scripts\python.exe" set "_mpt_youtube_python=.venv\Scripts\python.exe"
if not defined _mpt_youtube_python if exist "venv\Scripts\python.exe" set "_mpt_youtube_python=venv\Scripts\python.exe"
if not defined _mpt_youtube_python (
  echo Ambiente Python do MPT nao encontrado. Execute na raiz do MPT.
  echo Use o Python do seu ambiente virtual para instalar requirements-youtube.txt.
  pause
  exit /b 1
)
"%_mpt_youtube_python%" -m pip install -r "%~dp0requirements-youtube.txt"
if errorlevel 1 (
  echo A instalacao falhou. Confira a mensagem acima antes de iniciar o MPT.
  pause
  exit /b 1
)
echo Dependencias YouTube instaladas. Inicie o MPT normalmente.
pause
