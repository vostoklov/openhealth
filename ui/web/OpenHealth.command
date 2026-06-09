#!/bin/bash
# OpenHealth дашборд — лаунчер двойным кликом.
# Поднимает локальный сервер в фоне (переживает закрытие терминала) и открывает дашборд.
# Не нужно каждый раз руками запускать http.server.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${OPENHEALTH_PORT:-8770}"
URL="http://localhost:${PORT}/index.html"

# Если сервер уже отвечает на порту — просто открыть дашборд.
if curl -s -o /dev/null -m 2 "http://localhost:${PORT}/" 2>/dev/null; then
  open "$URL"
  exit 0
fi

# Иначе поднять фоновый сервер (nohup → не упадёт при закрытии окна).
cd "$DIR"
nohup python3 -m http.server "$PORT" >/tmp/openhealth-dashboard.log 2>&1 &
disown 2>/dev/null || true

# Подождать готовности и открыть.
for i in $(seq 1 20); do
  if curl -s -o /dev/null -m 2 "http://localhost:${PORT}/" 2>/dev/null; then break; fi
  sleep 0.3
done
open "$URL"
echo "OpenHealth запущен на ${URL}"
echo "Сервер работает в фоне. Это окно можно закрыть."
