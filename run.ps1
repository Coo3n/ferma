# Запуск фермы на Windows (вызывается из run.bat; работает и в PowerShell 7 на Mac/Linux).
# Всё нужное ставится само и только один раз:
#   Python 3.10+ — официальный установщик python.org, только для этого пользователя;
#   adb          — официальный архив Google в .deps\ (без прав администратора);
#   scrcpy       — необязателен, последний релиз с GitHub в .deps\;
#   зависимости  — в .venv, заново только если поменялся backend\requirements.txt.
# Уже стоящее (в PATH, в .deps, готовый .venv) повторно не качается.
#
# Логика здесь, а не в .bat: cmd читает файл в одной кодировке, а после chcp —
# в другой, и длинный bat с русским текстом и скобками ломался на разборе
# («окно мигнуло и закрылось»). PowerShell с этим не путается.

$ErrorActionPreference = 'Continue'      # коды выхода проверяем сами
$ProgressPreference = 'SilentlyContinue' # в PowerShell 5.1 полоса прогресса тормозит загрузку в разы
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
# PowerShell 5.1 по умолчанию ходит по TLS 1.0 — python.org и GitHub его не принимают.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

Set-Location -LiteralPath $PSScriptRoot
$win = ($env:OS -eq 'Windows_NT')
$deps = Join-Path $PSScriptRoot '.deps'
$sep = [IO.Path]::PathSeparator

function Say($m) { Write-Host "-> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[x] $m" -ForegroundColor Red; exit 1 }

# Скачать во временный .part и переименовать только целый файл: оборванная
# загрузка не должна потом считаться «уже скачанной».
function Get-File($url, $out) {
    $part = "$out.part"
    Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
    if ($win -and (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
        & curl.exe -L --fail --progress-bar -o $part $url        # видно ход загрузки
        if ($LASTEXITCODE -ne 0) { Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue; return $false }
    } else {
        try { Invoke-WebRequest -Uri $url -OutFile $part -UseBasicParsing }
        catch { Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue; return $false }
    }
    Move-Item -LiteralPath $part -Destination $out -Force
    return $true
}

function Add-ToPath($dir) { $env:PATH = "$dir$sep$env:PATH" }
function Add-ToPathEnd($dir) { $env:PATH = "$env:PATH$sep$dir" }

# ------------------------------------------------------------------ Python 3.10+
function Test-Py($exe) {
    try {
        & $exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-Py {
    $cands = @()
    if ($env:PYTHON) { $cands += $env:PYTHON }
    foreach ($name in 'python', 'python3') {
        Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | ForEach-Object { $cands += $_.Source }
    }
    if ($win) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            try { $p = (& py -3 -c "import sys; print(sys.executable)" 2>$null); if ($p) { $cands += "$p".Trim() } } catch {}
        }
        $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
    }
    foreach ($exe in $cands) {
        # Заглушка python.exe из WindowsApps не Python, а ярлык в Microsoft Store:
        # её запуск открывал бы магазин.
        if (-not $exe -or $exe -match '\\WindowsApps\\') { continue }
        if (Test-Py $exe) { return $exe }
    }
    return $null
}

$py = Find-Py
if (-not $py) {
    if (-not $win) { Fail 'Нужен Python 3.10+ (на Mac удобнее ./run.sh — он поставит его через Homebrew).' }
    $setup = Join-Path $env:TEMP 'python-3.12.7-amd64.exe'
    if (-not (Test-Path -LiteralPath $setup)) {
        Say 'Python не найден — скачиваю официальный установщик с python.org (~25 МБ)...'
        if (-not (Get-File 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' $setup)) {
            Fail 'Не удалось скачать Python. Поставьте вручную: https://www.python.org/downloads/ (галочка «Add python.exe to PATH») и запустите run.bat снова.'
        }
    }
    Say 'Ставлю Python только для этого пользователя — 1-2 минуты, появится окно с прогрессом...'
    Start-Process -FilePath $setup -Wait -ArgumentList '/passive', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_test=0', 'Shortcuts=0'
    $py = Find-Py
    if (-not $py) { Fail 'Python не поставился. Поставьте вручную: https://www.python.org/downloads/ и запустите run.bat снова.' }
}
Say "Python: $py"

# ------------------------------------------------------------------ .venv + зависимости
$vpy = if ($win) { Join-Path $PSScriptRoot '.venv\Scripts\python.exe' } else { Join-Path $PSScriptRoot '.venv/bin/python' }
if (-not (Test-Path -LiteralPath $vpy)) {
    Say 'Создаю виртуальное окружение...'
    & $py -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $vpy)) { Fail 'Не получилось создать .venv — текст ошибки выше.' }
    & $vpy -m pip install --disable-pip-version-check --upgrade pip
}
# Зависимости — заново, только если список изменился с прошлой установки.
$req = Join-Path $PSScriptRoot 'backend/requirements.txt'
$mark = Join-Path $PSScriptRoot '.venv/requirements.installed'
$same = (Test-Path -LiteralPath $mark) -and ((Get-FileHash -LiteralPath $req).Hash -eq (Get-FileHash -LiteralPath $mark).Hash)
if (-not $same) {
    Say 'Ставлю зависимости (видно ход установки, обычно меньше минуты)...'
    & $vpy -m pip install --disable-pip-version-check -r $req
    if ($LASTEXITCODE -ne 0) { Fail 'Зависимости не поставились — текст ошибки выше.' }
    Copy-Item -LiteralPath $req -Destination $mark -Force
}

# ------------------------------------------------------------------ adb
$adbExe = if ($win) { 'adb.exe' } else { 'adb' }
$sdkAdb = if ($win) { Join-Path "$env:LOCALAPPDATA" 'Android\Sdk\platform-tools\adb.exe' } else { '' }
if (Get-Command adb -ErrorAction SilentlyContinue) {
    # уже в PATH
} elseif ($sdkAdb -and (Test-Path -LiteralPath $sdkAdb)) {
    Add-ToPath (Split-Path $sdkAdb)
} elseif (Test-Path -LiteralPath (Join-Path $deps "platform-tools/$adbExe")) {
    Add-ToPath (Join-Path $deps 'platform-tools')
} else {
    $plat = if ($win) { 'windows' } elseif ($IsMacOS) { 'darwin' } else { 'linux' }
    Say 'Скачиваю adb (Android platform-tools) в .deps...'
    New-Item -ItemType Directory -Force -Path $deps | Out-Null
    $zip = Join-Path $deps 'pt.zip'
    if (Get-File "https://dl.google.com/android/repository/platform-tools-latest-$plat.zip" $zip) {
        Expand-Archive -LiteralPath $zip -DestinationPath $deps -Force
        Remove-Item -LiteralPath $zip -Force
        if (-not $win) { & chmod +x (Join-Path $deps 'platform-tools/adb') }
        Add-ToPath (Join-Path $deps 'platform-tools')
    } else {
        # Ферма всё равно стартует, просто без телефонов; в следующий раз попробуем снова.
        Warn 'adb скачать не удалось — телефоны не будут видны. Вручную: https://developer.android.com/tools/releases/platform-tools'
    }
}

# ------------------------------------------------------------------ scrcpy (необязательно)
if (-not (Get-Command scrcpy -ErrorAction SilentlyContinue)) {
    $scr = Join-Path $deps 'scrcpy'
    if (Test-Path -LiteralPath (Join-Path $scr 'scrcpy.exe')) {
        Add-ToPathEnd $scr
    } elseif ($win) {
        Say 'Скачиваю scrcpy (кнопка «В окне») в .deps...'
        try {
            # Последний релиз — через API GitHub; не ответил (лимит запросов,
            # прокси) — проверенная версия по прямой ссылке.
            $link = 'https://github.com/Genymobile/scrcpy/releases/download/v3.1/scrcpy-win64-v3.1.zip'
            try {
                $rel = Invoke-RestMethod -Uri 'https://api.github.com/repos/Genymobile/scrcpy/releases/latest' -UseBasicParsing
                $asset = $rel.assets | Where-Object { $_.name -like 'scrcpy-win64-*.zip' } | Select-Object -First 1
                if ($asset) { $link = $asset.browser_download_url }
            } catch {}
            New-Item -ItemType Directory -Force -Path $deps | Out-Null
            $zip = Join-Path $deps 'scrcpy.zip'
            $tmp = Join-Path $deps 'scrcpy-tmp'
            if (-not (Get-File $link $zip)) { throw 'download' }
            Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
            $inner = Get-ChildItem -LiteralPath $tmp -Directory | Select-Object -First 1
            if (Test-Path -LiteralPath $scr) { Remove-Item -LiteralPath $scr -Recurse -Force }
            Move-Item -LiteralPath $inner.FullName -Destination $scr
            Remove-Item -LiteralPath $tmp, $zip -Recurse -Force
            Add-ToPathEnd $scr
        } catch {
            Warn 'scrcpy скачать не удалось — кнопка «В окне» будет недоступна, остальное работает.'
        }
    } else {
        Write-Host '[i] scrcpy не найден — кнопка «В окне» будет недоступна (brew install scrcpy / sudo apt install scrcpy).'
    }
}

# В архиве scrcpy лежит свой adb.exe. Две разные версии adb на одном
# компьютере перезапускают друг другу сервер, и телефоны «отваливаются».
# Поэтому папка scrcpy — в конце PATH, а scrcpy через ADB получает тот же adb,
# что и ферма (его adb — только запасной, если основной скачать не удалось).
$adbCmd = Get-Command adb -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($adbCmd) { $env:ADB = $adbCmd.Source; $env:ADB_PATH = $adbCmd.Source }

# ------------------------------------------------------------------ запуск
$hostName = if ($env:FARM_HOST) { $env:FARM_HOST } else { '127.0.0.1' }
$port = if ($env:FARM_PORT) { $env:FARM_PORT } else { '8777' }
$url = "http://${hostName}:${port}"
Say "Ферма поднимается на $url  (остановить — Ctrl+C)"
if ($win) { Start-Process $url }
Set-Location -LiteralPath (Join-Path $PSScriptRoot 'backend')
& $vpy -m farm.server
exit $LASTEXITCODE
