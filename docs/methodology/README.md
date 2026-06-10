# Методологии расчёта

По одному файлу на параметр дашборда. Каждый файл написан **из реального кода** (точные константы и пути) и имеет жёсткий формат, чтобы UI мог его парсить: заголовок `#`, строка `> algo_version: ... · источник данных: ... · редактируемость: ...`, секции `## Что это`, `## Формула / алгоритм`, `## Параметры (константы кода)` (таблица `параметр | значение | где в коде | зачем`), `## Источники и доверие`, `## Известные ограничения`.

## Индекс

| файл | параметр | версия алгоритма | основной модуль |
|---|---|---|---|
| [recovery.md](recovery.md) | recovery score 0-100 | recovery_score@v3 | `openhealth/modules/recovery.py` |
| [correlations.md](correlations.md) | влияние привычек («+N пунктов») | n/a | `openhealth/modules/correlations.py` |
| [hrv.md](hrv.md) | rMSSD, readiness, baseline/SWC | n/a (readiness v2) | `openhealth/modules/pulse.py` |
| [rhr.md](rhr.md) | пульс покоя (компонента + тренд) | recovery_score@v3 | `openhealth/modules/recovery.py`, `openhealth/insights.py` |
| [strain.md](strain.md) | нагрузка 0-21 (passthrough) | strain@v1 | `openhealth/modules/recovery.py` |
| [sleep.md](sleep.md) | долг сна, need, маркеры сна | sleep_debt@v2 | `openhealth/modules/recovery.py`, `openhealth/modules/sleep.py` |
| [vo2max.md](vo2max.md) | VO2max (оценка Uth) | vo2max@v1 | `openhealth/modules/vo2max.py` |
| [circadian.md](circadian.md) | фазы дня, кривая энергии | two-process-rise@v1 | `openhealth/circadian.py` |
| [insights.md](insights.md) | 7 детекторов паттернов | n/a | `openhealth/insights.py` |
| [protocols.md](protocols.md) | n-of-1 протоколы (ABAB/AB) | n/a | `openhealth/protocols.py` |
| [biological-age.md](biological-age.md) | фитнес-возраст по VO2max | n/a (UI) | `ui/web/dashboard.html` |
| [day-load.md](day-load.md) | загрузка дня из календаря | n/a | `openhealth/connectors/ics_calendar.py` |
| [weather-flags.md](weather-flags.md) | погодные флаги | n/a | `openhealth/connectors/weather.py` |
| [data-quality.md](data-quality.md) | балл качества данных | n/a | `openhealth/data_quality.py` |

Смежное: [evidence-and-trust.md](evidence-and-trust.md) — канон уверенности C1-C5, на который ссылаются все файлы выше.

## Правило синхронизации (anti-drift)

**Правишь параметр в коде → бампни `algo_version` модуля (если она есть) и обнови соответствующий md в этой папке.** Старые записи остаются помечены версией, которая их произвела, — это и есть смысл версионирования.

Дрейф ловится тестом `tests/test_methodology_docs.py`: он парсит значения из таблиц «Параметры (константы кода)» и сверяет их с живым импортом модулей (веса recovery, окно baseline 28, коэффициент Uth 15.3, порог давления 8 гПа, вес busy-часов 70). Разъехались md и код — тест красный.

## Как это редактировать

Эти файлы — обычный markdown в локальном репозитории, источник правды для будущей страницы «Методологии» в дашборде. Редактирование:

- руками — любой правкой файла (формат секций сохранять, иначе UI-парсер и тест сломаются);
- через агента — запрос вида «поменяй порог X» означает **двойную правку**: константа в коде + строка в таблице md (и бамп версии, если модуль версионирован). Агент обязан делать обе;
- runtime-оверрайды — реестр `openhealth/params.py` (`~/.openhealth/params.json`): пользователь меняет значение в пределах допустимого диапазона без правки кода; записи, посчитанные с оверрайдом, штампуются `algo_version+custom` и несут `metadata.params_overrides`. Константы в коде остаются каноническими дефолтами — именно их сверяет anti-drift тест.

UI-контракт (для оркестратора): `GET /api/methodology` → `[{id, title, version, path, content}]`, где `id` — имя файла без `.md`, `title` — первая `#`-строка, `version` — из `algo_version` в шапке, `content` — сырой markdown.
