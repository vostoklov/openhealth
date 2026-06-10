# Инсайты (детекторы паттернов)
> algo_version: n/a (модуль insights, пороги-константы) · источник данных: движок · редактируемость: параметры в коде

## Что это

Слой «найди настоящую проблему» поверх дневных серий (recovery, hrv, rhr, sleep_h, strain). 7 детекторов, каждый превращает числовое наблюдение в осторожный вывод: факты → вопрос себе → один конкретный шаг. `severity` (info/attention/warning) — громкость сигнала в данных; `confidence` (C1/C2) — уверенность в причине. Это разные оси: громкий необъяснённый сигнал = высокая severity + низкая confidence.

## Формула / алгоритм

Общая механика трендовых детекторов: среднее за последние 7 дней против личного baseline 14-28 дней назад (окно 7-28, свежая неделя исключена). Минимум 5 свежих и 7 baseline-точек. Конфиденс: C2 при достатке данных, C1 при скудных (через `cap_personal_pattern`). Каждый warning несёт дисклеймер «при симптомах — к врачу».

7 детекторов и их пороги:

1. **Накопленный недосып** (`detect_sleep_debt`): недобор к цели за 7 ночей >= 5 ч → attention, >= 10 ч → warning. Цель — персональная (`goals.sleep_h`, дефолт 8.0).
2. **HRV ниже baseline** (`detect_hrv_downtrend`): 7д среднее ниже baseline на >= 8% → attention, >= 15% → warning.
3. **Пульс покоя выше baseline** (`detect_rhr_uptrend`): рост >= 3 уд/мин → attention, >= 6 → warning.
4. **Серия красных дней** (`detect_recovery_red_streak`): >= 3 дня подряд recovery < 34 (красная зона дашборда) → warning.
5. **Нагрузка на низком восстановлении** (`detect_strain_recovery_mismatch`): дни, где strain >= 14 при recovery < 50, за окно 14 дней; 2 раза → attention, 3 → warning.
6. **Паттерн выходных** (`detect_weekend_pattern`): |среднее recovery будни − выходные| >= 5 пунктов; просадка в выходные → attention, наоборот → info.
7. **Нестабильный сон** (`detect_sleep_consistency`): SD длительности сна за 14 ночей > 1.2 ч → attention.

Сортировка вывода: warning → attention → info, внутри — по убыванию confidence. Падение одного детектора не валит проход (исключения глотаются).

## Параметры (константы кода)

| параметр | значение | где в коде | зачем |
|---|---|---|---|
| цель сна дефолт | 8.0 | `openhealth/insights.py: DEFAULT_SLEEP_GOAL_H` | если пользователь не задал свою |
| недосып attention / warning | 5.0 / 10.0 | `openhealth/insights.py: SLEEP_DEBT_WEEK_*_H` | ~43 мин и ~1.4 ч за ночь соответственно |
| падение HRV attention / warning | 8.0 / 15.0 (%) | `openhealth/insights.py: HRV_DROP_*_PCT` | прагматичные личные полосы тренда |
| рост RHR attention / warning | 3.0 / 6.0 (уд/мин) | `openhealth/insights.py: RHR_RISE_*_BPM` | классический ранний маркер |
| красная зона recovery | 34 | `openhealth/insights.py: RECOVERY_RED_MAX` | синхронизирована с цветами дашборда |
| длина красной серии | 3 | `openhealth/insights.py: RED_STREAK_DAYS` | три подряд — уже не случайность |
| высокий strain / низкий recovery | 14.0 / 50 | `openhealth/insights.py: STRAIN_HIGH, RECOVERY_LOW_FOR_STRAIN` | определение mismatch-дня |
| mismatch окно / attention / warning | 14 / 2 / 3 | `openhealth/insights.py: MISMATCH_*` | повторяемость = паттерн |
| разница выходных | 5.0 | `openhealth/insights.py: WEEKEND_DIFF_POINTS` | меньше — шум календарного среза |
| SD сна | 1.2 | `openhealth/insights.py: SLEEP_CONSISTENCY_STDEV_H` | регулярность важнее разовой длительности |
| окна тренда | 7 / 7-28 | `openhealth/insights.py: RECENT_WINDOW, BASELINE_LO, BASELINE_HI` | свежая неделя против личного фона |
| минимум точек | 5 / 7 | `openhealth/insights.py: MIN_RECENT_POINTS, MIN_BASELINE_POINTS` | ниже — не считаем |

## Источники и доверие

- Канон — `openhealth/evidence.py`: личный паттерн capped C2 до n-of-1 валидации; всё на C3 и ниже — вопрос, не утверждение.
- Только личные baseline, никаких популяционных норм.
- Пороги — задокументированные, тюнябельные константы с обоснованием в комментариях кода.

## Известные ограничения

- Детекторы независимы и могут описывать одно событие с разных сторон (болезнь поднимет и RHR, и красную серию).
- Календарный срез будни/выходные груб — не учитывает реальный график.
- Ничего не диагностируется; warning — это «громко в данных», не «опасно медицински».
