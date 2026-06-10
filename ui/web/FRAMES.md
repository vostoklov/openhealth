# FRAMES — motion-спек дашборда OpenHealth

Контракт анимаций для dashboard.html. Библиотека: GSAP 3.12 (CDN, подключён). Все тайминги в секундах. Любая новая анимация сверяется с этим файлом, а не придумывается на месте.

## Стандарты

| Паттерн | Длительность | Easing | Детали |
|---|---|---|---|
| Enter карточек зоны | 0.5-0.7 | power2.out | y 20→0 + fade, stagger 0.06-0.08 |
| Count-up чисел | 0.8 | power2.out | snap по шагу значения (целые: 1, десятые: 0.1); крупные числа mono |
| Line-draw | 1.2 | power1.inOut | stroke-dasharray/dashoffset = getTotalLength, после завершения inline dash очищается |
| Bar-grow | 0.6 | power3.out | scaleY 0→1 от основания (`transform-box: fill-box; transform-origin: 50% 100%`), stagger 0.05-0.08 |
| Ring (дуга) | 1.2 | back.out(1.2) при значении ≤90, иначе power3.out (overshoot не перелетает 100%) | счётчик числа count-up синхронно, та же длительность |
| Area-fill под линией | 0.6 | power1.out | fade 0→1, delay 0.4 (после старта draw) |
| Микро-фидбэк (чекбокс, save) | 0.3 | power2.out | scale 0.97→1 / fade |
| Уход зоны (go) | 0.25 | power2.in | fade + y 10 |

## Reduced motion

`prefers-reduced-motion: reduce` → `gsap.globalTimeline.timeScale(1000)` (паттерн уже в файле): каждый твин мгновенно достигает конечного кадра. CSS-анимации глушатся медиа-блоком. Print-CSS дополнительно довершает линии и прозрачность через `!important`.

## Экраны

- **Сегодня**: enter 0.7/0.08 → ринг recovery 1.2 back.out(1.2) + count-up числа синхронно (1.2); метрики-тайлы count-up 0.8 с каскадом 0.06; чеклист привычек fade+x(-8) 0.4, stagger 0.05.
- **Пульс дня**: line-draw ЧСС 1.2; зоны ЧСС bar-grow по width 0.6, stagger 0.06.
- **Biomarkers**: пилюли segment-баров fade + drop(y -6) 0.45, stagger 0.05; деталь-панель expand 0.3 power2.out, значение в панели count-up 0.8.
- **Обзор показателей**: три ринга 1.0 back.out(1.2), задержки 0 / 0.15 / 0.3, count-up значений синхронно; спарклайны line-draw 1.2 + area 0.6/delay 0.4.
- **Тренды**: оба графика line-draw 1.2, area fade 0.6 delay 0.4.
- **Отчёты**: дельты сравнения count-up 0.8; бары сравнения bar-grow 0.6, stagger 0.08; recovery-линия draw 1.2 + точки дней fade stagger 0.012; HRV/RHR тонкая линия draw 1.2, отрезки-средние и подписи fade 0.4 delay 0.9; heatmap-ячейки scale 0.6→1 + fade 0.4, stagger 0.012.
- **Пульс дня (колесо/эмоции)**: дуги циркадного колеса line-draw 1.0, stagger 0.05 (суммарно ≤0.45), маркер «ты здесь» fade+scale 0.4 back.out(1.6) delay 0.9; кольцо чек-инов эмоций — стандарт Ring 1.2.
- **Сегодня (декомпозиция)**: вклады recovery bar-grow scaleX 0.6 power3.out, stagger 0.08.
- **Протоколы**: enter-стандарт карточек 0.5/0.08.
- **Тренировки**: strain-бары width 0.6 power3.out (узкий прогресс — width-исключение), строки fade+x(-8) 0.4/0.04.
- **Переход зон**: уход 0.25 power2.in → enter-стандарт; render-хуки зоны зовутся из onComplete в `go()`.

## Запреты

- Никаких infinite-анимаций, кроме дыхания маскота (CSS) и спиннеров загрузки.
- Ничего дольше 1.5 c; суммарная задержка каскада ≤ 0.45.
- Не анимировать layout-свойства (width/height/top) там, где можно transform; исключение — узкие прогресс-бары (width).
- Печать: до `window.print()` все твины принудительно завершаются (`printReport()` + страховка в `@media print`).
