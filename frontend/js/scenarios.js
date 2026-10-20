'use strict';

/* Сценарии: список, форма параметров, запуск. */

/* Опрос раз в 15 с раньше пересобирал список и правую панель и заново
   грузил рецепт — панель моргала, фокус слетал. Теперь перерисовываем,
   только если что-то правда изменилось. */
let scSig = '';
const scRecipeCache = new Map();

async function loadScenarios(reload) {
    let list;
    try {
        list = await api('/api/scenarios' + (reload ? '?reload=true' : ''));
    } catch (e) {
        return;
    }
    const sig = JSON.stringify(list);
    if (sig === scSig && !reload) return;
    scSig = sig;
    scRecipeCache.clear();
    S.scenarios = list;

    scRenderList();

    setText($('scenCount'), S.scenarios.length ? `всего: ${S.scenarios.length}` : '');

    if (S.scenario && !S.scenarios.some(s => s.key === S.scenario)) S.scenario = null;
    if (!S.scenario && S.scenarios.length) pickScenario(scOrdered(S.scenarios)[0].key);
    else renderParams();
    renderRunbar();
}

/* Поиск и фильтры: сценариев набегает много, а искать глазами по списку
   тяжело. Панель собирается один раз, чтобы набор текста не терял фокус;
   перерисовываются только карточки. */
const SC_FILTER = {q: '', kind: 'all'};
const SC_TOOLS_FROM = 6;
const scKinds = () => [['all', t('scen.f_all')], ['bad', t('scen.f_bad')], ['mine', t('scen.f_mine')]];

function scVisible(list) {
    const q = SC_FILTER.q.trim().toLowerCase();
    return list.filter(s => {
        if (SC_FILTER.kind === 'bad' && !(s.failed || s.error)) return false;
        if (SC_FILTER.kind === 'mine' && s.template) return false;
        return !q || (s.name + ' ' + (s.description || '')).toLowerCase().includes(q);
    });
}

function scRenderList() {
    const box = $('scList');
    if (!S.scenarios.length) {
        setHTML(box, emptyBig({
            art: 'scenario',
            title: 'Ни одного сценария',
            text: 'Запишите действия на одном телефоне — ферма повторит на всех.',
            action: {label: 'Создать записью', icon: 'record', onClick: 'recNew(false)'},
        }));
        return;
    }
    /* Поиск и фильтры нужны, когда список не помещается в глаз; на двух
       сценариях это три лишних ряда над списком. */
    const tools = S.scenarios.length >= SC_TOOLS_FROM;
    if (!tools) {
        SC_FILTER.q = '';
        SC_FILTER.kind = 'all';
        if ($('scTools')) box.innerHTML = '<div id="scCards"></div>';
    }
    if (tools && !$('scTools')) {
        box.innerHTML = `<div id="scTools">
            <input type="search" id="scQ" placeholder="${esc(t('scen.poisk'))}" aria-label="${esc(t('scen.poisk'))}">
            <div class="seg" role="group">${scKinds().map(([k, label]) =>
                `<button class="sm" data-k="${k}" onclick="scSetKind('${k}')">${esc(label)}</button>`).join('')}</div>
            </div><div id="scCards"></div>`;
        $('scQ').addEventListener('input', ev => {
            SC_FILTER.q = ev.target.value;
            scRenderList();
        });
    }
    if (!$('scCards')) box.innerHTML = '<div id="scCards"></div>';
    box.querySelectorAll('#scTools .seg button').forEach(b => b.classList.toggle('on', b.dataset.k === SC_FILTER.kind));
    const shown = scVisible(S.scenarios);
    setHTML($('scCards'), shown.length ? scListHtml(shown)
        : `<p class="dim" style="padding:var(--s4)">${esc(t('scen.nichego'))}</p>`);
}

function scSetKind(kind) {
    SC_FILTER.kind = kind;
    scRenderList();
}

/* Готовые шаблоны (TEMPLATE = True в файле: прогрев и т.п.) — отдельной
   группой сверху: их запускают чаще всего и без правки. Порядок карточек
   в DOM = scOrdered, на нём держится выделение в pickScenario. */
function scOrdered(list) {
    return list.filter(s => s.template).concat(list.filter(s => s.command && !s.template),
        list.filter(s => !s.template && !s.command));
}

function scListHtml(list) {
    const templates = list.filter(s => s.template);
    const commands = list.filter(s => s.command && !s.template);
    const own = list.filter(s => !s.template && !s.command);
    const group = (title, items) => items.length
        ? `<div class="sc-group">${esc(title)}</div>${items.map(scenarioCard).join('')}` : '';
    if (!templates.length && !commands.length) return own.map(scenarioCard).join('');
    return group('Готовые шаблоны', templates) + group(t('cmd.komandy'), commands)
        + group('Мои сценарии', own);
}

/* Вторая строка карточки: сколько в сценарии шагов и развилок. Только у
   записанных конструктором — сырой .py обратно в шаги не разбирается, и
   врать числом было бы хуже, чем промолчать. */
function scenarioStructure(scenario) {
    if (scenario.steps == null) return '';
    const bits = [`${scenario.steps} ${declOfNum(scenario.steps, ['шаг', 'шага', 'шагов'])}`];
    if (scenario.branches) {
        bits.push(`${scenario.branches} ${declOfNum(scenario.branches, ['развилка', 'развилки', 'развилок'])}`);
    }
    return `<div class="meta">${esc(bits.join(' · '))}</div>`;
}

/* Третья строка: итог последних прогонов и непокрытые преграды по пакету
   приложения. uncovered === null значит «пакет не задан в параметрах» —
   тогда бейдж тревог просто не показываем, а не гадаем на нуле. */
function scenarioHealth(scenario) {
    const done = scenario.passed + scenario.failed;
    const bits = [];
    if (done) {
        const tone = scenario.failed ? (scenario.passed ? 'warn' : 'bad') : 'ok';
        bits.push(`<span class="hp ${tone}">✓ ${scenario.passed}/${done}</span>`);
    }
    if (scenario.uncovered) {
        bits.push(`<span class="hp bad">⚠ ${scenario.uncovered} ${
            declOfNum(scenario.uncovered, ['помеха', 'помехи', 'помех'])}</span>`);
    }
    return bits.length ? `<div class="health tnum">${bits.join(' ')}</div>` : '';
}

/* Русское склонение по числу — 1 шаг / 2 шага / 5 шагов. */
function declOfNum(n, forms) {
    const mod10 = n % 10, mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return forms[0];
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1];
    return forms[2];
}

function scenarioCard(scenario) {
    const lastErrorLine = String(scenario.error || '').split('\n').filter(Boolean).pop();
    const mark = scenario.recorded
        ? '<svg class="ic rec-mark"><title>Записано конструктором</title><use href="#i-record"/></svg>'
        : '';
    const drop = scenario.recorded
        ? `<button class="sm danger" title="Удалить сценарий"
             aria-label="Удалить сценарий ${esc(scenario.name)}"
             onclick="event.stopPropagation();deleteScenario('${scenario.key}')">
             <svg class="ic"><use href="#i-trash"/></svg></button>`
        : '';
    /* Правка только у сценариев с рецептом: .py обратно в шаги не разбирается
       (см. GET /api/recorder/recipe). */
    const edit = scenario.editable
        ? `<button class="sm" title="Править шаги в конструкторе"
             aria-label="Править сценарий ${esc(scenario.name)}"
             onclick="event.stopPropagation();editScenario('${scenario.key}')">
             <svg class="ic"><use href="#i-pencil"/></svg></button>`
        : '';
    return `<div class="sc ${S.scenario === scenario.key ? 'on' : ''}" data-kbd tabindex="0" role="button"
         aria-pressed="${S.scenario === scenario.key}"
               onclick="pickScenario('${scenario.key}')">
    <div class="nm">${mark}<span>${esc(scenario.name)}</span>${edit}${drop}</div>
    ${scenarioStructure(scenario)}
    ${scenarioHealth(scenario)}
    ${scenario.description ? `<div class="ds">${esc(scDescription(scenario.description))}</div>` : ''}
    ${scenario.error ? `<div class="er">${esc(lastErrorLine)}</div>` : ''}
  </div>`;
}

function deleteScenario(key) {
    const name = ((S.scenarios || []).find(s => s.key === key) || {}).name || key;
    confirmModal('Удалить сценарий?',
        `<p>«${esc(name)}» удалится без возврата.</p>`,
        'Удалить сценарий', async () => {
            try {
                await api('/api/scenarios/' + encodeURIComponent(key), {method: 'DELETE'});
                toast('сценарий удалён', 'ok');
                if (S.scenario === key) S.scenario = null;
                await loadScenarios(true);
            } catch (e) {
                toast(e.message, 'bad');
            }
        }, true);
}

function pickScenario(key) {
    S.scenario = key;
    renderParams();
    const cards = document.querySelectorAll('#scList .sc');
    cards.forEach(el => el.classList.remove('on'));
    const index = scOrdered(scVisible(S.scenarios)).findIndex(s => s.key === key);
    if (cards[index]) cards[index].classList.add('on');
}

function paramField(name, spec, value) {
    if (spec.options) {
        const options = spec.options.map(option =>
            `<option value="${esc(option)}" ${String(option) === String(value) ? 'selected' : ''}>${esc(option)}</option>`
        ).join('');
        return `<select id="p_${name}">${options}</select>`;
    }
    if (spec.type === 'bool' || typeof value === 'boolean') {
        return `<select id="p_${name}">
      <option value="true" ${value ? 'selected' : ''}>да</option>
      <option value="false" ${!value ? 'selected' : ''}>нет</option>
    </select>`;
    }
    if (spec.type === 'number' || typeof value === 'number') {
        const lim = (spec.min != null ? ` min="${esc(spec.min)}"` : '')
            + (spec.max != null ? ` max="${esc(spec.max)}"` : '');
        return `<input type="number" id="p_${name}" value="${esc(value)}" step="any"${lim}>`;
    }
    return `<input type="text" id="p_${name}" value="${esc(value)}"
                 placeholder="${esc(spec.placeholder || '')}">`;
}

/* Настройки сценария — одна разметка для окна запуска и формы смены.
   prefix разводит id полей двух мест; values — уже сохранённые значения
   (смена), иначе берутся значения по умолчанию из PARAMS сценария. */
function paramSpecs(sc) {
    return Object.entries((sc && sc.params) || {}).map(([name, raw]) =>
        [name, (raw && typeof raw === 'object') ? raw : {default: raw}]);
}

function paramsFormHtml(sc, values, prefix) {
    const v = values || {};
    return paramSpecs(sc).map(([name, spec]) => {
        const value = name in v ? v[name] : (spec.default == null ? '' : spec.default);
        return `<label class="bulk-row" title="${esc(spec.help || '')}">${esc(spec.label || name)}
          ${paramField(name, spec, value).replace(/id="p_/g, `id="${prefix}`)}</label>`;
    }).join('');
}

function paramsRead(sc, prefix) {
    const out = {};
    for (const [name, spec] of paramSpecs(sc)) {
        const el = $(prefix + name);
        if (!el) continue;
        let val = el.value === 'true' ? true : el.value === 'false' ? false : el.value;
        if (spec.type === 'number' && val !== '') {
            val = Number(val);
            if (spec.min != null) val = Math.max(spec.min, val);
            if (spec.max != null) val = Math.min(spec.max, val);
        }
        out[name] = val;
    }
    return out;
}

/* Что нужно сценарию и как он прошёл в последний раз — до запуска, а не
   после сорока упавших задач. */
/* Автоописание «Записано конструктором фермы 29.09.2026.» — служебное;
   человеку достаточно даты. */
function scDescription(text) {
    const m = /^Записано конструктором фермы\s+([\d.]+?)\.?$/.exec(text.trim());
    return m ? `записан ${m[1]}` : text;
}

function scMeta(sc) {
    const bits = [];
    if ((sc.needs_accounts || []).length) {
        bits.push(`<span>нужен аккаунт: <b>${sc.needs_accounts.map(p => PLATFORM_NAMES[p] || p).join(', ')}</b></span>`);
    }
    if (sc.passed || sc.failed) {
        bits.push(`<span>запуски: <b class="ok">${sc.passed} ок</b>`
            + (sc.failed ? ` · <b class="bad">${sc.failed} сбой</b>` : '') + '</span>');
    } else {
        bits.push('<span>ещё не запускался</span>');
    }
    return `<div class="sc-meta">${bits.join('')}</div>`;
}

/* Запуск — в окне запуска (rundialog.js): там же параметры, кто
   запускает и проверка готовности. Здесь только вход в него. */
function scRunBarHtml(key) {
    return `<div class="sc-acts">
      <button class="primary" onclick="openRunDialog({scenario: '${esc(key)}'})">
        <svg class="ic" aria-hidden="true"><use href="#i-play"/></svg>Запустить</button>
    </div>`;
}

function renderParams() {
    const scenario = S.scenarios.find(s => s.key === S.scenario);
    const box = $('scParams');
    if (!scenario) {
        box.innerHTML = '';
        return;
    }

    setHTML(box, `<h3>${esc(scenario.name)}</h3>${scMeta(scenario)}${scRunBarHtml(scenario.key)}${scTemplateInfo(scenario)}`);
    renderScenarioSteps(scenario);
}

/* Шаблон не из конструктора — шагов у него нет, и правая панель пустовала.
   Показываем, что он делает, с какими настройками стартует по умолчанию и
   куда его поставить; менять настройки — в окне запуска или в смене. */
function scTemplateInfo(sc) {
    if (!sc.template) return '';
    const facts = paramSpecs(sc).map(([, spec]) => {
        const d = spec.default;
        const shown = d === true ? 'да' : d === false ? 'нет' : esc(d);
        return `<div><dt>${esc(spec.label)}</dt><dd>${shown}</dd></div>`;
    }).join('');
    return `<div class="sc-tpl-info">
      ${sc.description ? `<p>${esc(sc.description)}</p>` : ''}
      ${facts ? `<h4>По умолчанию</h4><dl class="sc-tpl-facts">${facts}</dl>
        <p class="dim">Меняется при запуске.</p>` : ''}
      <button class="sm" onclick="scToSchedule('${esc(sc.key)}')">
        <svg class="ic"><use href="#i-activity"/></svg>Поставить в расписание</button>
    </div>`;
}

function scToSchedule(key) {
    S.scenario = key;
    showView('schedule');
    if (window.schEdit) schEdit(null, key);
}

/* Что сценарий делает — по шагам, теми же словами, что в конструкторе.
   Без этого список сценариев — набор имён, и понять «vk_auth» от «auth»
   можно было только открыв каждый в конструкторе. */
async function renderScenarioSteps(scenario) {
    const box = $('scSteps');
    if (!box) return;
    if (!scenario.editable) {
        box.hidden = true;
        return;
    }
    let recipe = scRecipeCache.get(scenario.key);
    try {
        if (!recipe) {
            recipe = await api('/api/recorder/recipe/' + encodeURIComponent(scenario.key));
            scRecipeCache.set(scenario.key, recipe);
        }
    } catch (e) {
        box.hidden = true;
        return;
    }
    if (S.scenario !== scenario.key) return;   // пока грузили, выбрали другой
    const steps = (recipe.steps || []).map(st => Object.assign({args: {}}, st));
    box.hidden = false;
    setHTML(box, `<div class="sc-steps-head"><h3>Шаги · ${steps.length}</h3>
        <button class="sm" onclick="editScenario('${esc(scenario.key)}')"
                title="Открыть в конструкторе">
          <svg class="ic"><use href="#i-pencil"/></svg>Изменить</button></div>
      <ol class="sc-steps">${steps.map(st =>
        `<li>${esc(recLabel(st))}</li>`).join('')}</ol>`);
}

