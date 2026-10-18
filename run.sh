#!/usr/bin/env bash
# Запуск фермы (Mac / Linux). Всё нужное ставится само и только один раз:
#   • Python 3.10+  — через Homebrew на Mac (если нет — подскажет, как поставить);
#   • adb           — официальный архив Google в .deps/ (без sudo и Homebrew);
#   • scrcpy        — необязателен: Homebrew на Mac, на Linux — подсказка;
#   • зависимости   — в .venv, переустанавливаются, только если поменялся
#                     backend/requirements.txt.
# Уже стоящее (adb в PATH, скачанное в .deps, готовый .venv) повторно не качается.
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
DEPS=".deps"
OS="$(uname -s)"

say() { echo "→ $*"; }
warn() { echo "⚠️  $*" >&2; }

# ---------------------------------------------------------------- Python 3.10+
py_ok() { command -v "$1" >/dev/null 2>&1 && "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; }

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for cand in python3 python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if py_ok "$cand"; then PY="$cand"; break; fi
  done
fi
if [ -z "$PY" ]; then
  if [ "$OS" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    say "Ставлю Python через Homebrew…"
    brew install python
    PY="$(brew --prefix)/bin/python3"
  else
    if [ "$OS" = "Darwin" ]; then
      warn "Нужен Python 3.10+. Проще всего: поставьте Homebrew (https://brew.sh) и запустите ./run.sh снова — Python поставится сам."
    else
      warn "Нужен Python 3.10+: sudo apt install python3 python3-venv  (или аналог для вашего дистрибутива)"
    fi
    exit 1
  fi
fi

# ---------------------------------------------------------------- .venv + зависимости
if [ ! -x "$VENV/bin/python" ]; then
  say "Создаю виртуальное окружение…"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
fi
# Зависимости — заново, только если список изменился с прошлой установки.
if ! cmp -s backend/requirements.txt "$VENV/.requirements.installed" 2>/dev/null; then
  say "Ставлю зависимости…"
  "$VENV/bin/pip" install --quiet -r backend/requirements.txt
  cp backend/requirements.txt "$VENV/.requirements.installed"
fi

# ---------------------------------------------------------------- adb
download() {  # download URL FILE — curl или wget, что есть
  if command -v curl >/dev/null 2>&1; then curl -fL --retry 3 -o "$2" "$1"
  else wget -q -O "$2" "$1"; fi
}

if command -v adb >/dev/null 2>&1; then
  :   # уже стоит (Homebrew, Android Studio в PATH…)
elif [ -x "$DEPS/platform-tools/adb" ]; then
  export PATH="$PWD/$DEPS/platform-tools:$PATH"
else
  case "$OS" in
    Darwin) PT="darwin" ;;
    *)      PT="linux" ;;
  esac
  say "Скачиваю adb (Android platform-tools) в $DEPS/…"
  mkdir -p "$DEPS"
  # Не скачалось (нет сети, прокси) — ферма всё равно стартует, просто без
  # телефонов; при следующем запуске попробуем снова.
  if download "https://dl.google.com/android/repository/platform-tools-latest-$PT.zip" "$DEPS/pt.zip"; then
    if command -v unzip >/dev/null 2>&1; then unzip -q -o "$DEPS/pt.zip" -d "$DEPS"
    else "$PY" -m zipfile -e "$DEPS/pt.zip" "$DEPS"; chmod +x "$DEPS/platform-tools/"*; fi
    export PATH="$PWD/$DEPS/platform-tools:$PATH"
  else
    warn "adb скачать не удалось — телефоны не будут видны. Поставьте вручную: https://developer.android.com/tools/releases/platform-tools"
  fi
  rm -f "$DEPS/pt.zip"
fi

# ---------------------------------------------------------------- scrcpy (необязательно)
if ! command -v scrcpy >/dev/null 2>&1; then
  if [ "$OS" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
    say "Ставлю scrcpy через Homebrew (для кнопки «В окне»)…"
    brew install scrcpy || warn "scrcpy не поставился — кнопка «В окне» будет недоступна, остальное работает"
  else
    echo "ℹ️  scrcpy не найден — кнопка «В окне» будет недоступна. Поставить: brew install scrcpy / sudo apt install scrcpy"
  fi
fi

# ---------------------------------------------------------------- запуск
HOST="${FARM_HOST:-127.0.0.1}"
PORT="${FARM_PORT:-8777}"
URL="http://${HOST}:${PORT}"

say "Ферма поднимается на ${URL}"
( sleep 2; { command -v open >/dev/null && open "$URL"; } || { command -v xdg-open >/dev/null && xdg-open "$URL"; } || true ) >/dev/null 2>&1 &

# Сервер (backend/) сам раздаёт сайт (frontend/). Только API, без сайта:
# FARM_SERVE_FRONTEND=0 ./run.sh — тогда сайт поднимают отдельно:
# python3 frontend/dev_server.py
cd backend
exec "../$VENV/bin/python" -m farm.server
