@echo off
setlocal
cd /d "%~dp0"
if not exist ".git" (
  echo To jest kopia z Download ZIP, bez historii Git.
  echo Aby otrzymywac aktualizacje bez ponownego pobierania ZIP:
  echo 1. Zainstaluj Git for Windows.
  echo 2. W nowym folderze wykonaj:
  echo    git clone https://github.com/wskakuj/GeoStudio.git
  echo 3. Uruchom setup_windows.bat w pobranym repozytorium.
  pause
  exit /b 1
)
where git >nul 2>nul
if errorlevel 1 (
  echo Brak narzedzia Git. Zainstaluj Git for Windows.
  pause
  exit /b 1
)
rem Do not discard local edits, do not force-push or reset.
git pull --ff-only origin main
if errorlevel 1 (
  echo Nie udalo sie zaktualizowac bezpiecznie. Sprawdz: git status
  pause
  exit /b 1
)
call "%~dp0setup_windows.bat"
