#!/usr/bin/env bash
# OpenHealth — установка одной командой.
#
#   bash setup.sh
#
# или, если репозиторий ещё не скачан:
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/igindin/openhealth/main/setup.sh)
#
# Скрипт дружелюбный и идемпотентный: его можно запускать сколько угодно раз.
# Он ничего не отправляет в интернет (кроме git clone, если репозитория ещё нет)
# и ничего не ставит в систему без твоего согласия.

set -u

REPO_URL="https://github.com/igindin/openhealth.git"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$*"; exit 1; }

# --- Шаг 0. Найти (или скачать) репозиторий ---------------------------------

ROOT=""
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ]; then
  CANDIDATE="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
  [ -f "$CANDIDATE/openhealth/__main__.py" ] && ROOT="$CANDIDATE"
fi
if [ -z "$ROOT" ] && [ -f "./openhealth/__main__.py" ]; then
  ROOT="$(pwd)"
fi
if [ -z "$ROOT" ]; then
  # Запуск через curl: репозитория рядом нет — скачиваем в ~/openhealth.
  say "Шаг 0. Скачиваю OpenHealth в ~/openhealth ..."
  if ! command -v git >/dev/null 2>&1; then
    fail "Не найден git. На macOS он поставится сам: открой Терминал, набери git и согласись на установку Command Line Tools. Потом запусти этот скрипт ещё раз."
  fi
  if [ -d "$HOME/openhealth/openhealth" ]; then
    note "~/openhealth уже существует — использую его."
  else
    git clone "$REPO_URL" "$HOME/openhealth" || fail "Не получилось скачать репозиторий. Проверь интернет и попробуй снова."
  fi
  ROOT="$HOME/openhealth"
fi
cd "$ROOT" || fail "Не получилось перейти в $ROOT"

say "OpenHealth: установка. Папка: $ROOT"

# --- Шаг 1. Проверить Python --------------------------------------------------

say "Шаг 1. Проверяю Python ..."
# Берём первый подходящий python (3.9+): обычный python3, новые версии, системный macOS.
PY=""
for CAND in python3 python3.13 python3.12 python3.11 python3.10 python3.9 /usr/bin/python3; do
  if command -v "$CAND" >/dev/null 2>&1 \
     && "$CAND" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$CAND"
    break
  fi
done
if [ -z "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '?')"
    fail "Твой python3 слишком старый ($PYV). Нужен 3.9 или новее: https://www.python.org/downloads/"
  fi
  fail "Не найден python3. Поставь Python с https://www.python.org/downloads/ (кнопка Download, дальше «далее-далее»), затем запусти скрипт ещё раз."
fi
note "Python найден: $("$PY" --version 2>&1) ($PY). Отлично, ничего ставить не нужно."

# Все команды openhealth работают без установки пакета: репозиторий в PYTHONPATH.
oh() { PYTHONPATH="$ROOT" "$PY" -m openhealth "$@"; }

# --- Шаг 2. (Опционально) установить пакет -----------------------------------

say "Шаг 2. Как запускать OpenHealth?"
note "1) локально, без установки — рекомендуется, ничего не меняет в системе"
note "2) установить пакет в Python (pip install -e .) — для тех, кто работает с CLI"
INSTALL_CHOICE="1"
if [ -t 0 ]; then
  printf '   Выбор [1]: '
  read -r INSTALL_CHOICE || INSTALL_CHOICE="1"
  INSTALL_CHOICE="${INSTALL_CHOICE:-1}"
fi
if [ "$INSTALL_CHOICE" = "2" ]; then
  if "$PY" -m pip install -e . ; then
    note "Пакет установлен. Теперь работает просто: python3 -m openhealth ..."
  else
    note "pip install не получился — не страшно, продолжаю в локальном режиме (это ни на что не влияет)."
  fi
else
  note "Ок, локальный режим: пакет не устанавливается, всё работает прямо из папки."
fi

# --- Шаг 3. Создать рабочее пространство --------------------------------------

say "Шаг 3. Создаю локальное рабочее пространство (папки + база данных) ..."
if oh init >/dev/null; then
  note "Готово: данные будут жить в $ROOT/data (только на этом компьютере, в git не попадают)."
else
  fail "Не получилось создать рабочее пространство. Запусти ещё раз; если повторится — открой Issue на GitHub."
fi

# --- Шаг 4. Свои данные (можно пропустить) ------------------------------------

DB="$ROOT/data/index/openhealth.sqlite3"

say "Шаг 4. Свои данные (этот шаг можно пропустить)."
note "Есть экспорт Apple Health? (iPhone: Здоровье -> аватар -> «Экспортировать медданные» -> переслать ZIP на компьютер)"
note "Перетащи файл export.zip (или export.xml) прямо в это окно и нажми Enter."
note "Просто Enter — пропустить (дашборд откроется на демо-данных)."
if [ -t 0 ]; then
  printf '   Файл: '
  read -r RAW_PATH || RAW_PATH=""
  # Подчистить путь после drag-and-drop: кавычки, экранированные пробелы, хвостовой пробел.
  CLEAN_PATH="${RAW_PATH%\'}"; CLEAN_PATH="${CLEAN_PATH#\'}"
  CLEAN_PATH="${CLEAN_PATH%\"}"; CLEAN_PATH="${CLEAN_PATH#\"}"
  CLEAN_PATH="${CLEAN_PATH//\\ / }"
  CLEAN_PATH="$(printf '%s' "$CLEAN_PATH" | sed 's/[[:space:]]*$//;s/^[[:space:]]*//')"
  if [ -n "$CLEAN_PATH" ]; then
    if [ -e "$CLEAN_PATH" ]; then
      note "Импортирую (на большом экспорте это может занять пару минут) ..."
      if oh import-apple-health --path "$CLEAN_PATH"; then
        note "Импорт завершён."
      else
        note "Импорт не получился — не страшно, продолжаю. Потом можно повторить: python3 -m openhealth import-apple-health --path <файл>"
      fi
    else
      note "Файл не найден: $CLEAN_PATH — пропускаю. Импорт можно сделать позже."
    fi
  else
    note "Пропускаю. Импорт можно сделать в любой момент позже."
  fi
else
  note "(неинтерактивный запуск — пропускаю вопрос про импорт)"
fi
note "Носишь WHOOP? Подключение через OAuth: python3 -m openhealth whoop-auth-url (подробнее в README, раздел Run)."

# --- Шаг 5. Собрать данные для дашборда ----------------------------------------

say "Шаг 5. Готовлю дашборд ..."
RECORDS=0
if [ -f "$DB" ]; then
  RECORDS="$("$PY" - "$DB" <<'PYEOF' 2>/dev/null || echo 0
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
print(con.execute("SELECT COUNT(*) FROM records").fetchone()[0])
PYEOF
)"
fi
if [ "${RECORDS:-0}" -gt 0 ] 2>/dev/null; then
  if "$PY" "$ROOT/ui/web/build_dashboard_data.py" --db "$DB" --out "$ROOT/ui/web/data.local.json"; then
    note "Дашборд будет показывать твои реальные данные (записей в базе: $RECORDS)."
  else
    note "Не получилось собрать data.local.json — дашборд откроется на демо-данных."
  fi
else
  note "Записей пока нет — дашборд откроется на демо-данных. Импортируй данные и запусти setup.sh ещё раз."
fi

# --- Шаг 6. Запустить ----------------------------------------------------------

say "Шаг 6. Запускаю дашборд ..."
chmod +x "$ROOT/ui/web/OpenHealth.command" 2>/dev/null || true
if [ "$(uname)" = "Darwin" ]; then
  bash "$ROOT/ui/web/OpenHealth.command" || note "Не открылось само? Запусти вручную: двойной клик по ui/web/OpenHealth.command"
else
  note "Не macOS: запусти сервер вручную и открой http://localhost:8770/index.html"
  note "  python3 $ROOT/ui/web/server.py --port 8770 --dir $ROOT/ui/web"
fi

# --- Дальше -------------------------------------------------------------------

say "Готово. Что дальше (всё по желанию):"
note "- Агент: поставь Claude Code (https://claude.com/claude-code) или Codex (https://github.com/openai/codex) — кнопки агента в дашборде оживут."
note "- Telegram-бот: docs/TELEGRAM.md"
note "- Календарь и другие интеграции: docs/INTEGRATIONS.md"
note "- Полный путеводитель: docs/START-HERE.md (RU) / docs/START-HERE.en.md (EN)"

# Момент ценности — самое честное место для просьбы (один раз, тепло).
if [ ! -f "$HOME/.openhealth/.star-asked" ]; then
  mkdir -p "$HOME/.openhealth" 2>/dev/null || true
  touch "$HOME/.openhealth/.star-asked" 2>/dev/null || true
  echo ""
  note "P.S. Если OpenHealth оказался полезен — звезда на GitHub реально помогает"
  note "проекту находить людей: https://github.com/igindin/openhealth ⭐"
fi
