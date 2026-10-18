'use strict';

/* Инструменты конструктора поверх recorder.js: отмена/возврат, дубли,
   «необязательный шаг» и повторы, группы шагов, превью жестов на экране,
   дифф с сохранённой версией и проверка на устройстве (валидация, запуск
   с шага N, замедление, живая подсветка шага, отчёт).

   Файл грузится после recorder.js и не переопределяет его состояние: REC
   общий, а недостающее подключается обёртками (recSave, recRender, ...).
   Имена с префиксом st — внутренние, rec* — вызываются из разметки. */

const ST_FLEX = new Set(['click', 'tap', 'long_tap', 'swipe', 'type', 'key',
    'launch_app', 'open_url', 'stop_app', 'shell', 'screenshot', 'unlock']);
const ST_HIST_MAX = 60;
const ST_HIST_MERGE_MS = 700;   // правки внутри окна — одна запись отмены (набор текста)
const ST_POLL_MS = 700;
const ST_SPEEDS = [['1', 'Обычная скорость'], ['0.5', 'Вдвое медленнее'], ['0.25', 'В четыре раза медленнее']];

REC.sel = new Set();
REC.run = null;        // {id, job, active, hSig, timer}
REC.runOpen = false;
REC.base = null;       // снимок сохранённой версии — для «Изменения»
REC.savedSig = null;   // подпись сохранённой версии — чтобы знать, «грязный» ли сценарий
REC.issues = new Map();
REC.runAfterAt = 0;
REC.runSpeed = '1';

/* --------------------------------------------------------------- история */

const stHist = {undo: [], redo: [], last: {steps: [], params: {}}, lastSig: '', at: 0, busy: false};

function stClone(step) {
    const {shot, crop, ...rest} = step;
    const out = JSON.parse(JSON.stringify(rest));
    out.shot = shot;   // тяжёлое — по ссылке, копировать десятки кадров на каждую правку дорого
    out.crop = crop;
    return out;
}

function stSnap() {
    return {steps: REC.steps.map(stClone), params: JSON.parse(JSON.stringify(REC.params || {}))};
}

function stSig(snap) {
    return JSON.stringify([snap.steps.map(step => {
        const {shot, crop, ...rest} = step;
        return [rest, !!crop];
    }), snap.params]);
}

stHist.lastSig = stSig(stHist.last);

function stHistReset() {
    stHist.undo = [];
    stHist.redo = [];
    stHist.last = stSnap();
    stHist.lastSig = stSig(stHist.last);
    stHist.at = 0;
    stSyncButtons();
}

function stHistNote() {
    if (stHist.busy) return;
    const now = stSnap();
    const sig = stSig(now);
    if (sig === stHist.lastSig) return;
    const time = Date.now();
    if (time - stHist.at > ST_HIST_MERGE_MS) {
        stHist.undo.push(stHist.last);
        if (stHist.undo.length > ST_HIST_MAX) stHist.undo.shift();
    }
    stHist.at = time;
    stHist.redo = [];
    stHist.last = now;
    stHist.lastSig = sig;
    if (REC.run && REC.run.hSig !== sig) REC.run.stale = true;
    stSyncButtons();
}

function stApply(snap) {
    stHist.busy = true;
    try {
        REC.steps = snap.steps.map(stClone);
        REC.params = JSON.parse(JSON.stringify(snap.params));
        REC.open = null;
        REC.sel.clear();
        stHist.last = stSnap();
        stHist.lastSig = stSig(stHist.last);
        stHist.at = 0;
        if (REC.run && REC.run.hSig !== stHist.lastSig) REC.run.stale = true;
        recRender();
        stOrigSave();
    } finally {
        stHist.busy = false;
    }
    stSyncButtons();
}

function recUndo() {
    if (!stHist.undo.length) return;
    stHist.redo.push(stHist.last);
    stApply(stHist.undo.pop());
    toast('отменено');
}

function recRedo() {
    if (!stHist.redo.length) return;
    stHist.undo.push(stHist.last);
    stApply(stHist.redo.pop());
    toast('возвращено');
}

function stSyncButtons() {
    const undo = $('btnRecUndo'), redo = $('btnRecRedo');
    if (undo) undo.disabled = !stHist.undo.length;
    if (redo) redo.disabled = !stHist.redo.length;
    const diff = $('btnRecDiff');
    if (diff) diff.hidden = !REC.base;
    const run = $('btnRecRun');
    if (run) {
        disableWithReason(run, !REC.steps.length || !!REC.teach,
            REC.teach ? 'В режиме обучения проверка недоступна'
                : 'Сначала запишите хотя бы один шаг');
    }
}

/* Ctrl/⌘+Z и Ctrl/⌘+Y действуют, пока открыт конструктор и фокус не в поле
   ввода: там своя, встроенная в браузер отмена набора текста. */
document.addEventListener('keydown', ev => {
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
    const key = ev.key.toLowerCase();
    if (key !== 'z' && key !== 'y') return;
    if (S.view !== 'device' || (!REC.steps.length && !stHist.undo.length && !stHist.redo.length)) return;
    const t = ev.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))
        && t.type !== 'checkbox') return;
    ev.preventDefault();
    if (key === 'y' || ev.shiftKey) recRedo();
    else recUndo();
});

document.addEventListener('keydown', ev => {
    if (ev.key !== 'Escape' || S.view !== 'device' || !REC.sel.size) return;
    if (document.querySelector('#modal.on')) return;   // Esc закрывает модалку, не выбор
    REC.sel.clear();
    recRender();
});

/* ----------------------------------------------------- обёртки recorder.js */

const stOrigSave = window.recSave;
window.recSave = function () {
    stHistNote();
    return stOrigSave.apply(this, arguments);
};

const stOrigRender = window.recRender;
window.recRender = function () {
    stOrigRender.apply(this, arguments);
    stRunSyncOptions();
    stRunPaint();
    stSyncButtons();
};

const stOrigSync = window.recSync;
window.recSync = function () {
    stOrigSync.apply(this, arguments);
    stSyncButtons();
};

/* Открытие правки: снимок файла — точка отсчёта и для «Изменений», и для
   вопроса «сохранён ли сценарий»; история начинается с него. */
const stOrigEdit = window.editScenario;
window.editScenario = async function (key) {
    await stOrigEdit.apply(this, arguments);
    if (REC.edit && REC.edit.key === key) {
        REC.base = stSnap();
        REC.savedSig = stCurSig();
    }
    stHistReset();
    stSyncButtons();
};

function stAfterExit() {
    if (REC.steps.length || REC.edit) return;   // «остаться в конструкторе» — ничего не сбрасываем
    REC.base = null;
    REC.savedSig = null;
    REC.sel.clear();
    REC.issues = new Map();
    stRunReset();
    stHistReset();
}

for (const name of ['recSubmit', 'recModeOff', 'recTeachSubmit']) {
    const orig = window[name];
    if (typeof orig !== 'function') continue;
    window[name] = async function () {
        const result = await orig.apply(this, arguments);
        stAfterExit();
        return result;
    };
}

/* «Создать записью» всегда начинает НОВЫЙ сценарий. Раньше кнопка звала
   recOpen() как есть, и после правки (или «остаться в конструкторе») в
   конструкторе оставался прежний сценарий. Черновик правки лежит под ключом
   сценария и не теряется. */
function recNew() {
    if (!S.active || !(S.devices.find(d => d.serial === S.active) || {}).online) {
        return pickPhone('На каком телефоне записывать?', serial => {
            openDevice(serial);
            recNew();
        });
    }
    if (REC.edit || REC.teach) {
        REC.edit = null;
        REC.teach = null;
        REC.steps = [];
        REC.params = {};
        REC.open = null;
        REC.baseWidth = null;
        REC.base = null;
        REC.savedSig = null;
        REC.sel.clear();
        REC.issues = new Map();
        recBanner('');
        stRunReset();
        stHistReset();
    }
    recOpen();
}

/* -------------------------------------------- необязательность и повторы */

function recBadges(step) {
    if (!ST_FLEX.has(step.kind)) return '';
    const fail = stFailGet(step);
    let html = '';
    if (fail.skip) {
        html += `<span class="rs-badge opt" title="${esc(t('rec.badge_skip_hint'))}">${esc(t('rec.badge_skip'))}</span>`;
    }
    if (fail.tries > 1) {
        html += `<span class="rs-badge retry" title="${esc(t('rec.badge_tries_hint', {n: fail.tries}))}">×${fail.tries}</span>`;
    }
    return html;
}

/* «Если не нашёл» — одна фраза вместо «необязательный» + «повторов»:
   оператору нужен ответ «что будет, если не вышло», а не два флага. */
function recFlexEditor(step) {
    if (!ST_FLEX.has(step.kind)) return '';
    const fail = stFailGet(step);
    const tries = stFailTriesOptions(fail.tries).map(n =>
        `<option value="${n}" ${fail.tries === n ? 'selected' : ''}>${n}</option>`).join('');
    return `<div class="rs-flex rs-fail">
    <span class="rs-fail-h">${esc(t('rec.nenashel'))}:</span>
    <label>${esc(t('rec.nenashel_probovat'))}
      <select onchange="recSetFail(${step.id}, 'tries', this.value)">${tries}</select>
      ${esc(t('rec.nenashel_raz'))}</label>
    <select onchange="recSetFail(${step.id}, 'skip', this.value === '1')"
            aria-label="${esc(t('rec.nenashel'))}">
      <option value="0" ${fail.skip ? '' : 'selected'}>${esc(t('rec.nenashel_stop'))}</option>
      <option value="1" ${fail.skip ? 'selected' : ''}>${esc(t('rec.nenashel_skip'))}</option>
    </select>
  </div>`;
}

function recSetFail(id, field, value) {
    const step = recFind(id);
    if (!step || !ST_FLEX.has(step.kind)) return;
    stFailSet(step, {[field]: value});
    recRender();
    recSave();
}

/* Предпросмотр строки зеркалит codegen._flexible. */
const stOrigCode = window.recCode;
window.recCode = function (step, index) {
    const code = stOrigCode.apply(this, arguments);
    if ((step.optional || step.retries) && ST_FLEX.has(step.kind) && !code.includes('\n')) {
        const extra = [];
        if (step.retries) extra.push(`retries=${step.retries}`);
        if (step.optional) extra.push('optional=True');
        extra.push(`what=${JSON.stringify('шаг ' + (index + 1))}`);
        return `ctx.attempt(lambda: ${code}, ${extra.join(', ')})`;
    }
    return code;
};

/* ----------------------------------------------------------------- дубли */

function stCopyOf(step) {
    const copy = stClone(step);
    copy.id = REC.nextId++;
    if (copy.pos) copy.pos = [copy.pos[0] + 24, copy.pos[1] + 24];
    copy.cropName = null;
    return copy;
}

function recDup(id) {
    const index = REC.steps.findIndex(step => step.id === id);
    if (index < 0) return;
    const copy = stCopyOf(REC.steps[index]);
    REC.steps.splice(index + 1, 0, copy);
    REC.open = copy.id;
    recRender();
    recSave();
    toast(`шаг ${index + 1} продублирован`);
}

/* --------------------------------------------------------- группы шагов */

let stSelAnchor = null;

function recSelToggle(id, ev) {
    if (ev && ev.shiftKey && stSelAnchor != null) {
        const a = REC.steps.findIndex(step => step.id === stSelAnchor);
        const b = REC.steps.findIndex(step => step.id === id);
        if (a >= 0 && b >= 0) {
            for (let i = Math.min(a, b); i <= Math.max(a, b); i++) REC.sel.add(REC.steps[i].id);
        }
    } else if (REC.sel.has(id)) {
        REC.sel.delete(id);
    } else {
        REC.sel.add(id);
    }
    stSelAnchor = id;
    recRender();
}

function recSelClear() {
    REC.sel.clear();
    recRender();
}

function recSelAll() {
    REC.steps.forEach(step => REC.sel.add(step.id));
    recRender();
}

function recSelBar() {
    if (!REC.sel.size) return '';
    const retries = [0, 1, 2, 3, 5].map(n =>
        `<option value="${n}">${n ? 'повторов: ' + n : 'без повторов'}</option>`).join('');
    return `<div class="selbar" role="toolbar" aria-label="Действия над выбранными шагами">
    <span class="selbar-n"><b>${REC.sel.size}</b> выбрано</span>
    <div class="selbar-grp">
      <button class="sm" onclick="recSelOptional()"
              title="Переключить «необязательный»">${recIcon('shield')} необязательные</button>
      <select class="sm" onchange="recSelRetries(this.value)" aria-label="Повторы для выбранных шагов">
        <option value="">↻ повторы</option>${retries}</select>
    </div>
    <div class="selbar-grp">
      <label class="selbar-pause">пауза
        <input type="number" id="selPause" min="0.1" step="0.1" value="1" aria-label="Секунды паузы"> с</label>
      <button class="sm" onclick="recSelPause()" title="Вставить паузу после каждого выбранного шага">после каждого</button>
    </div>
    <div class="selbar-grp">
      <span class="selbar-k">${esc(t('rec.v_blok'))}</span>
      <button class="sm" onclick="recSelBlock('loop')" title="${esc(t('rec.blok_povtor_podskazka'))}">${recIcon('rotate')} ${esc(t('rec.blok_povtor'))}</button>
      <button class="sm" onclick="recSelBlock('chance')" title="${esc(t('rec.blok_shans_podskazka'))}">${recIcon('dice')} ${esc(t('rec.blok_shans'))}</button>
      <button class="sm" onclick="recSelBlock('until')" title="${esc(t('rec.blok_poka_podskazka'))}">${recIcon('search')} ${esc(t('rec.blok_poka'))}</button>
      <button class="sm" onclick="recSelBlock('if_seen')" title="${esc(t('rec.blok_esli_podskazka'))}">${recIcon('eye-off')} ${esc(t('rec.blok_esli'))}</button>
    </div>
    <div class="selbar-grp">
      <button class="sm" onclick="recSelDup()">${recIcon('copy')} дублировать</button>
      <button class="sm danger" onclick="recSelDelete()">${recIcon('trash')} удалить</button>
    </div>
    <span class="sp"></span>
    <button class="sm ghost" onclick="recSelAll()">все</button>
    <button class="sm ghost" onclick="recSelClear()" title="Снять выбор (Esc)">снять</button>
  </div>`;
}

function stSelected() {
    return REC.steps.filter(step => REC.sel.has(step.id));
}

function recSelOptional() {
    const flex = stSelected().filter(step => ST_FLEX.has(step.kind));
    if (!flex.length) {
        toast('среди выбранных нет шагов, которым это применимо', 'bad');
        return;
    }
    const make = !flex.every(step => step.optional);
    flex.forEach(step => { step.optional = make; });
    recRender();
    recSave();
}

function recSelRetries(value) {
    if (value === '') return;
    const flex = stSelected().filter(step => ST_FLEX.has(step.kind));
    if (!flex.length) {
        toast('среди выбранных нет шагов, которым это применимо', 'bad');
        recRender();
        return;
    }
    flex.forEach(step => { step.retries = Number(value) || 0; });
    recRender();
    recSave();
}

function recSelPause() {
    const seconds = Math.max(0.1, Number(($('selPause') || {}).value) || 1);
    const chosen = new Set(REC.sel);
    const out = [];
    for (const step of REC.steps) {
        out.push(step);
        if (chosen.has(step.id)) {
            out.push({id: REC.nextId++, kind: 'sleep', args: {seconds: seconds},
                param: null, note: '', warn: '',
                parent: blockIsHead(step) ? step.id : (step.parent ?? null)});
        }
    }
    REC.steps = out;
    recRender();
    recSave();
    toast(`пауз добавлено: ${chosen.size}`);
}

function recSelDup() {
    const chosen = stSelected();
    if (!chosen.length) return;
    const last = REC.steps.indexOf(chosen[chosen.length - 1]);
    const copies = chosen.map(stCopyOf);
    REC.steps.splice(last + 1, 0, ...copies);
    REC.sel = new Set(copies.map(step => step.id));
    recRender();
    recSave();
    toast(`продублировано: ${copies.length}`);
}

function recSelDelete() {
    const count = REC.sel.size;
    REC.steps = REC.steps.filter(step => !REC.sel.has(step.id));
    REC.sel.clear();
    recPrune();
    recRender();
    recSave();
    toast(`удалено: ${count} (Ctrl/⌘+Z вернёт)`);
}

/* -------------------------------------------------- превью жеста на экране */

function stGestureSvg(step, width, height) {
    const a = step.args || {};
    const px = (x, y) => [x * width, y * height];
    const num = v => Number.isFinite(Number(v)) ? Number(v) : null;
    if (step.kind === 'swipe') {
        const v = [a.x1, a.y1, a.x2, a.y2].map(num);
        if (v.some(x => x === null)) return '';
        const [x1, y1] = px(v[0], v[1]);
        const [x2, y2] = px(v[2], v[3]);
        /* Живой режим гнёт свайп: показываем лёгкую дугу, а не линейку. */
        const dx = x2 - x1, dy = y2 - y1;
        const len = Math.hypot(dx, dy) || 1;
        const cx = (x1 + x2) / 2 - dy / len * len * 0.06;
        const cy = (y1 + y2) / 2 + dx / len * len * 0.06;
        const ang = Math.atan2(y2 - cy, x2 - cx);
        const head = [[0, 0], [-14, -7], [-14, 7]].map(([hx, hy]) =>
            `${(x2 + hx * Math.cos(ang) - hy * Math.sin(ang)).toFixed(1)},`
            + `${(y2 + hx * Math.sin(ang) + hy * Math.cos(ang)).toFixed(1)}`).join(' ');
        const secs = num(a.duration) || 0.25;
        return `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">
      <path class="g-line" d="M${x1.toFixed(1)},${y1.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}"
            pathLength="1" style="animation-duration:${Math.max(0.5, secs * 2.5)}s"/>
      <circle class="g-dot" cx="${x1.toFixed(1)}" cy="${y1.toFixed(1)}" r="9"/>
      <polygon class="g-head" points="${head}"/>
      <text class="g-txt" x="${((x1 + x2) / 2 + 12).toFixed(1)}" y="${((y1 + y2) / 2).toFixed(1)}">${secs} с</text></svg>`;
    }
    let point = null, long = false;
    if (step.kind === 'tap' || step.kind === 'long_tap') {
        const x = num(a.x), y = num(a.y);
        if (x !== null && y !== null) point = px(x, y);
        long = step.kind === 'long_tap';
    } else if (step.kind === 'click' && step.point) {
        point = px(step.point[0], step.point[1]);
    }
    if (point) {
        return `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">
      <circle class="g-ring ${long ? 'long' : ''}" cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="18"/>
      <circle class="g-dot" cx="${point[0].toFixed(1)}" cy="${point[1].toFixed(1)}" r="5"/></svg>`;
    }
    if (step.kind === 'click' && step.bounds) {
        const [x1, y1, x2, y2] = step.bounds;
        return `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">
      <rect class="g-box" x="${x1 * width}" y="${y1 * height}" width="${(x2 - x1) * width}" height="${(y2 - y1) * height}" rx="4"/></svg>`;
    }
    return '';
}

function stGestureShow(id) {
    const step = recFind(id);
    const img = $('screen');
    if (!step || !img || !img.parentElement) return;
    const rect = img.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const svg = stGestureSvg(step, Math.round(rect.width), Math.round(rect.height));
    if (!svg) {
        stGestureHide();
        return;
    }
    const stage = img.parentElement;
    const at = stage.getBoundingClientRect();
    let box = $('recGest');
    if (!box) {
        box = document.createElement('div');
        box.id = 'recGest';
        box.className = 'rec-gest';
        stage.appendChild(box);
    }
    Object.assign(box.style, {
        left: (rect.left - at.left) + 'px', top: (rect.top - at.top) + 'px',
        width: rect.width + 'px', height: rect.height + 'px', display: 'block',
    });
    box.innerHTML = svg;
}

function stGestureHide() {
    const box = $('recGest');
    if (box) {
        box.style.display = 'none';
        box.innerHTML = '';
    }
}

document.addEventListener('mouseover', ev => {
    const el = ev.target.closest && ev.target.closest('.rs[data-id], .gr-node[data-id]');
    if (el) stGestureShow(Number(el.dataset.id));
});
document.addEventListener('mouseout', ev => {
    const el = ev.target.closest && ev.target.closest('.rs[data-id], .gr-node[data-id]');
    if (el && !(ev.relatedTarget && el.contains(ev.relatedTarget))) stGestureHide();
});

/* ---------------------------------------------------------------- дифф */

function stDiffKey(step) {
    const fallbacks = step.selector && window.recFallbacks ? recFallbacks(step) : [];
    return JSON.stringify({
        kind: step.kind, args: step.args,
        sel: step.selector ? [step.selector.args, ...fallbacks] : null,
        param: step.param || null, note: step.kind === 'click' ? step.note || '' : '',
        texts: step.texts || [], point: step.point || null, any: step.any || null,
        arms: step.arms || null, crop: !!step.crop, optional: !!step.optional,
        retries: step.retries || 0, report: step.report,
    });
}

/* Наибольшая общая подпоследовательность: ops вида {t: 'same'|'del'|'add', a, b}. */
function stLcs(a, b) {
    const n = a.length, m = b.length;
    const dp = Array.from({length: n + 1}, () => new Array(m + 1).fill(0));
    for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
            dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
    }
    const ops = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
        if (a[i] === b[j]) { ops.push({t: 'same', a: i, b: j}); i++; j++; }
        else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({t: 'del', a: i}); i++; }
        else { ops.push({t: 'add', b: j}); j++; }
    }
    while (i < n) ops.push({t: 'del', a: i++});
    while (j < m) ops.push({t: 'add', b: j++});
    return ops;
}

function stFieldChanges(x, y) {
    const out = [];
    const same = (u, v) => JSON.stringify(u) === JSON.stringify(v);
    const ax = x.args || {}, ay = y.args || {};
    for (const key of new Set([...Object.keys(ax), ...Object.keys(ay)])) {
        if (!same(ax[key], ay[key])) out.push(`${key}: «${ax[key] ?? ''}» → «${ay[key] ?? ''}»`);
    }
    const fb = s => (s.selector && window.recFallbacks ? [s.selector.args, ...recFallbacks(s)] : null);
    if (!same(fb(x), fb(y))) out.push('что искать');
    if (!same(x.param || null, y.param || null)) out.push(`параметр: ${x.param || '—'} → ${y.param || '—'}`);
    if ((x.note || '') !== (y.note || '')) out.push('заметка');
    if (!same(x.texts || [], y.texts || []) || !same(x.point || null, y.point || null)
        || !!x.crop !== !!y.crop) out.push('запасные слои цели');
    if (!same(x.any || null, y.any || null)) out.push('признаки экрана');
    if (!same(x.arms || null, y.arms || null)) out.push('ветки развилки');
    if (!!x.optional !== !!y.optional) out.push(y.optional ? 'стал необязательным' : 'стал обязательным');
    if ((x.retries || 0) !== (y.retries || 0)) out.push(`повторов: ${x.retries || 0} → ${y.retries || 0}`);
    return out;
}

/* Список изменений: {kind: 'add'|'del'|'chg', index, label, details}. Соседние
   удаление и добавление шага одного вида склеиваются в «изменён». */
function stDiffSteps(before, after, label) {
    const ops = stLcs(before.map(stDiffKey), after.map(stDiffKey));
    const out = [];
    let dels = [], adds = [];
    const flush = () => {
        const pairs = Math.min(dels.length, adds.length);
        let k = 0;
        for (; k < pairs; k++) {
            const x = before[dels[k]], y = after[adds[k]];
            if (x.kind !== y.kind) break;
            out.push({kind: 'chg', index: adds[k], label: label(y), details: stFieldChanges(x, y)});
        }
        dels.slice(k).forEach(i => out.push({kind: 'del', index: i, label: label(before[i]), details: []}));
        adds.slice(k).forEach(i => out.push({kind: 'add', index: i, label: label(after[i]), details: []}));
        dels = [];
        adds = [];
    };
    for (const op of ops) {
        if (op.t === 'same') flush();
        else if (op.t === 'del') dels.push(op.a);
        else adds.push(op.b);
    }
    flush();
    return out;
}

function stDiffParams(before, after) {
    const out = [];
    for (const name of new Set([...Object.keys(before), ...Object.keys(after)])) {
        if (!(name in before)) out.push(`+ параметр ${name}`);
        else if (!(name in after)) out.push(`− параметр ${name}`);
        else if (JSON.stringify(before[name]) !== JSON.stringify(after[name])) out.push(`~ параметр ${name}`);
    }
    return out;
}

function recDiff() {
    if (!REC.base) return;
    const cur = stSnap();
    const changes = stDiffSteps(REC.base.steps, cur.steps, recLabel);
    const params = stDiffParams(REC.base.params, cur.params);
    const mark = {add: '+', del: '−', chg: '~'};
    const word = {add: 'добавлен', del: 'удалён', chg: 'изменён'};
    const rows = changes.map(c => `<div class="df ${c.kind}">
      <span class="df-m">${mark[c.kind]}</span>
      <span><b>${word[c.kind]}</b> · ${c.kind === 'del' ? 'был' : ''} шаг ${c.index + 1}: ${esc(c.label)}
      ${c.details.length ? `<span class="df-d">${c.details.map(esc).join('; ')}</span>` : ''}</span></div>`)
        .concat(params.map(p => `<div class="df chg"><span class="df-m">${p[0]}</span><span>${esc(p.slice(2))}</span></div>`));
    $('mTitle').textContent = 'Изменения с последнего сохранения';
    $('mBody').innerHTML = rows.length ? `<div class="dflist">${rows.join('')}</div>`
        : '<p style="color:var(--dim)">Ничего не изменилось.</p>';
    $('mActs').innerHTML = '<span class="sp"></span><button class="sm" onclick="closeModal()">Закрыть</button>';
    openModal();
}

/* ----------------------------------------------------- проверка и запуск */

function stCurSig() {
    const meta = REC.edit ? REC.edit.meta : recMeta();
    return JSON.stringify([recPayload(meta).steps, REC.params]);
}

function recRunAfterPending() {
    return REC.runAfterAt && Date.now() - REC.runAfterAt < 300000;
}

function stStepLabel(step, index) {
    return `${index + 1}. ${recLabel(step)}`;
}

function recRunOpen() {
    if (!S.active) {
        toast('сначала откройте телефон', 'bad');
        return;
    }
    if (!REC.steps.length) {
        toast('ещё нет ни одного шага', 'bad');
        return;
    }
    REC.runOpen = true;
    stRunBuild();
}

function recRunClose() {
    REC.runOpen = false;
    const box = $('recRun');
    if (box) {
        box.hidden = true;
        box.innerHTML = '';
    }
}

function stRunBuild() {
    const box = $('recRun');
    if (!box) return;
    box.hidden = false;
    box.setAttribute('role', 'region');
    box.setAttribute('aria-label', 'Проверка на телефоне');
    box.innerHTML = `
    <div class="run-head">
      <span class="run-title">${recIcon('play')} Проверка на телефоне</span>
      <button class="sm ghost" onclick="recRunClose()" aria-label="Закрыть панель">${recIcon('x')}</button>
    </div>
    <div class="run-ctl">
      <button class="primary" id="btnRunGo" onclick="recRunGo()"
              title="Правки сохранятся перед запуском">
        ${recIcon('play')} Запустить</button>
      <button onclick="recValidate()" title="Проверить шаги без запуска">
        ${recIcon('check')} Найти ошибки</button>
      <span class="run-opt"><span class="run-lbl">с шага</span>
        <select id="runFrom" aria-label="Начать с шага" onchange="stRunNote()"></select></span>
      <label class="run-opt inline-check" title="Только этот шаг — с текущего экрана">
        <input type="checkbox" id="runOnly" onchange="stRunNote()"> только этот шаг</label>
      <span class="run-opt"><span class="run-lbl">скорость</span>
        <span class="seg" role="group" aria-label="Скорость">${ST_SPEEDS.map(([v, t]) =>
        `<button type="button" class="${REC.runSpeed === v ? 'on' : ''}" aria-pressed="${REC.runSpeed === v}"
          data-speed="${v}" onclick="stSetSpeed('${v}')" title="${esc(t)}">${v}×</button>`).join('')}</span></span>
    </div>
    <div class="run-note" id="runNote" hidden></div>
    <div id="runIssues"></div>
    <div id="runStatus" role="status" aria-live="polite"></div>`;
    stRunSyncOptions();
    stRunRenderStatus();
    stRenderIssues();
}

function stSetSpeed(value) {
    REC.runSpeed = value;
    document.querySelectorAll('.seg [data-speed]').forEach(btn => {
        const on = btn.dataset.speed === value;
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
}

/* Подсказка появляется только когда она нужна: запуск не с начала. */
function stRunNote() {
    const note = $('runNote'), from = Number(($('runFrom') || {}).value) || 0;
    const only = ($('runOnly') || {}).checked;
    if (!note) return;
    note.hidden = !from && !only;
    note.textContent = only
        ? `Только шаг ${from + 1} — с текущего экрана.`
        : from ? `Шаги 1–${from} пропустятся — начнём с текущего экрана.` : '';
}

function stRunSyncOptions() {
    const select = $('runFrom');
    if (!select) return;
    const keep = select.value;
    select.innerHTML = REC.steps.map((step, i) =>
        `<option value="${i}">${esc(stStepLabel(step, i))}</option>`).join('');
    if (keep && Number(keep) < REC.steps.length) select.value = keep;
    stRunNote();
}

/* Валидация: ошибки и предупреждения по шагам. Ошибка останавливает запуск,
   предупреждение — нет. */
async function recValidate() {
    if (!REC.steps.length) {
        toast('ещё нет ни одного шага', 'bad');
        return null;
    }
    if (!REC.runOpen) recRunOpen();
    const body = recPayload(REC.edit ? REC.edit.meta : recMeta());
    if (S.active) body.serial = S.active;
    let result;
    try {
        result = await post('/api/recorder/validate', body);
    } catch (e) {
        toast(e.message, 'bad');
        return null;
    }
    REC.issues = new Map();
    for (const item of result.errors.concat(result.warnings)) {
        const list = REC.issues.get(item.step) || [];
        list.push(item);
        REC.issues.set(item.step, list);
    }
    stRenderIssues();
    stRunPaint();
    if (result.ok && !result.warnings.length) toast('проверка пройдена: замечаний нет', 'ok');
    return result;
}

function stRenderIssues() {
    const box = $('runIssues');
    if (!box) return;
    const rows = [];
    let errors = 0, warns = 0;
    for (const [step, list] of REC.issues) {
        for (const item of list) {
            if (item.level === 'error') errors++; else warns++;
            const where = step >= 0 ? `<a href="#" onclick="recRunShow(${step});return false">шаг ${step + 1}</a>` : 'сценарий';
            rows.push(`<div class="iss ${item.level}"><svg class="ic"><use href="#i-${item.level === 'error' ? 'alert' : 'info'}"/></svg>
        <span>${where}: ${esc(item.text)}</span></div>`);
        }
    }
    if (!rows.length) {
        box.innerHTML = '';
        return;
    }
    const title = [errors ? `${errors} ${errors === 1 ? 'ошибка' : 'ошибок'}` : '',
        warns ? `${warns} ${warns === 1 ? 'замечание' : 'замечаний'}` : ''].filter(Boolean).join(' · ');
    box.innerHTML = `<details class="iss-box ${errors ? 'has-err' : ''}" ${errors ? 'open' : ''}>
      <summary>${errors ? recIcon('alert') : recIcon('info')} ${title}</summary>${rows.join('')}</details>`;
}

/* Показать шаг: в Списке открывает и прокручивает строку, на Схеме — карточку. */
function recRunShow(index) {
    const step = REC.steps[index];
    if (!step) return;
    REC.open = step.id;
    recSetView('list');
    recRender();
    const row = document.querySelector(`#recSteps .rs[data-id="${step.id}"]`);
    if (row) row.scrollIntoView({block: 'center', behavior: 'smooth'});
}

async function stEnsureSaved() {
    if (!REC.edit) {
        REC.runAfterAt = Date.now();
        recSaveForm();
        toast('сохраните сценарий — проверка начнётся сама', 'ok');
        return false;
    }
    const sig = stCurSig();
    if (sig === REC.savedSig) return true;
    const body = recPayload(REC.edit.meta);
    body.key = REC.edit.key;
    body.overwrite = true;
    try {
        await post('/api/recorder/save', body);
    } catch (e) {
        toast('не удалось сохранить перед запуском: ' + e.message, 'bad');
        return false;
    }
    REC.savedSig = sig;
    REC.base = stSnap();
    localStorage.removeItem(recDraftKey());
    stSyncButtons();
    await loadScenarios(true);
    return true;
}

/* Сохранение из формы с галкой «остаться»: сценарий становится правкой
   собственного файла, конструктор не закрывается. */
async function recStayAfterSave(key, meta, wasEdit) {
    closeModal();
    localStorage.removeItem(recDraftKey());
    REC.edit = {key: key, meta: meta};
    REC.savedSig = stCurSig();
    REC.base = stSnap();
    recBanner(`правим сценарий «${meta.name}»`);
    recSync();
    recRender();
    await loadScenarios(true);
    toast(wasEdit ? 'изменения сохранены' : 'сценарий сохранён, конструктор остался открытым', 'ok');
    if (recRunAfterPending()) {
        REC.runAfterAt = 0;
        recRunOpen();
        recRunGo();
    }
}

function recRunFrom(index) {
    recRunOpen();
    const select = $('runFrom');
    if (select) select.value = String(index);
    const only = $('runOnly');
    if (only) only.checked = false;
    recRunGo();
}

/* Проверить один шаг: телефон уже на нужном экране — выполняем только
   этот шаг и видим, попал ли он, не прогоняя сценарий с начала. */
function recRunStep(index) {
    recRunOpen();
    const select = $('runFrom');
    if (select) select.value = String(index);
    const only = $('runOnly');
    if (only) only.checked = true;
    stRunNote();
    recRunGo();
}

async function recRunGo() {
    /* runStarting — пока идут проверка и сохранение: второй клик в это
       время ставил на телефон вторую проверку следом за первой. */
    if ((REC.run && REC.run.active) || REC.runStarting) {
        toast('проверка ещё идёт', 'bad');
        return;
    }
    if (!S.active) {
        toast('сначала откройте телефон', 'bad');
        return;
    }
    REC.runStarting = true;
    try {
        await recRunStart();
    } finally {
        REC.runStarting = false;
    }
}

async function recRunStart() {
    const check = await recValidate();
    if (!check || !check.ok) {
        if (check) toast('в сценарии есть ошибки — запуск отменён', 'bad');
        return;
    }
    if (!(await stEnsureSaved())) return;
    const from = Number(($('runFrom') || {}).value) || 0;
    const only = !!($('runOnly') || {}).checked;
    const speed = Number(REC.runSpeed) || 1;
    let result;
    try {
        result = await post('/api/run', {scenario: REC.edit.key, serials: [S.active],
            start_step: from, stop_step: only ? from + 1 : null, speed: speed});
    } catch (e) {
        toast(e.message, 'bad');
        return;
    }
    const job = result.jobs[0];
    REC.run = {id: job.id, job: job, active: true, stale: false, from: from, only: only,
        hSig: stHist.lastSig, timer: null};
    stRunRenderStatus();
    stRunPoll();
    if (window.pollJobs) pollJobs();
}

function stRunPoll() {
    const run = REC.run;
    if (!run) return;
    clearTimeout(run.timer);
    run.timer = setTimeout(async () => {
        if (REC.run !== run) return;
        try {
            run.job = await api('/api/jobs/' + run.id);
        } catch (e) {
            stRunPoll();
            return;
        }
        run.active = isActive(run.job.status);
        if (window.syncInteractive) syncInteractive();
        stRunRenderStatus();
        stRunPaint();
        if (run.active) stRunPoll();
        else if (window.pollJobs) pollJobs();
    }, ST_POLL_MS);
}

function stRunReset() {
    if (REC.run) clearTimeout(REC.run.timer);
    REC.run = null;
    stRunPaint();
    recRunClose();
}

const ST_RUN_CLASSES = ['run-ok', 'run-now', 'run-fail', 'run-skip', 'run-retry', 'run-blind', 'has-issue', 'has-warn'];

function stRunPaint() {
    document.querySelectorAll('[data-id]').forEach(el => {
        if (el.classList.contains('rs') || el.classList.contains('gr-node')) {
            el.classList.remove(...ST_RUN_CLASSES);
        }
    });
    const mark = (index, cls) => {
        const step = REC.steps[index];
        if (!step) return;
        document.querySelectorAll(`.rs[data-id="${step.id}"], .gr-node[data-id="${step.id}"]`)
            .forEach(el => el.classList.add(cls));
    };
    for (const [index, list] of REC.issues) {
        if (index < 0) continue;
        mark(index, list.some(item => item.level === 'error') ? 'has-issue' : 'has-warn');
    }
    const run = REC.run;
    if (!run || run.stale || !run.job) return;
    const timeline = run.job.timeline || [];
    timeline.forEach((entry, k) => {
        const current = run.active && k === timeline.length - 1;
        mark(entry.i, current ? 'run-now'
            : {failed: 'run-fail', skipped: 'run-skip', retried: 'run-retry', blind: 'run-blind'}[entry.status] || 'run-ok');
    });
    if (run.active && timeline.length) {
        const last = timeline[timeline.length - 1];
        if (last.i !== run.followed) {
            run.followed = last.i;
            const step = REC.steps[last.i];
            const row = step && document.querySelector(`#recSteps .rs[data-id="${step.id}"]`);
            if (row && REC.view === 'list') row.scrollIntoView({block: 'nearest', behavior: 'smooth'});
        }
    }
}

function stRunRenderStatus() {
    const box = $('runStatus');
    if (!box) return;
    const run = REC.run;
    if (!run) {
        setHTML(box, '');
        return;
    }
    const job = run.job;
    const total = job.step_total || REC.steps.length;
    const done = Math.max(0, job.step_index + (run.active ? 0 : 1));
    const pct = total ? Math.min(100, Math.round(done / total * 100)) : 0;
    const stale = run.stale
        ? '<div class="run-note">Сценарий изменён после запуска — подсветка шагов скрыта.</div>' : '';
    let head = '';
    if (job.status === 'held') {
        /* Кнопки решения — только в полосе над рабочим местом
           (#deviceHeldBar, decisionBar): второй набор здесь же давал два
           разных блока с разными кнопками на одну задачу. */
        head = `<span class="run-step held-note"><svg class="ic"><use href="#i-alert"/></svg>
      ждёт вашего решения — полоса вверху</span>`;
    } else if (run.active) {
        head = `<span class="run-step">${job.step_index >= 0
            ? `шаг ${job.step_index + 1}/${total} · ${esc(job.step_label)}` : 'запуск…'}</span>
      <button class="sm ghost" onclick="cancelJob('${job.id}')">остановить</button>`;
    } else {
        head = stRunResult(job);
    }
    /* Опрос каждые 700 мс: без сравнения «остановить» пересоздавалась под
       курсором, и нажатие, попавшее между mousedown и mouseup, терялось. */
    setHTML(box, `${stale}<div class="runprog ${run.active ? 'on' : job.status}">
      <div class="runprog-bar"><i style="width:${pct}%"></i></div>
      <div class="runprog-row">${head}</div>${stRunChips(run)}</div>`);
}

/* Ленты шагов: видно весь ход одним взглядом, клик — к шагу. */
function stRunChips(run) {
    const timeline = (run.job && run.job.timeline) || [];
    if (timeline.length < 2 || run.stale) return '';
    return '<div class="jchips run-chips">' + timeline.map((t, k) => {
        const now = run.active && k === timeline.length - 1;
        return `<button class="jchip ${now ? 'now' : t.status}" onclick="recRunShow(${t.i})"
          title="${esc(t.label || '')}${t.secs != null ? ' · ' + t.secs + ' с' : ''}">${t.i + 1}</button>`;
    }).join('') + '</div>';
}

function stRunResult(job) {
    const timeline = job.timeline || [];
    const skipped = timeline.filter(t => t.status === 'skipped').length;
    const retried = timeline.filter(t => t.status === 'retried').length;
    const blind = timeline.filter(t => t.status === 'blind').length;
    const extra = [skipped ? `пропущено: ${skipped}` : '', retried ? `с повторами: ${retried}` : '',
        blind ? `вслепую: ${blind}` : '']
        .filter(Boolean).join(' · ');
    if (job.status === 'passed' && blind) {
        return `<div class="run-fail-box"><b class="warnb">Дошёл до конца, но ${blind} ${declOfNum(blind, ['шаг', 'шага', 'шагов'])} — без проверки экрана</b>
      <p>Эти шаги (жёлтый пунктир) засчитаны, даже если экран не тот — уточните, что искать.</p>
      <div class="runprog-acts"><span>${extra}</span> ${stReportLink(job)}</div></div>`;
    }
    /* Шаг за шагом: проверили один шаг — сразу предлагаем следующий, не
       заставляя искать его в списке. Так сюжет проходят с паузой после
       каждого шага, как отладчик. */
    const run = REC.run;
    if (job.status === 'passed' && run && run.only && run.from + 1 < REC.steps.length) {
        const next = run.from + 1;
        return `<span class="run-ok-txt">✓ шаг ${next} прошёл</span>
      <button class="sm primary" onclick="recRunStep(${next})">Следующий шаг: ${esc(recLabel(REC.steps[next]))}</button>`;
    }
    if (job.status === 'passed') {
        return `<span class="run-ok-txt">✓ прошёл за ${job.duration} с${extra ? ' · ' + extra : ''}</span>
      ${stReportLink(job)}`;
    }
    if (job.status === 'cancelled') return '<span>остановлен</span>';
    const info = job.error_info || {title: job.error || 'упал', hint: '', kind: 'other'};
    const last = timeline.length ? timeline[timeline.length - 1] : null;
    const shot = (job.artifacts || []).includes('99_failure.jpg')
        ? `<a target="_blank" href="/api/jobs/${job.id}/artifacts/99_failure.jpg">кадр падения</a>` : '';
    const buttons = last ? `<button class="sm" onclick="recRunShow(${last.i})">показать шаг ${last.i + 1}</button>
      <button class="sm" onclick="recRunFrom(${last.i})">повторить с шага ${last.i + 1}</button>` : '';
    return `<div class="run-fail-box">
      <b>${info.timeout ? 'Не дождались' : 'Сбой'}${last ? ` на шаге ${last.i + 1}` : ''}: ${esc(info.title)}</b>
      ${info.hint ? `<p>${esc(info.hint)}</p>` : ''}
      <div class="runprog-acts">${buttons} ${shot} ${stReportLink(job)}
        <a href="#" onclick="showView('deviations');return false">все проблемы</a></div></div>`;
}

function stReportLink(job) {
    return (job.artifacts || []).includes('report.json')
        ? `<a target="_blank" href="/api/jobs/${job.id}/artifacts/report.json">отчёт</a>` : '';
}

/* ------------------------------------------------- журнал задач (jobs.js) */

function jobProgressHtml(job) {
    if (!job.step_total || (job.status !== 'running' && job.status !== 'held')) return '';
    return ` <span class="jp">шаг ${Math.max(0, job.step_index) + 1}/${job.step_total}</span>`;
}

function jobStepsHtml(job) {
    const timeline = job.timeline || [];
    const info = job.error_info;
    if (!timeline.length && !info) return '';
    const chips = timeline.map(t => `<span class="jchip ${t.status}" title="${esc(t.label || '')}${t.secs != null ? ' · ' + t.secs + ' с' : ''}">${t.i + 1}</span>`).join('');
    const from = job.start_step ? `<span class="jnote">запуск с шага ${job.start_step + 1}</span>` : '';
    const speed = job.speed && job.speed < 1 ? `<span class="jnote">замедление ×${job.speed}</span>` : '';
    const err = info ? `<div class="jerr ${info.timeout ? 'timeout' : ''}">
      <b>${info.timeout ? 'Не дождались' : 'Сбой'}: ${esc(info.title)}</b>${info.hint ? `<p>${esc(info.hint)}</p>` : ''}</div>` : '';
    return `<div class="jsteps"><div class="jchips">${chips}${from}${speed}</div>${err}</div>`;
}

window.jobStepsHtml = jobStepsHtml;
window.jobProgressHtml = jobProgressHtml;
