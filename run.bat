@echo off
rem Запуск фермы на Windows (то же, что run.sh на Mac/Linux).
rem Двойной клик по файлу или в терминале:  run.bat   (в PowerShell:  .\run.bat)
rem Первый запуск создаст виртуальное окружение и поставит зависимости.
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=python"
where %PY% >nul 2>nul || set "PY=py -3"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if errorlevel 1 (
  echo Нужен Python 3.10+. Установите с https://www.python.org/downloads/ ^(галочка «Add python.exe to PATH»^)
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo -^> Создаю виртуальное окружение...
  %PY% -m venv .venv || (pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  echo -^> Ставлю зависимости...
  ".venv\Scripts\python.exe" -m pip install --quiet -r backend\requirements.txt || (pause & exit /b 1)
)

where adb >nul 2>nul
if errorlevel 1 if not exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" (
  echo [!] adb не найден. Скачайте «SDK Platform-Tools for Windows»:
  echo     https://developer.android.com/tools/releases/platform-tools
  echo     распакуйте и добавьте папку platform-tools в PATH ^(или задайте ADB_PATH^).
)
where scrcpy >nul 2>nul || echo [i] scrcpy не найден ^(кнопка «В окне» будет недоступна^): https://github.com/Genymobile/scrcpy

if "%FARM_HOST%"=="" set "FARM_HOST=127.0.0.1"
if "%FARM_PORT%"=="" set "FARM_PORT=8777"
echo -^> Ферма поднимается на http://%FARM_HOST%:%FARM_PORT%
start "" "http://%FARM_HOST%:%FARM_PORT%"

cd backend
"..\.venv\Scripts\python.exe" -m farm.server
pause
