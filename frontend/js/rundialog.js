/* Окно запуска — единственная точка запуска сценария на ферме.

   Раньше запускали из трёх мест тремя кодами: панель фермы (select +
   «Повторов»), «Сценарии» (параметры + «Повторов») и «По группам». Здесь
   всё сразу: сценарий, параметры, кто запускает, и — главное — сводка
   готовности до нажатия: «38 готовы · 2 без аккаунта VK». Без неё о
   нехватке аккаунта узнавали по сорока упавшим задачам.

   Проверка в конструкторе (один телефон, с шага, медленно) — другая
   задача и живёт в steptools.js. */

const RD_LAST_KEY = 'farm.run.last';
const RD_PREFLIGHT_DEBOUNCE_MS = 150;

const RD_STATUS = {
    ready: ['готовы', 'ok'],
    login: ['нужен вход — запустятся', 'warn'],
    busy: ['заняты — встанут в очередь', 'busy'],
    no_account: ['без аккаунта', 'bad'],
    banned: ['аккаунт в бане', 'bad'],
    offline: ['не в сети', 'off'],
};
/* Кого запускаем: занятые встают в очередь, «нужен вход» — пробуем. */
const RD_RUNNABLE = new Set(['ready', 'busy', 'login']);

const RD = window.RD = {mode: 'devices', who: 'phones', picked: new Set(), query: '',
    group: '', tag: '', check: null, timer: null, seq: 0};

function rdGroups() {
    return [...new Set(S.devices.map(d => d.group).filter(Boolean))].sort();
}

function rdTags() {
    return [...new Set(S.devices.flatMap(d => d.tags || []))].sort((a, b) => a.localeCompare(b, 'ru'));
}

function rdOnline(list) {
    return list.filter(d => d.online && !S.hidden.has(d.serial)).map(d => d.serial);
}

function rdTargets() {
    if (RD.who === 'phones') return rdOnline(S.devices.filter(d => RD.picked.has(d.serial)));
    if (RD.who === 'group') return rdOnline(S.devices.filter(d => d.group === RD.group));
    if (RD.who === 'tag') return rdOnline(S.devices.filter(d => (d.tags || []).includes(RD.tag)));
    return rdOnline(S.devices);
}

function rdScenario() {
    return S.scenarios.find(s => s.key === ($('rdScen') || {}).value);
}

/* ------------------------------------------------------------- открыть */

function openRunDialog(opts) {
    opts = opts || {};
    if (!S.scenarios.length) return toast('сценариев пока нет — запишите первый', 'bad');
    RD.mode = opts.mode || 'devices';
    if (RD.mode === 'groups') return rdGroupsOpen();

    const key = opts.scenario || store.get(RD_LAST_KEY, '') || S.scenario || S.scenarios[0].key;
    /* По умолчанию — конкретные телефоны, а не вся ферма: отмечены выбранные
       на ферме, а если ничего не выбрано — открытый в пульте. Запуск на всех
       сразу — только явным выбором «Все в сети». */
    RD.who = 'phones';
    RD.query = '';
    const active = S.devices.find(d => d.serial === S.active && d.online);
    RD.picked = new Set(S.selected.size ? S.selected : active ? [active.serial] : []);
    RD.group = rdGroups()[0] || '';
    RD.tag = FLEET.tag || rdTags()[0] || '';
    RD.check = null;

    $('mTitle').textContent = 'Запуск сценария';
    $('mBody').innerHTML = `<div class="rd">
      <label class="bulk-row">Сценарий
        <select id="rdScen" onchange="rdScenarioChanged()">${S.scenarios.map(s =>
            `<option value="${esc(s.key)}">${esc(s.name)}</option>`).join('')}</select></label>
      <div id="rdParams"></div>
      <div class="bulk-row">Кто запускает
        <div class="rd-who" id="rdWho"></div></div>
      <label class="bulk-row rd-repeat">Повторов на каждом
        <input type="number" id="rdRepeat" value="1" min="1" max="200"></label>
      <div class="rd-check" id="rdCheck" role="status" aria-live="polite"></div>
    </div>`;
    $('mActs').innerHTML = `<button onclick="closeModal()">Отмена</button>
      <button class="primary" id="rdGo" onclick="rdGo()">Запустить</button>`;
    $('modal').querySelector('.sheet').classList.add('wide');
    const sel = $('rdScen');
    sel.value = S.scenarios.some(s => s.key === key) ? key : S.scenarios[0].key;
    openModal();
    rdScenarioChanged();
}

function rdScenarioChanged() {
    const sc = rdScenario();
    if (!sc) return;
    store.set(RD_LAST_KEY, sc.key);
    $('rdParams').innerHTML = paramsFormHtml(sc, null, 'rd_');
    rdRenderWho();
    rdRefresh();
}

function rdRenderWho() {
    const groups = rdGroups();
    const tags = rdTags();
    const btn = (who, label, disabled) => `<button class="sm${RD.who === who ? ' on' : ''}"
        ${disabled ? 'disabled' : ''} aria-pressed="${RD.who === who}"
        onclick="rdSetWho('${who}')">${label}</button>`;
    $('rdWho').innerHTML = `<div class="seg">
        ${btn('phones', esc(t('run.telefony', {n: rdOnline(S.devices.filter(d => RD.picked.has(d.serial))).length})))}
        ${btn('group', 'Группа', !groups.length)}
        ${btn('tag', 'По тегу', !tags.length)}
        ${btn('all', `Все в сети · ${rdOnline(S.devices).length}`)}
      </div>
      ${RD.who === 'phones' ? rdPickerHtml() : ''}
      ${RD.who === 'group' ? `<select id="rdGroup" onchange="RD.group=this.value;rdRefresh()">${groups.map(g =>
        `<option value="${esc(g)}" ${g === RD.group ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select>` : ''}
      ${RD.who === 'tag' ? `<select id="rdTag" aria-label="Тег" onchange="RD.tag=this.value;rdRefresh()">${tags.map(tg =>
        `<option value="${esc(tg)}" ${tg === RD.tag ? 'selected' : ''}>${esc(tg)}</option>`).join('')}</select>` : ''}`;
    const tagBtn = $('rdWho').querySelector(`[onclick="rdSetWho('tag')"]`);
    disableWithReason(tagBtn, !tags.length, t('run.tegov_net'));
}

/* Выбор телефонов прямо в окне запуска: поиск по имени, группе и тегу,
   отметка кликом. Видны только телефоны в сети — офлайн запустить нельзя,
   а сорок серых строк мешали бы найти нужные. */
function rdPickerHtml() {
    const q = RD.query.trim().toLowerCase();
    const online = S.devices.filter(d => d.online && !S.hidden.has(d.serial));
    const shown = online.filter(d => !q || [d.name, d.group, ...(d.tags || [])]
        .some(v => String(v || '').toLowerCase().includes(q)));
    return `<div class="rd-pick">
      <div class="rd-pick-bar">
        <input type="search" id="rdPickQ" placeholder="${esc(t('run.poisk_telefona'))}" value="${esc(RD.query)}"
               aria-label="${esc(t('run.poisk_telefona'))}" oninput="rdPickQuery(this.value)">
        <button class="sm ghost" onclick="rdPickShown(true)">${esc(t('run.otmetit_vidimye'))}</button>
        <button class="sm ghost" onclick="rdPickShown(false)">${esc(t('run.snyat'))}</button>
      </div>
      <div class="rd-pick-list" role="group" aria-label="${esc(t('run.telefony_dlya_zapuska'))}">${shown.length
        ? shown.map(d => `<button class="rd-ph${RD.picked.has(d.serial) ? ' on' : ''}" aria-pressed="${RD.picked.has(d.serial)}"
            onclick="rdPick('${esc(d.serial)}')"><b>${esc(d.name)}</b>${d.busy_job ? `<i>${esc(t('run.zanyat'))}</i>` : ''}${
            [d.group, ...(d.tags || [])].filter(Boolean).map(v => `<small>${esc(v)}</small>`).join('')}</button>`).join('')
        : `<span class="dim">${esc(t('run.nikogo_ne_naydeno'))}</span>`}</div>
    </div>`;
}

function rdPick(serial) {
    if (RD.picked.has(serial)) RD.picked.delete(serial);
    else RD.picked.add(serial);
    rdRenderWho();
    rdRefresh();
}

function rdPickQuery(value) {
    RD.query = value;
    rdRenderWho();
    const input = $('rdPickQ');
    if (input) {
        input.focus();
        input.setSelectionRange(value.length, value.length);
    }
}

function rdPickShown(on) {
    const q = RD.query.trim().toLowerCase();
    S.devices.filter(d => d.online && !S.hidden.has(d.serial) && (!q || [d.name, d.group, ...(d.tags || [])]
        .some(v => String(v || '').toLowerCase().includes(q))))
        .forEach(d => (on ? RD.picked.add(d.serial) : RD.picked.delete(d.serial)));
    rdRenderWho();
    rdRefresh();
}

function rdSetWho(who) {
    RD.who = who;
    rdRenderWho();
    rdRefresh();
}

/* ------------------------------------------------- сводка готовности */

function rdRefresh() {
    clearTimeout(RD.timer);
    RD.timer = setTimeout(rdPreflight, RD_PREFLIGHT_DEBOUNCE_MS);
}

async function rdPreflight() {
    const sc = rdScenario();
    const serials = rdTargets();
    const seq = ++RD.seq;
    if (!sc || !serials.length) {
        RD.check = {counts: {}, devices: {}};
        return rdRenderCheck();
    }
    try {
        const check = await post('/api/run/preflight', {scenario: sc.key, serials});
        if (seq !== RD.seq) return;   // пока ждали, выбор поменялся
        RD.check = check;
    } catch (e) {
        RD.check = null;
        $('rdCheck').innerHTML = `<div class="rd-err">${esc(e.message)}</div>`;
        return disableWithReason($('rdGo'), true, e.message);
    }
    rdRenderCheck();
}

function rdRunnable() {
    const devs = (RD.check && RD.check.devices) || {};
    return Object.keys(devs).filter(s => RD_RUNNABLE.has(devs[s].status));
}

function rdRenderCheck() {
    const {counts = {}, devices = {}} = RD.check || {};
    const sc = rdScenario();
    const parts = Object.keys(RD_STATUS).filter(k => counts[k]).map(k =>
        `<span class="rd-c rd-c--${RD_STATUS[k][1]}"><b>${counts[k]}</b> ${RD_STATUS[k][0]}</span>`);
    const problems = Object.entries(devices).filter(([, d]) => !RD_RUNNABLE.has(d.status) || d.status === 'login');
    const missing = [...new Set(problems.filter(([, d]) => d.status === 'no_account').map(([, d]) => d.platform))];
    const name = s => (S.devices.find(d => d.serial === s) || {name: s}).name;

    $('rdCheck').innerHTML = !Object.keys(devices).length
        ? '<div class="rd-empty">некого запускать — выберите телефоны</div>'
        : `<div class="rd-counts">${parts.join('<span class="rd-sep">·</span>')}</div>
      ${sc && sc.needs_accounts && sc.needs_accounts.length
            ? `<div class="rd-need">нужен аккаунт: ${sc.needs_accounts.map(p => PLATFORM_NAMES[p] || p).join(', ')}</div>` : ''}
      ${missing.map(p => `<button class="sm" onclick="rdAutobind('${p}')">
          <svg class="ic"><use href="#i-phone"/></svg>Раздать аккаунты ${PLATFORM_NAMES[p] || p}</button>`).join(' ')}
      ${problems.length ? `<details class="rd-list"${problems.length <= 5 ? ' open' : ''}>
          <summary>${problems.length} требуют внимания</summary>
          <ul>${problems.map(([s, d]) => `<li><span class="rd-c rd-c--${RD_STATUS[d.status][1]}">●</span>
            ${esc(name(s))} — ${RD_STATUS[d.status][0]}${d.platform ? ' ' + (PLATFORM_NAMES[d.platform] || d.platform) : ''}
            ${RD_RUNNABLE.has(d.status) ? '' : '<small>(пропустим)</small>'}</li>`).join('')}</ul></details>` : ''}`;

    const k = rdRunnable().length;
    const go = $('rdGo');
    go.textContent = k ? `Запустить на ${k}` : 'Запустить';
    disableWithReason(go, !k, 'Нет готовых телефонов');
}

async function rdAutobind(platform) {
    try {
        const res = await post('/api/accounts/autobind', {platform, serials: rdTargets()});
        toast(res.count ? `${PLATFORM_NAMES[platform]}: привязано ${res.count}`
            : `${PLATFORM_NAMES[platform]}: свободных аккаунтов нет — добавьте в «Аккаунтах»`,
            res.count ? 'ok' : 'bad');
        rdRefresh();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* -------------------------------------------------------------- запуск */

function rdParams() {
    return paramsRead(rdScenario(), 'rd_');
}

async function rdGo() {
    const sc = rdScenario();
    const serials = rdRunnable();
    if (!sc || !serials.length) return;
    const go = $('rdGo');
    if (go.disabled) return;
    go.disabled = true;   // двойной клик давал два пакета по 40 задач
    go.textContent = 'Запускаю…';
    try {
        const res = await post('/api/run', {
            scenario: sc.key, serials, params: rdParams(),
            repeat: Number($('rdRepeat').value) || 1,
        });
        closeModal();
        toast(`${sc.name}: запущено на ${serials.length} тел.`, 'ok');
        showRuns(res.batch);
    } catch (e) {
        toast(e.message, 'bad');
        rdRenderCheck();   // вернёт кнопке текст и состояние
    }
}

/* --------------------------------------------------------- по группам

   «VK-группа качает ленту, TG-группа пишет в чаты» — каждой группе свой
   сценарий одним нажатием. Готовность считается так же, как в основном
   окне, но коротко: сколько в группе запустится. */

function rdGroupsOpen() {
    const groups = rdGroups();
    if (!groups.length) return toast('сначала назначьте группы: выберите телефоны → Действия → Группа', 'bad');
    const opts = '<option value="">— не запускать —</option>'
        + S.scenarios.map(s => `<option value="${esc(s.key)}">${esc(s.name)}</option>`).join('');
    $('mTitle').textContent = 'Сценарии по группам';
    $('mBody').innerHTML = `<table class="grun">${groups.map(g => `<tr>
        <td><b>${esc(g)}</b> <small>${rdOnline(S.devices.filter(d => d.group === g)).length} в сети</small></td>
        <td><select data-group="${esc(g)}" onchange="rdGroupCheck(this)">${opts}</select></td>
        <td class="rd-gc" data-gc="${esc(g)}"></td></tr>`).join('')}</table>
      <label class="bulk-row rd-repeat">Повторов на каждом
        <input type="number" id="rdRepeat" value="1" min="1" max="200"></label>
      <p class="rd-need">Параметры — по умолчанию.</p>`;
    $('mActs').innerHTML = `<button onclick="closeModal()">Отмена</button>
      <button class="primary" onclick="rdGroupsGo(event)">Запустить</button>`;
    openModal();
}

async function rdGroupCheck(sel) {
    const cell = document.querySelector(`[data-gc="${CSS.escape(sel.dataset.group)}"]`);
    if (!sel.value) return setText(cell, '');
    const serials = rdOnline(S.devices.filter(d => d.group === sel.dataset.group));
    try {
        const check = await post('/api/run/preflight', {scenario: sel.value, serials});
        sel._check = check;
        const ok = Object.values(check.devices).filter(d => RD_RUNNABLE.has(d.status)).length;
        const skip = serials.length - ok;
        cell.innerHTML = `<span class="rd-c rd-c--ok"><b>${ok}</b> запустятся</span>`
            + (skip ? ` <span class="rd-c rd-c--bad">${skip} пропустим</span>` : '');
    } catch (e) {
        setText(cell, e.message);
    }
}

async function rdGroupsGo(ev) {
    const btn = ev && ev.currentTarget;
    if (btn) {
        if (btn.disabled) return;
        btn.disabled = true;
        btn.textContent = 'Запускаю…';
    }
    const repeat = Number($('rdRepeat').value) || 1;
    const plan = [...document.querySelectorAll('.grun select')].filter(sel => sel.value);
    if (!plan.length) return toast('выберите сценарий хотя бы для одной группы', 'bad');
    let total = 0, phones = 0;
    for (const sel of plan) {
        if (!sel._check) await rdGroupCheck(sel);
        const devs = (sel._check && sel._check.devices) || {};
        const serials = Object.keys(devs).filter(s => RD_RUNNABLE.has(devs[s].status));
        if (!serials.length) continue;
        try {
            const res = await post('/api/run', {scenario: sel.value, serials, repeat});
            total += res.jobs.length;
            phones += serials.length;
        } catch (e) {
            toast(`${sel.dataset.group}: ${e.message}`, 'bad');
        }
    }
    closeModal();
    if (total) {
        toast(`запущено на ${phones} тел.`, 'ok');
        showRuns();
    } else {
        toast('в группах нет готовых телефонов', 'bad');
    }
}

window.openRunDialog = openRunDialog;
