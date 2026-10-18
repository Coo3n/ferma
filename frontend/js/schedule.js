/* Смены — запуск сценария по расписанию («Запуски» → «Расписание»).

   Каждому телефону сервер сам раздаёт свои моменты внутри окна, не ближе
   20 минут друг к другу, — телефоны не стартуют разом. Здесь только список
   смен, форма и план дня полосой 00–24. */

const SCH = {items: [], loaded: false, open: new Set(), plans: {}, timer: null};
const SCH_POLL_MS = 15000;
const SCH_DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const SCH_STATUS = {wait: 'ждёт', started: 'запущен', skipped: 'пропущен'};

async function loadSchedules() {
    try {
        SCH.items = await api('/api/schedules');
        SCH.loaded = true;
    } catch (e) {
        if (!SCH.loaded) toast('расписание: ' + e.message, 'bad');
        return;
    }
    renderSchedules();
    /* Открытые планы освежаем вместе со списком: статусы «ждёт → запущен»
       меняются сами по себе. */
    SCH.open.forEach(id => schLoadPlan(id));
}

function schEnsurePolling() {
    if (SCH.timer) return;
    SCH.timer = setInterval(() => {
        if (S.view === 'schedule' && !document.hidden) loadSchedules();
    }, SCH_POLL_MS);
}

function schShow() {
    schEnsurePolling();
    loadSchedules();
}

/* «через 2 ч 15 мин», «через 3 мин», «завтра в 10:42». */
function schWhen(ts) {
    if (!ts) return '';
    const now = Date.now() / 1000;
    const diff = Math.max(0, ts - now);
    const at = new Date(ts * 1000);
    const hm = at.toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'});
    if (diff < 60) return 'вот-вот';
    if (diff < 3600) return `через ${Math.round(diff / 60)} мин`;
    const today = new Date();
    if (at.toDateString() === today.toDateString()) {
        const h = Math.floor(diff / 3600), m = Math.round((diff % 3600) / 60);
        return `через ${h} ч${m ? ` ${m} мин` : ''}`;
    }
    const tomorrow = new Date(today.getTime() + 86400000);
    if (at.toDateString() === tomorrow.toDateString()) return `завтра в ${hm}`;
    return `${SCH_DAYS[(at.getDay() + 6) % 7].toLowerCase()} в ${hm}`;
}

function schTargetText(t) {
    if (t.kind === 'group') return `группа «${esc(t.value)}»`;
    if (t.kind === 'tag') return `тег «${esc(t.value)}»`;
    if (t.kind === 'serials') return `${t.value.length} выбранных телефонов`;
    return 'все телефоны';
}

function schDaysText(days) {
    if (days.length === 7) return 'каждый день';
    if (days.join() === '0,1,2,3,4') return 'по будням';
    if (days.join() === '5,6') return 'по выходным';
    return days.map(d => SCH_DAYS[d]).join(', ');
}

function renderSchedules() {
    const box = $('schList');
    setText($('schCount'), SCH.items.length ? `${SCH.items.length} ${declOfNum(SCH.items.length, ['смена', 'смены', 'смен'])}` : '');
    if (!SCH.loaded) return;
    if (!SCH.items.length) {
        setHTML(box, emptyBig({
            art: 'job',
            title: 'Смен пока нет',
            text: 'Сценарий по расписанию, каждый телефон — в своё случайное время.',
            action: {label: 'Новая смена', icon: 'plus', onClick: 'schEdit()'},
        }));
        return;
    }
    setHTML(box, `<div class="sch-cards">${SCH.items.map(schCardHtml).join('')}</div>`);
    schRefreshWhen();
}

function schRefreshWhen() {
    document.querySelectorAll('#schList .sch-when[data-at]').forEach(node =>
        setText(node, schWhen(Number(node.dataset.at))));
}

function schCardHtml(s) {
    const open = SCH.open.has(s.id);
    /* «через 12 мин» меняется сам по себе — в разметке только момент, текст
       вписывает schRefreshWhen(). Иначе список пересобирался бы каждый опрос
       и сбрасывал взведённое «Удалить» и фокус. */
    const next = s.enabled ? (s.next_at ? '' : 'некого запускать') : 'выключена';
    const runs = s.runs_per_day === 1 ? '1 раз' : `${s.runs_per_day} раза`;
    return `<article class="sch-card${s.enabled ? '' : ' off'}" data-id="${esc(s.id)}">
      <div class="sch-head">
        <label class="sch-switch" title="${s.enabled ? 'Выключить смену' : 'Включить смену'}">
          <input type="checkbox" ${s.enabled ? 'checked' : ''} onchange="schToggle('${esc(s.id)}', this)"
                 aria-label="Смена «${esc(s.name)}» включена"><span></span></label>
        <div class="sch-title">
          <b>${esc(s.name)}</b>
          <span class="dim">${esc(s.scenario_name)}${s.scenario_missing ? ' <em class="sch-bad">— сценарий удалён</em>' : ''}</span>
        </div>
        <div class="sch-next${s.enabled && s.next_at ? '' : ' dim'}">
          <span class="dim">Следующий запуск</span><b${s.enabled && s.next_at ? ` class="sch-when" data-at="${esc(s.next_at)}"` : ''}>${next}</b></div>
      </div>
      <div class="sch-facts">
        <span>${schTargetText(s.target)}</span>
        <span>${schDaysText(s.days)}</span>
        <span>с ${esc(s.window.from)} до ${esc(s.window.to)}</span>
        <span>${runs} в день на телефон</span>
      </div>
      <div class="sch-acts">
        <button class="sm" onclick="schTogglePlan('${esc(s.id)}')" aria-expanded="${open}">
          <svg class="ic" aria-hidden="true"><use href="#i-${open ? 'up' : 'down'}"/></svg>
          План на сегодня</button>
        <span class="sp"></span>
        <button class="sm" onclick="schEdit('${esc(s.id)}')">
          <svg class="ic" aria-hidden="true"><use href="#i-pencil"/></svg>Изменить</button>
        <button class="sm danger" onclick="schDelete('${esc(s.id)}', this)">
          <svg class="ic" aria-hidden="true"><use href="#i-trash"/></svg><span>Удалить</span></button>
      </div>
      ${open ? `<div class="sch-plan" id="schPlan-${esc(s.id)}">${SCH.plans[s.id] ? schPlanHtml(SCH.plans[s.id]) : '<p class="dim">Загружаем план…</p>'}</div>` : ''}
    </article>`;
}

async function schToggle(id, input) {
    input.disabled = true;
    try {
        const s = await post(`/api/schedules/${encodeURIComponent(id)}/toggle`, {enabled: input.checked});
        toast(s.enabled ? 'смена включена' : 'смена выключена', 'ok');
        await loadSchedules();
    } catch (e) {
        input.checked = !input.checked;
        toast(e.message, 'bad');
    } finally {
        input.disabled = false;
    }
}

async function schDelete(id, btn) {
    if (!armConfirm(btn, 'Точно удалить?')) return;
    btn.disabled = true;
    try {
        await api(`/api/schedules/${encodeURIComponent(id)}`, {method: 'DELETE'});
        SCH.open.delete(id);
        delete SCH.plans[id];
        toast('смена удалена', 'ok');
        await loadSchedules();
    } catch (e) {
        btn.disabled = false;
        toast(e.message, 'bad');
    }
}

/* ------------------------------------------------------------- план дня */

function schTogglePlan(id) {
    if (SCH.open.has(id)) SCH.open.delete(id);
    else {
        SCH.open.add(id);
        schLoadPlan(id);
    }
    renderSchedules();
}

async function schLoadPlan(id) {
    try {
        SCH.plans[id] = await api(`/api/schedules/${encodeURIComponent(id)}/plan`);
    } catch (e) {
        SCH.plans[id] = {error: e.message};
    }
    setHTML($('schPlan-' + id), schPlanHtml(SCH.plans[id]));
}

function schPlanHtml(p) {
    if (p.error) return `<p class="sch-bad">${esc(p.error)}</p>`;
    if (!p.working) return '<p class="dim">Сегодня у смены выходной.</p>';
    if (!p.phones.length) return '<p class="dim">В смене сейчас нет телефонов.</p>';
    const day0 = new Date(p.date + 'T00:00:00').getTime() / 1000;
    const pos = ts => Math.min(100, Math.max(0, (ts - day0) / 864)).toFixed(2);
    const now = Date.now() / 1000;
    const nowMark = now >= day0 && now < day0 + 86400
        ? `<i class="sch-now" style="left:${pos(now)}%" title="сейчас"></i>` : '';
    const band = `<i class="sch-band" style="left:${pos(p.window.from)}%;width:${(pos(p.window.to) - pos(p.window.from)).toFixed(2)}%"></i>`;
    const counts = {wait: 0, started: 0, skipped: 0};
    p.phones.forEach(ph => ph.slots.forEach(sl => counts[sl.status]++));
    const hm = ts => new Date(ts * 1000).toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'});
    const rows = p.phones.map(ph => `<div class="sch-row">
        <span class="sch-ph${ph.online ? '' : ' dim'}" title="${esc(ph.name)}">${esc(ph.name)}</span>
        <div class="sch-track">${band}${nowMark}${ph.slots.map(sl => {
            const tip = `${hm(sl.at)} — ${SCH_STATUS[sl.status]}${sl.note ? ': ' + sl.note : ''}`;
            return `<i class="sch-dot" data-st="${sl.status}" style="left:${pos(sl.at)}%" title="${esc(tip)}"></i>`;
        }).join('')}</div>
      </div>`).join('');
    const hours = [0, 6, 12, 18, 24].map(h =>
        `<span style="left:${(h / 24 * 100).toFixed(2)}%">${String(h).padStart(2, '0')}</span>`).join('');
    return `<div class="sch-legend">
        <span><i class="sch-dot" data-st="wait"></i>ждёт · ${counts.wait}</span>
        <span><i class="sch-dot" data-st="started"></i>запущен · ${counts.started}</span>
        <span><i class="sch-dot" data-st="skipped"></i>пропущен · ${counts.skipped}</span>
        <span class="dim">наведите на точку — подробности</span>
      </div>
      <div class="sch-rows">${rows}
        <div class="sch-row sch-axis"><span></span><div class="sch-hours">${hours}</div></div>
      </div>`;
}

/* ---------------------------------------------------------------- форма */

function schDeviceTags() {
    const all = new Set();
    S.devices.forEach(d => (d.tags || []).forEach(t => all.add(t)));
    return [...all].sort((a, b) => a.localeCompare(b, 'ru'));
}

function schDeviceGroups() {
    return [...new Set(S.devices.map(d => d.group).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ru'));
}

function schEdit(id, scenarioKey) {
    const s = id ? SCH.items.find(x => x.id === id) : null;
    if (!S.scenarios.length) return toast('сначала создайте сценарий', 'bad');
    const cur = s || {name: '', scenario: scenarioKey || S.scenario || S.scenarios[0].key, params: {}, target: {kind: 'all', value: null},
        days: [0, 1, 2, 3, 4, 5, 6], window: {from: '10:00', to: '14:00'}, runs_per_day: 1};
    const groups = schDeviceGroups(), tags = schDeviceTags();
    const kind = cur.target.kind;
    const sel = cur.target.kind === 'serials' ? new Set(cur.target.value) : new Set();
    $('mTitle').textContent = s ? 'Изменить смену' : 'Новая смена';
    $('mBody').innerHTML = `<div class="sch-form" id="schForm" data-id="${esc(id || '')}">
      <label class="bulk-row">Название <input id="schName" value="${esc(cur.name)}" placeholder="например, «Утренний прогрев»" autocomplete="off"></label>
      <label class="bulk-row">Сценарий <select id="schScen" onchange="schParamsRender()">${S.scenarios.map(x =>
          `<option value="${esc(x.key)}"${x.key === cur.scenario ? ' selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label>
      <div class="sch-params" id="schParams"></div>
      <div class="bulk-row">На каких телефонах
        <div class="seg sch-kind" role="radiogroup" aria-label="На каких телефонах">
          ${[['all', 'Все'], ['group', 'Группа'], ['tag', 'Тег'], ['serials', 'Выбрать']].map(([k, w]) =>
              `<button type="button" class="sm${k === kind ? ' on' : ''}" role="radio" aria-checked="${k === kind}"
                       data-kind="${k}" onclick="schKind('${k}')">${w}</button>`).join('')}
        </div>
        <select id="schGroup" ${kind === 'group' ? '' : 'hidden'} aria-label="Группа">${groups.length
            ? groups.map(g => `<option${kind === 'group' && cur.target.value === g ? ' selected' : ''}>${esc(g)}</option>`).join('')
            : '<option value="">групп пока нет</option>'}</select>
        <select id="schTag" ${kind === 'tag' ? '' : 'hidden'} aria-label="Тег">${tags.length
            ? tags.map(t => `<option${kind === 'tag' && cur.target.value === t ? ' selected' : ''}>${esc(t)}</option>`).join('')
            : '<option value="">тегов пока нет</option>'}</select>
        <div class="sch-phones" id="schPhones" ${kind === 'serials' ? '' : 'hidden'}>${S.devices.map(d =>
            `<label><input type="checkbox" value="${esc(d.serial)}"${sel.has(d.serial) ? ' checked' : ''}> ${esc(d.name)}</label>`).join('')
            || '<span class="dim">телефонов не видно</span>'}</div>
      </div>
      <div class="bulk-row">Дни
        <div class="sch-days" role="group" aria-label="Дни недели">${SCH_DAYS.map((w, i) =>
            `<button type="button" class="sm${cur.days.includes(i) ? ' on' : ''}" aria-pressed="${cur.days.includes(i)}"
                     data-day="${i}" onclick="schDay(this)">${w}</button>`).join('')}</div>
      </div>
      <div class="sch-inline">
        <label class="bulk-row">С <input type="time" id="schFrom" value="${esc(cur.window.from)}"></label>
        <label class="bulk-row">До <input type="time" id="schTo" value="${esc(cur.window.to)}"></label>
        <label class="bulk-row">Раз в день <input type="number" id="schRuns" min="1" max="10" value="${cur.runs_per_day}"></label>
      </div>
      <p class="sch-hint dim">Каждый телефон — в случайное время внутри окна, не чаще раза в 20 мин.</p>
    </div>`;
    $('mActs').innerHTML = `<button onclick="closeModal()">Отмена</button>
      <button class="primary" id="schSave" onclick="schSave(this)">${s ? 'Сохранить' : 'Создать смену'}</button>`;
    SCH.formParams = {scenario: cur.scenario, values: cur.params || {}};
    schParamsRender();
    openModal();
    $('schName').focus();
}

/* Настройки выбранного сценария. Сохранённые значения смены подставляем
   только для её же сценария: у другого сценария поля другие. */
function schParamsRender() {
    const key = $('schScen').value;
    const sc = S.scenarios.find(x => x.key === key);
    const values = SCH.formParams && SCH.formParams.scenario === key ? SCH.formParams.values : null;
    const html = paramsFormHtml(sc, values, 'schp_');
    $('schParams').innerHTML = html ? `<div class="sch-params-h">Настройки сценария</div>${html}` : '';
}

function schKind(kind) {
    document.querySelectorAll('#schForm .sch-kind button').forEach(b => {
        const on = b.dataset.kind === kind;
        b.classList.toggle('on', on);
        b.setAttribute('aria-checked', on);
    });
    $('schGroup').hidden = kind !== 'group';
    $('schTag').hidden = kind !== 'tag';
    $('schPhones').hidden = kind !== 'serials';
}

function schDay(btn) {
    const on = !btn.classList.contains('on');
    btn.classList.toggle('on', on);
    btn.setAttribute('aria-pressed', on);
}

async function schSave(btn) {
    const form = $('schForm');
    const id = form.dataset.id;
    const kind = (form.querySelector('.sch-kind button.on') || {}).dataset?.kind || 'all';
    const value = kind === 'group' ? $('schGroup').value
        : kind === 'tag' ? $('schTag').value
        : kind === 'serials' ? [...form.querySelectorAll('#schPhones input:checked')].map(i => i.value)
        : null;
    const data = {
        name: $('schName').value.trim(),
        scenario: $('schScen').value,
        params: paramsRead(S.scenarios.find(x => x.key === $('schScen').value), 'schp_'),
        target: {kind, value},
        days: [...form.querySelectorAll('.sch-days button.on')].map(b => +b.dataset.day),
        window: {from: $('schFrom').value, to: $('schTo').value},
        runs_per_day: +$('schRuns').value || 1,
    };
    btn.disabled = true;
    try {
        if (id) {
            await api(`/api/schedules/${encodeURIComponent(id)}`, {
                method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data),
            });
        } else {
            await post('/api/schedules', data);
        }
        closeModal();
        toast(id ? 'смена сохранена' : 'смена создана', 'ok');
        delete SCH.plans[id];
        await loadSchedules();
    } catch (e) {
        toast(e.message, 'bad');
    } finally {
        btn.disabled = false;
    }
}

window.schShow = schShow;
window.schEdit = schEdit;
