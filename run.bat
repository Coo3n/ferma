@echo off
rem Запуск фермы на Windows. Всё нужное ставится само и только один раз:
rem   Python 3.10+ - через winget, если его нет - установщик с python.org;
rem   adb          - официальный архив Google в .deps\ (без прав администратора);
rem   scrcpy       - необязателен, последний релиз с GitHub в .deps\;
rem   зависимости  - в .venv, заново только если поменялся backend\requirements.txt.
rem Уже стоящее (adb/scrcpy в PATH, скачанное в .deps, готовый .venv) повторно не качается.
rem Двойной клик по файлу или в терминале:  run.bat   (в PowerShell:  .\run.bat)
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "DEPS=%CD%\.deps"
set "PS=powershell -NoProfile -ExecutionPolicy Bypass -Command"

rem ------------------------------------------------------------ Python 3.10+
call :findpy
if defined PY goto :venv
echo -^> Python не найден - ставлю...
where winget >nul 2>nul
if not errorlevel 1 (
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
) else (
  echo -^> Скачиваю установщик Python с python.org...
  %PS% "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile \"$env:TEMP\py-setup.exe\""
  "%TEMP%\py-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1
)
call :findpy
if defined PY goto :venv
echo Не удалось поставить Python. Поставьте вручную: https://www.python.org/downloads/ ^(галочка «Add python.exe to PATH»^) и запустите run.bat снова.
pause
exit /b 1

:venv
rem ------------------------------------------------------------ .venv + зависимости
if not exist ".venv\Scripts\python.exe" (
  echo -^> Создаю виртуальное окружение...
  "%PY%" -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
)
rem Зависимости - заново, только если список изменился с прошлой установки.
fc /b backend\requirements.txt .venv\requirements.installed >nul 2>nul
if errorlevel 1 (
  echo -^> Ставлю зависимости...
  ".venv\Scripts\python.exe" -m pip install --quiet -r backend\requirements.txt || goto :fail
  copy /y backend\requirements.txt .venv\requirements.installed >nul
)

rem ------------------------------------------------------------ adb
where adb >nul 2>nul
if not errorlevel 1 goto :scrcpy
if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" goto :scrcpy
if exist "%DEPS%\platform-tools\adb.exe" goto :adbpath
echo -^> Скачиваю adb ^(Android platform-tools^) в .deps\...
if not exist "%DEPS%" mkdir "%DEPS%"
%PS% "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile '%DEPS%\pt.zip'; Expand-Archive -Force '%DEPS%\pt.zip' '%DEPS%'; Remove-Item '%DEPS%\pt.zip'"
if not exist "%DEPS%\platform-tools\adb.exe" echo [!] adb скачать не удалось - телефоны не будут видны. Скачайте вручную: https://developer.android.com/tools/releases/platform-tools
:adbpath
set "PATH=%DEPS%\platform-tools;%PATH%"

:scrcpy
rem ------------------------------------------------------------ scrcpy (необязательно)
where scrcpy >nul 2>nul
if not errorlevel 1 goto :run
if exist "%DEPS%\scrcpy\scrcpy.exe" goto :scrpath
echo -^> Скачиваю scrcpy ^(кнопка «В окне»^) в .deps\...
if not exist "%DEPS%" mkdir "%DEPS%"
%PS% "$ProgressPreference='SilentlyContinue'; try { $r = Invoke-RestMethod 'https://api.github.com/repos/Genymobile/scrcpy/releases/latest'; $a = $r.assets | Where-Object { $_.name -like 'scrcpy-win64-*.zip' } | Select-Object -First 1; Invoke-WebRequest $a.browser_download_url -OutFile '%DEPS%\scrcpy.zip'; Expand-Archive -Force '%DEPS%\scrcpy.zip' '%DEPS%\scrcpy-tmp'; $d = Get-ChildItem '%DEPS%\scrcpy-tmp' -Directory | Select-Object -First 1; if (Test-Path '%DEPS%\scrcpy') { Remove-Item -Recurse -Force '%DEPS%\scrcpy' }; Move-Item $d.FullName '%DEPS%\scrcpy'; Remove-Item -Recurse -Force '%DEPS%\scrcpy-tmp', '%DEPS%\scrcpy.zip' } catch { Write-Host '[i] scrcpy скачать не удалось - кнопка «В окне» будет недоступна, остальное работает' }"
:scrpath
if exist "%DEPS%\scrcpy\scrcpy.exe" set "PATH=%DEPS%\scrcpy;%PATH%"

:run
rem ------------------------------------------------------------ запуск
if "%FARM_HOST%"=="" set "FARM_HOST=127.0.0.1"
if "%FARM_PORT%"=="" set "FARM_PORT=8777"
echo -^> Ферма поднимается на http://%FARM_HOST%:%FARM_PORT%
start "" "http://%FARM_HOST%:%FARM_PORT%"
cd backend
"..\.venv\Scripts\python.exe" -m farm.server
pause
exit /b 0

:fail
echo Не получилось подготовить окружение - текст ошибки выше.
pause
exit /b 1

rem Ищет Python 3.10+: python в PATH, лаунчер py, стандартные папки установки.
:findpy
set "PY="
for %%C in (python.exe) do if not "%%~$PATH:C"=="" call :trypy "%%~$PATH:C"
if defined PY exit /b 0
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do call :trypy "%%P"
if defined PY exit /b 0
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" call :trypy "%%D\python.exe"
exit /b 0

:trypy
if defined PY exit /b 0
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=%~1"
exit /b 0
