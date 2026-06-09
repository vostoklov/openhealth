# Antigravity handoff — OpenHealth premium web dashboard

ЗАДАЧА: переписать `/Users/ilya/Projects/openhealth/ui/web/dashboard.html` (+ копия в `index.html`) в ПРЕМИУМ веб-дашборд OpenHealth. Текущая версия — недотянутый Linear-клон, нужна премиум-детализация. Single-file HTML/CSS/JS, запускается локально (`python3 -m http.server`), рендерит demo DATA (структура), мост на `openhealth show-summary`.

## Стиль (главный, не «тема»)
Тёмный премиум в духе Flenteey/Activity-dashboard. PNG-эталоны в `./refs/`:
- `cosmos-activity-dark.img`, `cosmos-then-tracker.img` — тёмные accent-карточки, bars, чеклисты состояний, golden-time. ГЛАВНЫЙ вайб.
- `cosmos-healthcare-bento.img` — цветные bento-блоки с крупными числами.
- `ultrahuman-dark.img` + WHOOP — ЗОЛОТОЙ СТАНДАРТ графиков: recovery rings, strain bars, тренды, зоны green/yellow/red. Pixel-perfect логику отображения бери отсюда.
- `linear-dashboard.img`, `linear-issues-sidebar.img` — sidebar-навигация, плотность, command palette.
- `substack-checklist.img` — getting-started чеклист с прогрессом → паттерн для «чекбоксы сегодня».
- `asana-dashboard.img`, `whop-today.img` — dashboard-виджеты, today-стата.

## Навигация (sidebar, под модули openhealth) — БЕЗ Ask/чат
Группы: 
- Сегодня: **Overview / Сегодня**, **Пульс дня**.
- Данные: **Biomarkers (Анализы)**, **WHOOP** (Overview + Correlations), **Журнал**, **Тренды**, Timeline, Состав тела, Тренировки.
- Знание: Protocols, Research.
- Система: Отчёты, Дайджесты, **Синхронизация**.
УБРАТЬ Ask/чат полностью (нерабочий, выпиливаем).

## Экраны (приоритет)
1. **Сегодня:** recovery-ring (WHOOP-логика, цветовое кодирование) + стата дня + **ЧЕКБОКСЫ «что сделано сегодня»** (как substack getting-started: лечь раньше / свет утром / прогулка / вода — отмечаешь). Фокус на действии, НЕ календарь. Доктор Контекст (настроение по recovery). Готовность к дню.
2. **Biomarkers/Анализы:** значения с референсными И оптимальными диапазонами (C1-C5), динамика, что обсудить с врачом. Если данных НЕТ → empty-state с CTA «Загрузить экспорт анализов / подключить».
3. **WHOOP Overview:** recovery/sleep/strain графики pixel-perfect по WHOOP.
4. **WHOOP Correlations:** что влияет на recovery (журнал↔recovery, personal baseline, C-grade).
5. **Журнал:** пользователь ВЫБИРАЕТ что хочет отвечать (кастомные behaviors из набора), потом лёгкий ежедневный чек-ин.
6. **Тренды, Синхронизация** (статус коннекторов: подключено/нет → CTA загрузить).

## Проверка подключений
Фронт проверяет, что подключено (WHOOP/Apple/Oura/Garmin/анализы/ДНК). Нет → empty-state + CTA «загрузить/подключить». Не показывай пустые графики молча.

## Премиум-требования
- Шрифты: Geist + Geist Mono (mono для всех чисел/метрик), выверенная типографическая иерархия.
- Анимации: GSAP — ring-fill, stagger карточек, мягкие переходы зон, hover. `prefers-reduced-motion` уважать.
- Вёрстка ИДЕАЛЬНАЯ на всех разрешениях: mobile (sidebar→drawer), tablet, desktop. Проверь брейкпоинты.
- Темы: тёмная главная (Flenteey), плюс светлая/брутал/баухаус переключателем (kazimir/mihaly НЕ нужны).
- Anti-slop: НЕ бежевый, НЕ Inter-дефолт, НЕ purple-gradient, НЕ дефолтные 3-колонки. Каждый элемент выверен по эталонам выше.

ВЫХОД: перезаписать `dashboard.html` и `index.html` в этой папке. Должно открываться локально и выглядеть премиально на всех экранах. Сохрани demo DATA-структуру и footer-намёк на `openhealth show-summary`.
