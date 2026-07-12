/* oh-onboarding.js — iPhone-setup-style onboarding for OpenHealth.
 *
 * WHY
 * ---
 * OpenHealth ships ~30 sections at once. A first-time person needs a calm,
 * step-by-step setup that starts from their GOAL and assembles only the modules
 * they need — like setting up a new iPhone. This module is that flow, shared by
 * both skins (V1 dark monolith + V2 Bento) and re-runnable from Settings.
 *
 * IT REUSES EXISTING MACHINERY, no schema change:
 *   - OH.registry.groups / .sections / .personas  (definitions)
 *   - OH.nav.setHidden(id,on)  ->  localStorage 'openhealth.nav.hidden'
 *     (both skins already filter nav by this; oh-registry.js sectionView also
 *      returns '' for hidden sections, so bodies disappear too)
 *   - OH.setPersona(id)        ->  localStorage 'oh.persona'  (reorders nav)
 *   - theme                    ->  localStorage 'openhealth.theme' (data-theme)
 *   - accent (new, additive)   ->  localStorage 'oh.accent' (overrides --accent)
 *   - 'oh.onboarded' flag gates the first-run auto-start.
 *
 * The overlay themes itself with the app's own CSS variables (--bg, --ink,
 * --accent, --card-outer, --line, --radius-outer, --font), so it matches any
 * skin/theme/palette automatically.
 *
 * Public API (window.OHOnboarding):
 *   .open({rerun})     open the flow (rerun=true when launched from Settings)
 *   .maybeAutoStart()  open once on genuine first run (no data, not onboarded)
 *   .reset()           clear the onboarded flag (debug)
 *   .applyPalette()    apply the saved accent (called on load)
 */
(function (global) {
  'use strict';

  var LS = {
    onboarded: 'oh.onboarded',
    accent: 'oh.accent',
    theme: 'openhealth.theme',
    hidden: 'openhealth.nav.hidden'
  };

  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

  // Sections that are always on — the app is useless without "Сегодня", and
  // Settings must never be hidden (it's how you re-run this onboarding).
  var PINNED = { today: 1, pulse: 1, sync: 1, settings: 1 };

  // --- Palette presets (theme base + accent). "Выбор цветовой палитры." -------
  // Accent recolours the whole app via --accent. Dark stays the primary default;
  // warm-editorial and daylight are real alternatives, executed with the accent,
  // never as a flat beige wash.
  var PALETTES = [
    { id: 'midnight', name: 'Полночь', sub: 'тёмная, изумруд', theme: 'dark', accent: '#10b981' },
    { id: 'amber', name: 'Янтарь', sub: 'тёмная, тёплый медный', theme: 'dark', accent: '#f0a24b' },
    { id: 'coral', name: 'Коралл', sub: 'тёмная, живой коралл', theme: 'dark', accent: '#f2765f' },
    { id: 'iris', name: 'Ирис', sub: 'тёмная, спокойный синий', theme: 'dark', accent: '#6ea8fe' },
    { id: 'daylight', name: 'Дневной', sub: 'светлая, изумруд', theme: 'light', accent: '#0e9f6e' }
  ];

  // --- Goal-first directions. Each maps to an existing registry persona and a
  // starter bundle of groups (the rest is hidden by default, user can tune). ---
  var GOALS = [
    {
      id: 'athletes', persona: 'athlete', icon: 'ph-person-simple-run',
      title: 'Спорт и результат',
      hook: 'Понять, что реально помогает восстановиться и добавляет в форме.',
      keepGroups: ['today', 'activity', 'sleep', 'stress', 'analytics']
    },
    {
      id: 'medical', persona: 'chronic', icon: 'ph-first-aid-kit',
      title: 'Здоровье под контролем',
      hook: 'Собрать разрозненную картину и приходить к врачу подготовленным.',
      keepGroups: ['today', 'medical', 'body', 'analytics', 'journal']
    },
    {
      id: 'longevity', persona: 'seniors', icon: 'ph-plant',
      title: 'Долголетие',
      hook: 'Следить за показателями, которые тихо копятся годами.',
      keepGroups: ['today', 'body', 'analytics', 'medical', 'knowledge']
    },
    {
      id: 'stress-sleep', persona: 'low-energy', icon: 'ph-moon-stars',
      title: 'Сон и спокойствие',
      hook: 'Найти, что мешает сну и энергии, вместо того чтобы гадать.',
      keepGroups: ['today', 'sleep', 'stress', 'journal', 'analytics']
    },
    {
      id: 'curious', persona: null, icon: 'ph-compass',
      title: 'Просто начать',
      hook: 'Первый раз собираю систему здоровья. Начнём с малого.',
      keepGroups: ['today', 'sleep', 'activity', 'analytics']
    }
  ];

  // --- Synthetic inspiration cases (public-safe archetypes, phrased as questions,
  // no medical claims, no real people). ---------------------------------------
  var CASES = [
    { icon: 'ph-person-simple-run', title: 'Марафонец и восстановление', text: 'С ростом объёма пульс покоя чуть подрос. Это ранний сигнал усталости и повод для лёгкого дня, или просто жаркая неделя и короткий сон?' },
    { icon: 'ph-barbell', title: 'Силовые без перетрена', text: 'После трёх тяжёлых дней подряд recovery просел раньше, чем результаты. Может ли такой провал быть подсказкой запланировать отдых?' },
    { icon: 'ph-brain', title: 'Дыхательная практика', text: 'Вечернее дыхание — видно ли его в сигналах нервной системы? Спокойнее ли ночь после практики, чем без неё?' }
  ];

  // hex -> rgba glow
  function glow(hex, a) {
    var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '');
    if (!m) return 'rgba(16,185,129,' + (a || 0.15) + ')';
    return 'rgba(' + parseInt(m[1], 16) + ',' + parseInt(m[2], 16) + ',' + parseInt(m[3], 16) + ',' + (a || 0.15) + ')';
  }

  // Apply a persisted accent on top of whatever theme the skin set. Idempotent.
  function applyPalette() {
    var a = get(LS.accent);
    if (a) {
      var root = document.documentElement;
      root.style.setProperty('--accent', a);
      root.style.setProperty('--accent-text', a);
      root.style.setProperty('--accent-glow', glow(a, 0.15));
    }
  }

  // Hide sections the user turned off, in either skin. The sectionView seam
  // already blanks registry bodies; this also covers nodes that never pass
  // through it: registry bodies carry data-section, and V2 bespoke bento cards
  // use id="sec-<id>" (biomarkers/correlations/trends/…) with no data-section.
  function hideIfOff(node, id) {
    if (id && !PINNED[id] && OH.nav.isHidden(id)) node.style.display = 'none';
  }
  function applyModuleVisibility() {
    if (!global.OH || !OH.nav) return;
    document.querySelectorAll('[data-section]').forEach(function (n) { hideIfOff(n, n.getAttribute('data-section')); });
    document.querySelectorAll('[id^="sec-"]').forEach(function (n) { hideIfOff(n, n.id.slice(4)); });
  }

  // ---- overlay construction --------------------------------------------------
  var state = null; // {step, goal, chosen:Set, palette}
  var el = null;

  function css() {
    if (document.getElementById('ohb-style')) return;
    var s = document.createElement('style');
    s.id = 'ohb-style';
    s.textContent = [
      // NO opacity animation/transition on the root — both rAF class-toggles AND
      // CSS animations get throttled in background/headless and freeze the overlay
      // half-faded, letting the dashboard bleed through. The root is always opaque.
      '.ohb-root{position:fixed;inset:0;z-index:100000;background:var(--bg,#060709);color:var(--ink,#f3f4f6);',
      'font-family:var(--font,system-ui,sans-serif);display:flex;flex-direction:column;opacity:1}',
      '.ohb-rail{display:flex;align-items:center;gap:14px;padding:22px 26px 8px;max-width:760px;margin:0 auto;width:100%}',
      '.ohb-num{font-variant-numeric:tabular-nums;font-weight:800;font-size:15px;letter-spacing:.02em;color:var(--accent,#10b981)}',
      '.ohb-num small{color:var(--dim,#768093);font-weight:600}',
      '.ohb-bar{flex:1;height:3px;border-radius:3px;background:var(--line,#1d212a);overflow:hidden}',
      '.ohb-bar>i{display:block;height:100%;width:0;background:var(--accent,#10b981);transition:width .5s cubic-bezier(.2,.8,.2,1)}',
      '.ohb-skip{background:none;border:0;color:var(--dim,#768093);font-size:13px;cursor:pointer;padding:6px 8px}',
      '.ohb-skip:hover{color:var(--ink,#fff)}',
      '.ohb-scroll{flex:1;overflow-y:auto;overflow-x:hidden}',
      '.ohb-stage{max-width:760px;margin:0 auto;padding:8px 26px 40px;width:100%}',
      '.ohb-step{animation:ohbIn .45s cubic-bezier(.2,.8,.2,1)}',
      '@keyframes ohbIn{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}',
      // giant numeral-as-graphic + ghost word
      '.ohb-hero{position:relative;padding:18px 0 6px}',
      '.ohb-ghost{position:absolute;top:-12px;left:-4px;font-size:150px;line-height:.8;font-weight:800;color:var(--ink,#fff);opacity:.05;letter-spacing:-.04em;pointer-events:none;user-select:none;white-space:nowrap}',
      '.ohb-kicker{position:relative;font-size:13px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--accent,#10b981);margin:0 0 10px}',
      '.ohb-h{position:relative;font-size:34px;line-height:1.08;font-weight:800;letter-spacing:-.02em;margin:0 0 12px}',
      '.ohb-sub{position:relative;font-size:16px;line-height:1.5;color:var(--mut,#8e96a3);margin:0 0 22px;max-width:52ch}',
      // cards
      '.ohb-cards{display:flex;flex-direction:column;gap:12px}',
      '.ohb-card{display:flex;align-items:center;gap:16px;text-align:left;width:100%;background:var(--card-outer,#0f1115);',
      'border:1.5px solid var(--line,#1d212a);border-radius:var(--radius-inner,16px);padding:16px 18px;cursor:pointer;',
      'transition:border-color .18s,transform .18s,background .18s;color:inherit}',
      '.ohb-card:hover{transform:translateY(-1px);border-color:var(--line2,#2a303d)}',
      '.ohb-card.sel{border-color:var(--accent,#10b981);background:var(--accent-glow,rgba(16,185,129,.12))}',
      '.ohb-card__ic{flex:none;width:46px;height:46px;border-radius:12px;display:grid;place-items:center;background:var(--card-inner,#14171d);color:var(--accent,#10b981);font-size:24px}',
      '.ohb-card.sel .ohb-card__ic{background:var(--accent,#10b981);color:#04120c}',
      '.ohb-card__t{display:block;font-size:17px;font-weight:700;margin:0 0 3px}',
      '.ohb-card__d{display:block;font-size:13.5px;color:var(--mut,#8e96a3);line-height:1.4;margin:0}',
      '.ohb-card__chk{margin-left:auto;flex:none;width:22px;height:22px;border-radius:50%;border:1.5px solid var(--line2,#2a303d);display:grid;place-items:center;color:transparent;font-size:13px}',
      '.ohb-card.sel .ohb-card__chk{background:var(--accent,#10b981);border-color:var(--accent,#10b981);color:#04120c}',
      // module groups
      '.ohb-grp{margin:0 0 10px;border:1px solid var(--line,#1d212a);border-radius:var(--radius-inner,16px);overflow:hidden;background:var(--card-outer,#0f1115)}',
      '.ohb-grp__h{display:flex;align-items:center;gap:11px;padding:13px 16px;cursor:pointer;user-select:none}',
      '.ohb-grp__h i.gic{color:var(--accent,#10b981);font-size:19px}',
      '.ohb-grp__nm{font-weight:700;font-size:15px}',
      '.ohb-grp__ct{margin-left:auto;font-size:12px;color:var(--dim,#768093)}',
      '.ohb-grp__sec{display:flex;flex-wrap:wrap;gap:8px;padding:0 16px 14px}',
      '.ohb-pill{display:inline-flex;align-items:center;gap:7px;padding:7px 12px;border-radius:999px;border:1.5px solid var(--line,#1d212a);',
      'font-size:13px;cursor:pointer;color:var(--mut,#8e96a3);transition:all .15s;background:var(--card-inner,#14171d)}',
      '.ohb-pill.on{border-color:var(--accent,#10b981);color:var(--ink,#fff);background:var(--accent-glow,rgba(16,185,129,.12))}',
      '.ohb-pill.pinned{opacity:.65;cursor:default}',
      '.ohb-pill i{font-size:14px}',
      '.ohb-soon{margin-left:2px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim,#768093);opacity:.8}',
      // palette swatches
      '.ohb-pals{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}',
      '.ohb-pal{border:1.5px solid var(--line,#1d212a);border-radius:var(--radius-inner,16px);padding:14px;cursor:pointer;background:var(--card-outer,#0f1115);transition:border-color .18s,transform .18s}',
      '.ohb-pal:hover{transform:translateY(-1px)}',
      '.ohb-pal.sel{border-color:var(--accent,#10b981)}',
      '.ohb-pal__sw{display:flex;gap:6px;margin-bottom:10px}',
      '.ohb-pal__sw i{width:26px;height:26px;border-radius:8px;display:block}',
      '.ohb-pal__nm{display:block;font-weight:700;font-size:14px}',
      '.ohb-pal__sub{display:block;font-size:12px;color:var(--dim,#768093)}',
      // how-it-works rows + cases
      '.ohb-rows{display:flex;flex-direction:column;gap:14px;margin:0 0 24px}',
      '.ohb-row{display:flex;gap:14px;align-items:flex-start}',
      '.ohb-row i{flex:none;width:40px;height:40px;border-radius:11px;display:grid;place-items:center;background:var(--card-inner,#14171d);color:var(--accent,#10b981);font-size:20px}',
      '.ohb-row b{display:block;font-size:15px;margin:0 0 2px}',
      '.ohb-row span{font-size:13.5px;color:var(--mut,#8e96a3);line-height:1.45}',
      '.ohb-cases{display:flex;flex-direction:column;gap:10px}',
      '.ohb-case{border:1px solid var(--line,#1d212a);border-radius:14px;padding:13px 15px;background:var(--card-outer,#0f1115)}',
      '.ohb-case__h{display:flex;align-items:center;gap:9px;font-weight:700;font-size:14px;margin:0 0 5px}',
      '.ohb-case__h i{color:var(--accent,#10b981);font-size:17px}',
      '.ohb-case p{margin:0;font-size:13px;color:var(--mut,#8e96a3);line-height:1.45}',
      // summary / assemble
      '.ohb-big{font-variant-numeric:tabular-nums;font-weight:800;font-size:88px;line-height:.9;letter-spacing:-.03em;margin:6px 0 2px}',
      '.ohb-biglbl{font-size:15px;color:var(--mut,#8e96a3);margin:0 0 22px}',
      '.ohb-chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px}',
      '.ohb-chip{display:inline-flex;align-items:center;gap:7px;padding:8px 13px;border-radius:999px;background:var(--card-inner,#14171d);border:1px solid var(--line,#1d212a);font-size:13px;',
      'opacity:0;transform:translateY(8px);animation:ohbPop .4s forwards}',
      '.ohb-chip i{color:var(--accent,#10b981)}',
      '@keyframes ohbPop{to{opacity:1;transform:none}}',
      // footer
      '.ohb-foot{border-top:1px solid var(--line,#1d212a);background:var(--bg,#060709);padding:16px 26px;display:flex;gap:12px;align-items:center;max-width:760px;margin:0 auto;width:100%}',
      '.ohb-back{background:none;border:0;color:var(--mut,#8e96a3);font-size:14px;cursor:pointer;padding:12px}',
      '.ohb-back:hover{color:var(--ink,#fff)}',
      '.ohb-next{margin-left:auto;background:var(--accent,#10b981);color:#04120c;border:0;border-radius:999px;padding:14px 30px;',
      'font-size:15px;font-weight:800;cursor:pointer;transition:transform .15s,opacity .15s;font-family:inherit}',
      '.ohb-next:hover{transform:translateY(-1px)}',
      '.ohb-next[disabled]{opacity:.4;cursor:not-allowed;transform:none}',
      '@media(max-width:560px){.ohb-h{font-size:27px}.ohb-ghost{font-size:96px}.ohb-big{font-size:64px}.ohb-stage{padding:8px 18px 32px}.ohb-rail,.ohb-foot{padding-left:18px;padding-right:18px}}'
    ].join('');
    document.head.appendChild(s);
  }

  function groupById(id) { return (OH.registry.groups || []).find(function (g) { return g.id === id; }); }
  function sectionsOf(groupId) {
    var g = groupById(groupId); if (!g) return [];
    return (g.section_ids || []).map(function (id) { return OH.section(id); }).filter(Boolean);
  }

  function defaultChosen(goal) {
    var chosen = {};
    (OH.registry.groups || []).forEach(function (g) {
      var keep = goal.keepGroups.indexOf(g.id) >= 0;
      (g.section_ids || []).forEach(function (sid) {
        var s = OH.section(sid); if (!s) return;
        // keep every section of a chosen group — matches how nav already renders
        // (incl. "coming soon" stubs); persona picks WHICH groups, not maturity.
        if (keep) chosen[sid] = 1;
      });
    });
    Object.keys(PINNED).forEach(function (k) { if (OH.section(k)) chosen[k] = 1; });
    return chosen;
  }

  var STEPS = ['welcome', 'goal', 'modules', 'palette', 'how', 'ready'];

  function open(opts) {
    opts = opts || {};
    if (!global.OH || !OH.registry) { return; } // registry must be loaded
    css();
    state = { i: 0, goal: null, chosen: {}, palette: PALETTES[0], rerun: !!opts.rerun };
    // seed palette from current settings on rerun
    var curAccent = get(LS.accent);
    if (curAccent) { var p = PALETTES.find(function (x) { return x.accent === curAccent; }); if (p) state.palette = p; }
    el = document.createElement('div');
    el.className = 'ohb-root';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'Настройка OpenHealth');
    document.body.appendChild(el);
    render();
  }

  function close() {
    if (!el) return;
    var node = el; el = null; state = null;
    node.style.transition = 'opacity .3s ease'; node.style.opacity = '0';
    setTimeout(function () { if (node && node.parentNode) node.parentNode.removeChild(node); }, 300);
  }

  function go(delta) {
    var next = state.i + delta;
    if (next < 0) return;
    if (next >= STEPS.length) return;
    // skip modules default-seed when entering from goal
    state.i = next;
    render();
    var sc = el.querySelector('.ohb-scroll'); if (sc) sc.scrollTop = 0;
  }

  function render() {
    var step = STEPS[state.i];
    var total = STEPS.length;
    var pct = Math.round(((state.i) / (total - 1)) * 100);
    var body = '';
    if (step === 'welcome') body = viewWelcome();
    else if (step === 'goal') body = viewGoal();
    else if (step === 'modules') body = viewModules();
    else if (step === 'palette') body = viewPalette();
    else if (step === 'how') body = viewHow();
    else if (step === 'ready') body = viewReady();

    var num = String(state.i + 1).padStart(2, '0');
    var tot = String(total).padStart(2, '0');
    el.innerHTML =
      '<div class="ohb-rail">' +
        '<span class="ohb-num">' + num + ' <small>/ ' + tot + '</small></span>' +
        '<span class="ohb-bar"><i style="width:' + pct + '%"></i></span>' +
        (step === 'welcome' && !state.rerun ? '<button class="ohb-skip" data-act="skip">Пропустить</button>' : '<button class="ohb-skip" data-act="skip">Закрыть</button>') +
      '</div>' +
      '<div class="ohb-scroll"><div class="ohb-stage"><div class="ohb-step">' + body + '</div></div></div>' +
      footer(step);
    wire(step);
  }

  function footer(step) {
    var canNext = true, nextLbl = 'Дальше';
    if (step === 'goal' && !state.goal) canNext = false;
    if (step === 'welcome') nextLbl = 'Поехали';
    if (step === 'ready') nextLbl = 'Собрать мою OpenHealth';
    return '<div class="ohb-foot">' +
      (state.i > 0 ? '<button class="ohb-back" data-act="back">Назад</button>' : '') +
      '<button class="ohb-next" data-act="next"' + (canNext ? '' : ' disabled') + '>' + nextLbl + '</button>' +
      '</div>';
  }

  function viewWelcome() {
    return '<div class="ohb-hero"><div class="ohb-ghost">Health</div>' +
      '<p class="ohb-kicker">Настройка</p>' +
      '<h1 class="ohb-h">Соберём вашу OpenHealth<br>под вас</h1>' +
      '<p class="ohb-sub">Это как настройка нового телефона. Несколько спокойных шагов — и на экране останется только то, что важно именно вам. Ничего лишнего, всё можно поменять позже.</p>' +
      '</div>' +
      '<div class="ohb-rows">' +
        row('ph-target', 'Начнём с цели', 'Скажете, ради чего вы здесь — приложение подстроится.') +
        row('ph-squares-four', 'Соберём модули', 'Включим только нужные разделы. Остальные не будут мешать.') +
        row('ph-palette', 'Выберете вид', 'Тема и цвет под ваш вкус.') +
      '</div>';
  }

  function viewGoal() {
    var cards = GOALS.map(function (g) {
      var sel = state.goal && state.goal.id === g.id;
      return '<button class="ohb-card' + (sel ? ' sel' : '') + '" data-goal="' + g.id + '">' +
        '<span class="ohb-card__ic"><i class="ph-light ' +g.icon + '"></i></span>' +
        '<span><span class="ohb-card__t">' + esc(g.title) + '</span>' +
        '<span class="ohb-card__d">' + esc(g.hook) + '</span></span>' +
        '<span class="ohb-card__chk"><i class="ph-light ph-check"></i></span>' +
        '</button>';
    }).join('');
    return '<p class="ohb-kicker">Шаг 1 · Цель</p>' +
      '<h1 class="ohb-h">Что для вас сейчас главное?</h1>' +
      '<p class="ohb-sub">Выберите одно. Это только старт — приложение соберётся вокруг этой цели, а не вокруг всех функций сразу.</p>' +
      '<div class="ohb-cards">' + cards + '</div>';
  }

  function viewModules() {
    if (!state.goal) state.goal = GOALS[0];
    if (!state._touchedModules) state.chosen = defaultChosen(state.goal);
    var on = 0; Object.keys(state.chosen).forEach(function (k) { if (state.chosen[k]) on++; });
    var groups = (OH.registry.groups || []).slice().sort(function (a, b) { return (a.order || 0) - (b.order || 0); });
    var html = groups.map(function (g) {
      var secs = sectionsOf(g.id);
      if (!secs.length) return '';
      var cnt = secs.filter(function (s) { return state.chosen[s.id] || PINNED[s.id]; }).length;
      var pills = secs.map(function (s) {
        var pinned = !!PINNED[s.id];
        var onp = pinned || state.chosen[s.id];
        var soon = (s.status === 'soon' || s.status === 'empty');
        return '<button class="ohb-pill' + (onp ? ' on' : '') + (pinned ? ' pinned' : '') + '" data-sec="' + s.id + '"' + (pinned ? ' disabled' : '') + '>' +
          '<i class="ph-light ' +(s.icon || 'ph-circle') + '"></i>' + esc(s.label_ru || s.id) +
          (soon ? '<span class="ohb-soon">скоро</span>' : '') + '</button>';
      }).join('');
      return '<div class="ohb-grp"><div class="ohb-grp__h"><i class="ph-light ' +(g.icon || 'ph-folder') + ' gic"></i>' +
        '<span class="ohb-grp__nm">' + esc(g.label_ru || g.id) + '</span>' +
        '<span class="ohb-grp__ct">' + cnt + ' из ' + secs.length + '</span></div>' +
        '<div class="ohb-grp__sec">' + pills + '</div></div>';
    }).join('');
    return '<p class="ohb-kicker">Шаг 2 · Модули</p>' +
      '<h1 class="ohb-h">Соберём только нужное</h1>' +
      '<p class="ohb-sub">Мы уже отметили разделы под вашу цель (сейчас ' + on + '). Уберите лишнее или добавьте своё — «Сегодня» остаётся всегда.</p>' +
      html;
  }

  function viewPalette() {
    var pals = PALETTES.map(function (p) {
      var sel = state.palette && state.palette.id === p.id;
      var sw = p.theme === 'light' ? '#f9fafb' : '#0f1115';
      var sw2 = p.theme === 'light' ? '#e5e7eb' : '#14171d';
      return '<button class="ohb-pal' + (sel ? ' sel' : '') + '" data-pal="' + p.id + '">' +
        '<span class="ohb-pal__sw"><i style="background:' + sw + ';border:1px solid ' + sw2 + '"></i>' +
        '<i style="background:' + sw2 + '"></i><i style="background:' + p.accent + '"></i></span>' +
        '<span class="ohb-pal__nm">' + esc(p.name) + '</span><span class="ohb-pal__sub">' + esc(p.sub) + '</span>' +
        '</button>';
    }).join('');
    return '<p class="ohb-kicker">Шаг 3 · Вид</p>' +
      '<h1 class="ohb-h">Выберите палитру</h1>' +
      '<p class="ohb-sub">Меняет тему и акцентный цвет всего приложения. Превью применяется сразу — потом можно переключить в настройках.</p>' +
      '<div class="ohb-pals">' + pals + '</div>';
  }

  function viewHow() {
    var cases = CASES.map(function (c) {
      return '<div class="ohb-case"><div class="ohb-case__h"><i class="ph-light ' +c.icon + '"></i>' + esc(c.title) + '</div>' +
        '<p>' + esc(c.text) + '</p></div>';
    }).join('');
    return '<p class="ohb-kicker">Шаг 4 · Как это работает</p>' +
      '<h1 class="ohb-h">Коротко о главном</h1>' +
      '<div class="ohb-rows">' +
        row('ph-devices', 'Везде одна база', 'Смотрите на компьютере, а телефон открывает то же самое. Внесли утром в заметку — вечером видно в приложении.') +
        row('ph-lock-simple', 'Данные у вас', 'OpenHealth хранит всё локально, на вашей стороне. Никакого облака по умолчанию.') +
        row('ph-chat-circle-dots', 'Помощник по желанию', 'Можно подключить агента (в том числе свой код или Codex), чтобы он разбирал данные и готовил заметки. Это опция, не обязанность.') +
        row('ph-flask', 'Осторожно с выводами', 'Приложение задаёт вопросы и показывает закономерности, но не ставит диагнозов. Решения — с врачом.') +
      '</div>' +
      '<p class="ohb-kicker">Живые примеры</p>' +
      '<div class="ohb-cases">' + cases + '</div>';
  }

  function viewReady() {
    var chips = chosenSections().map(function (s, idx) {
      return '<span class="ohb-chip" style="animation-delay:' + (idx * 45) + 'ms"><i class="ph-light ' +(s.icon || 'ph-circle') + '"></i>' + esc(s.label_ru || s.id) + '</span>';
    }).join('');
    var n = chosenSections().length;
    var gname = state.goal ? state.goal.title : '';
    return '<p class="ohb-kicker">Готово</p>' +
      '<div class="ohb-big" id="ohb-count">' + n + '</div>' +
      '<p class="ohb-biglbl">модулей в вашей OpenHealth · цель: ' + esc(gname) + '</p>' +
      '<div class="ohb-chips">' + chips + '</div>' +
      '<p class="ohb-sub" style="margin-top:18px">Нажмите «Собрать» — экран пересоберётся под эти модули и палитру. Захотите иначе — «Перезапустить настройку» живёт в разделе «Настройки».</p>';
  }

  function row(ic, t, d) {
    return '<div class="ohb-row"><i class="ph-light ' +ic + '"></i><div><b>' + esc(t) + '</b><span>' + esc(d) + '</span></div></div>';
  }

  function chosenSections() {
    var out = [];
    (OH.registry.sections || []).forEach(function (s) {
      if (s.id === 'settings' || s.id === 'sync') return; // infra, not a user module
      if (state.chosen[s.id] || PINNED[s.id]) out.push(s);
    });
    return out;
  }

  function wire(step) {
    el.querySelector('[data-act="skip"]').onclick = function () { if (state.rerun) close(); else finishSkip(); };
    var back = el.querySelector('[data-act="back"]'); if (back) back.onclick = function () { go(-1); };
    var next = el.querySelector('[data-act="next"]'); if (next) next.onclick = function () {
      if (step === 'ready') { commit(); return; }
      go(1);
    };
    if (step === 'goal') {
      el.querySelectorAll('[data-goal]').forEach(function (b) {
        b.onclick = function () {
          state.goal = GOALS.find(function (g) { return g.id === b.getAttribute('data-goal'); });
          state._touchedModules = false;
          render();
        };
      });
    }
    if (step === 'modules') {
      el.querySelectorAll('[data-sec]').forEach(function (b) {
        if (b.disabled) return;
        b.onclick = function () {
          var id = b.getAttribute('data-sec');
          state.chosen[id] = state.chosen[id] ? 0 : 1;
          state._touchedModules = true;
          render();
        };
      });
    }
    if (step === 'palette') {
      el.querySelectorAll('[data-pal]').forEach(function (b) {
        b.onclick = function () {
          state.palette = PALETTES.find(function (p) { return p.id === b.getAttribute('data-pal'); });
          previewPalette(state.palette);
          render();
        };
      });
    }
    if (step === 'ready') { countUp(); }
  }

  // live preview while choosing (temporary; committed on finish)
  function previewPalette(p) {
    var root = document.documentElement;
    root.setAttribute('data-theme', p.theme);
    root.style.setProperty('--accent', p.accent);
    root.style.setProperty('--accent-text', p.accent);
    root.style.setProperty('--accent-glow', glow(p.accent, 0.15));
  }

  function countUp() {
    var node = document.getElementById('ohb-count'); if (!node) return;
    var target = parseInt(node.textContent, 10) || 0;
    // rAF is throttled in background/headless and can freeze mid-count on a wrong
    // number. Guarantee the correct final value two ways: skip the animation when
    // hidden, and a timeout backstop that always lands on target.
    if (document.hidden || target <= 0) { node.textContent = target; return; }
    var startTs = null;
    function tick(ts) {
      if (startTs == null) startTs = ts;
      var t = Math.min(1, (ts - startTs) / 650);
      node.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) requestAnimationFrame(tick); else node.textContent = target;
    }
    requestAnimationFrame(tick);
    setTimeout(function () { node.textContent = target; }, 800);
  }

  // "Пропустить" on genuine first run: mark onboarded with an all-on default so
  // we don't nag again, but hide nothing.
  function finishSkip() {
    set(LS.onboarded, '1');
    close();
  }

  function commit() {
    // persona
    if (OH.setPersona) OH.setPersona(state.goal && state.goal.persona ? state.goal.persona : null);
    // hidden = complement of chosen (sections + fully-off groups)
    var hidden = [];
    (OH.registry.sections || []).forEach(function (s) {
      if (!state.chosen[s.id] && !PINNED[s.id]) hidden.push(s.id);
    });
    (OH.registry.groups || []).forEach(function (g) {
      var any = (g.section_ids || []).some(function (id) { return state.chosen[id] || PINNED[id]; });
      if (!any) hidden.push('group:' + g.id);
    });
    set(LS.hidden, JSON.stringify(hidden));
    // palette
    if (state.palette) { set(LS.theme, state.palette.theme); set(LS.accent, state.palette.accent); }
    set(LS.onboarded, '1');
    // assemble animation, then reload so both skins fully reassemble
    var stage = el.querySelector('.ohb-step');
    if (stage) stage.style.transition = 'opacity .4s';
    var foot = el.querySelector('.ohb-foot'); if (foot) foot.innerHTML = '<span style="margin:auto;color:var(--mut,#8e96a3);font-size:14px">Собираю вашу OpenHealth…</span>';
    setTimeout(function () { location.reload(); }, 1100);
  }

  // Auto-start only on a genuine first run: not onboarded yet, and no real data
  // loaded (a returning user with data is not "new" even without the flag).
  function maybeAutoStart() {
    if (get(LS.onboarded)) return;
    if (!global.OH || !OH.registry) return;
    open({ rerun: false });
  }

  var API = {
    open: open,
    maybeAutoStart: maybeAutoStart,
    applyPalette: applyPalette,
    applyModuleVisibility: applyModuleVisibility,
    reset: function () { try { localStorage.removeItem(LS.onboarded); } catch (e) {} }
  };
  global.OHOnboarding = API;

  // On load: apply saved accent immediately (before paint where possible), then
  // enforce module visibility (covers V2 bespoke cards) once and on later mounts.
  applyPalette();
  function boot() {
    applyModuleVisibility();
    // late-rendered sections (async skin render) — hide as they appear
    try {
      var mo = new MutationObserver(function () { applyModuleVisibility(); });
      mo.observe(document.body, { childList: true, subtree: true });
      setTimeout(function () { mo.disconnect(); }, 6000);
    } catch (e) {}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

})(typeof window !== 'undefined' ? window : this);
