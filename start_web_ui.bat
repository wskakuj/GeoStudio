@echo off
setlocal
cd /d "%~dp0"
echo.
echo  ========================================
echo   GeoStudio 2.0 - testowy interfejs WWW
echo   Oryginalny GeoStudio pozostaje bez zmian
echo  ========================================
echo.
set "PYTHON=%~dp0.venv-web\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [1/3] Tworzenie osobnego srodowiska GeoStudio 2.0...
  py -3 -m venv .venv-web
  if errorlevel 1 (
    echo Nie udalo sie utworzyc .venv-web. Zainstaluj Python 3.11+.
    pause
    exit /b 1
  )
)
"%PYTHON%" -c "import fastapi, uvicorn, webview, shapely, PIL, reportlab" >nul 2>&1
if errorlevel 1 (
  echo [2/3] Jednorazowa instalacja zaleznosci web UI...
  "%PYTHON%" -m pip install --disable-pip-version-check -e ".[web]"
  if errorlevel 1 (
    echo Instalacja nie powiodla sie. Sprawdz polaczenie z internetem.
    pause
    exit /b 1
  )
)
echo [3/3] Uruchamianie GeoStudio 2.0...
"%PYTHON%" -m geostudio.web_app %*
if errorlevel 1 (
  echo.
  echo Nie udalo sie uruchomic okna.
  echo Wariant w przegladarce: start_web_ui.bat --browser
  pause
  exit /b 1
)
endlocal
