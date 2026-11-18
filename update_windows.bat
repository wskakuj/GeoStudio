@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 goto failure

if not exist ".git" (
  echo Ta kopia GeoStudio nie ma historii Git ^(pobrana jako ZIP^).
  echo W nowym folderze uzyj: git clone https://github.com/wskakuj/GeoStudio.git
  echo Nastepnie uruchom setup_windows.bat.
  goto failure
)

where git >nul 2>nul
if errorlevel 1 (
  echo Nie znaleziono Git for Windows.
  goto failure
)

rem Do not silently stash, overwrite, merge, or discard local work.
rem Modified tracked files need an explicit user decision.
git diff --quiet --
if errorlevel 1 goto dirty
git diff --cached --quiet --
if errorlevel 1 goto dirty

rem The program update always follows main, not the last experimental branch.
set "current_branch="
for /f "delims=" %%B in ('git branch --show-current') do set "current_branch=%%B"
if not defined current_branch (
  echo HEAD jest odlaczony. Przejdz recznie na main po sprawdzeniu git status.
  goto failure
)
if /I not "%current_branch%"=="main" (
  echo Przelaczanie z %current_branch% na main...
  git switch main
  if errorlevel 1 (
    echo Nie mozna bezpiecznie przelaczyc na main.
    goto failure
  )
)

echo.
echo Pobieranie najnowszego main z GitHub...
git fetch origin main
if errorlevel 1 goto failure

rem Normal update: local HEAD is an ancestor of origin/main.
git merge-base --is-ancestor HEAD origin/main
if not errorlevel 1 goto fast_forward

rem Local-only commits with no remote updates: keep the branch intact.
git merge-base --is-ancestor origin/main HEAD
if not errorlevel 1 (
  echo Lokalny main zawiera dodatkowe commity, a origin/main nie ma nowszych.
  echo Niczego nie kasuje. Uruchamiam obecna lokalna wersje.
  goto run_program
)

rem Divergent history: automatically create a backup BEFORE offering reset.
echo.
echo UWAGA: lokalny main i origin/main maja rozna historie.
echo Lokalnych commitow nie wolno usuwac bez kopii.
set "stamp="
for /f "delims=" %%D in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "stamp=%%D"
if not defined stamp set "stamp=%RANDOM%-%RANDOM%"
set "backup_branch=backup/main-before-update-%stamp%"
git show-ref --verify --quiet "refs/heads/%backup_branch%"
if not errorlevel 1 set "backup_branch=%backup_branch%-%RANDOM%"
git branch "%backup_branch%" HEAD
if errorlevel 1 (
  echo Nie udalo sie zapisac kopii historii - NIE ruszam lokalnego main.
  goto failure
)
echo Zapisano lokalne commity w galezi: %backup_branch%
echo.
echo Mozesz odzyskac swoje commity z tej galezi.
echo Sprawdz je pozniej: git log --oneline main..%backup_branch%
echo.
echo Aby pobrac nowa wersje, trzeba przestawic lokalny main na origin/main.
echo Wykonane zostanie git reset --hard origin/main, ALE tylko po Twojej zgodzie.
echo Zmodyfikowane pliki sledzone przez Git zostaly sprawdzone: brak zmian.
choice /C TN /N /M "Czy przestawic lokalny main na GitHub? [T/N] "
if errorlevel 2 (
  echo Anulowano. Lokalna historia jest zachowana w %backup_branch%.
  goto failure
)
git reset --hard origin/main
if errorlevel 1 goto failure
echo Aktualizacja wykonana. Kopia dawnych commitow: %backup_branch%
goto run_program

:fast_forward
echo Aktualizacja fast-forward...
git merge --ff-only origin/main
if errorlevel 1 goto failure
goto run_program

:run_program
echo.
echo Uruchamiam instalator i GeoStudio...
call "%~dp0setup_windows.bat"
exit /b %errorlevel%

:dirty
echo.
echo W katalogu sa niezapisane lokalne zmiany plikow sledzonych przez Git.
echo Nie uruchamiam aktualizacji, aby ich nie uszkodzic.
git status --short
echo Zapisz zmiany, zrob commit albo odloz je do git stash.
goto failure

:failure
echo.
echo Aktualizacja przerwana bez nadpisania niezapisanych zmian.
echo Diagnostyka: git status ^& git log --oneline --left-right main...origin/main
pause
exit /b 1
