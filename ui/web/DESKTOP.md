# OpenHealth дашборд — запуск как приложение (без ручного localhost)

Чтобы не запускать `python3 -m http.server` каждый раз и чтобы дашборд не падал — три уровня, от простого к нативному.

## 1. Двойной клик (просто)
`OpenHealth.command` — двойной клик в Finder. Поднимает сервер в фоне (переживает закрытие окна) и открывает дашборд. Если сервер уже работает — просто открывает.

```
chmod +x OpenHealth.command   # один раз
```

## 2. Автозапуск-сервис (не падает, всегда доступен)
`com.openhealth.dashboard.plist` — launchd-агент: стартует при логине, перезапускается если упал (`KeepAlive`). Дашборд всегда на `http://localhost:8770`.

Установка (один раз, заменить путь и загрузить):
```
WEB_DIR="$(pwd)"
sed "s#__WEB_DIR__#${WEB_DIR}#" com.openhealth.dashboard.plist > ~/Library/LaunchAgents/com.openhealth.dashboard.plist
launchctl load ~/Library/LaunchAgents/com.openhealth.dashboard.plist
```
Выгрузить: `launchctl unload ~/Library/LaunchAgents/com.openhealth.dashboard.plist`.

> Это меняет системную конфигурацию (автозапуск). Ставить осознанно, своими руками.

## 3. Нативное приложение (цель, как OpenDesign) — TODO
Полноценный `.app` (Mac/Win) через **Tauri**: встроенный webview + локальный data-слой, запуск как обычное приложение из Dock, без терминала и без видимого сервера. Local Claude/Codex passthrough для агентных действий. Это отдельный desktop-батч (см. GOAL, фронт «Desktop/runtime»).

Реальные данные (`data.local.json`) живут ТОЛЬКО локально у пользователя (в его health-папке), в этот репозиторий не попадают. Дашборд читает их при наличии, иначе показывает demo.
