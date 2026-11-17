@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Python 3.11+ nie jest dostepny. Zainstaluj Python dla Windows.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 (
  echo Instalacja bibliotek nie powiodla sie.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m geostudio
if errorlevel 1 pause
