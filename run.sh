#!/usr/bin/env bash
# Запуск фермы. Первый прогон создаст виртуальное окружение и поставит зависимости.
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Не найден python3. Установите: brew install python" >&2
  exit 1
fi

if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Нужен Python 3.10+. Установите: brew install python" >&2
  exit 1
fi

if [ ! -d "$VENV" ]; then
  echo "→ Создаю виртуальное окружение…"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  echo "→ Ставлю зависимости…"
  "$VENV/bin/pip" install --quiet -r backend/requirements.txt
fi

if ! command -v adb >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/adb ] && [ ! -x "$HOME/Library/Android/sdk/platform-tools/adb" ]; then
  echo "⚠️  adb не найден. Установите: brew install --cask android-platform-tools" >&2
fi

if ! command -v scrcpy >/dev/null 2>&1; then
  echo "ℹ️  scrcpy не найден (кнопка «scrcpy» будет недоступна). Установите: brew install scrcpy" >&2
fi

HOST="${FARM_HOST:-127.0.0.1}"
PORT="${FARM_PORT:-8777}"
URL="http://${HOST}:${PORT}"

echo "→ Ферма поднимается на ${URL}"
( sleep 2; command -v open >/dev/null && open "$URL" || true ) &

# Сервер (backend/) сам раздаёт сайт (frontend/). Только API, без сайта:
# FARM_SERVE_FRONTEND=0 ./run.sh — тогда сайт поднимают отдельно:
# python3 frontend/dev_server.py
cd backend
exec "../$VENV/bin/python" -m farm.server
