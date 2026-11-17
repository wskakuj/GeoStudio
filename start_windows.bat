@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Brak srodowiska .venv. Postepuj zgodnie z README.md
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m geostudio
if errorlevel 1 pause
