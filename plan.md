# Plan: agent-native multi-domain OpenHealth

## Суть
Развиваем OpenHealth в agent-native health OS: главный интерфейс — Claude Code /
Codex (не GUI). Каждый домен (pulse, cycle, body, metabolic, skin, sleep) —
плагин-модуль с контрактом, схемой и тестами на синтетике. Реализуем классы
функциональности оригинально по открытой науке; чужие бренд-ассеты/код не копируем.
Без диагнозов: шкала доверия C1–C5 + red-flags. Local-first, MIT. GUI — потом, через A2UI.

## Что делаем
- Модульная плагин-система (`openhealth/modules/`): контракт `HealthModule` + registry. [DONE]
- Домен-модули: Pulse(HRV) [DONE], затем Sleep/Circadian, Cycle, Body, Metabolic, Skin.
- Agent-native UX: slash-команды (/checkin /log /fast /sleep /pulse /insights /trends /protocol) + health-agent оркестратор поверх Python CLI.
- Онбординг без git: `make setup`, pre-commit, CI, скрытый git/PR через агентские скрипты, ≥20 agent task cards, новичковые AGENTS/CLAUDE/CONTRIBUTING.
- core/privacy (анонимизация+тесты), headless API + TS SDK + OpenAPI, A2UI-адаптер (Insight→интент, golden, без рендера).

## Проверка
- до: OpenHealth = ingest+parsers+evidence+lab, без модулей/агент-UX/API.
- после: тесты/типы/lint зелёные; `make setup` с нуля; каждый модуль проходит contract-тест; ≥6 slash-команд end-to-end на синтетике; ≥20 agent task cards; новичок проходит «открыл Claude Code → залогировал/получил инсайт» и «выбрал задачу → PR» без знания git.

## Допущения
- Работаем в public `igindin/openhealth`, ветка `feat/agent-native-os`, без push без разрешения.
- GUI вне рамок (агент = интерфейс). Core — stdlib-only (без numpy).
- A2UI: подтвердить пакет (google/A2UI vs codaaiteam/ai2ui) перед адаптером.
- Всё на синтетике, ноль реальных PII.
