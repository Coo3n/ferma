'use strict';

/* ИИ-мастер сюжетов: Описание → Шаги и ревью → Проверка на телефоне → Улучшения.
   Контракт API — docs/superpowers/specs/2026-11-06-ai-wizard-design.md (/api/ai/*).
   Редактор не дублируем: сохранение — POST /api/recorder/save, глубокая правка —
   editScenario() из recorder.js. Чистые функции (aiApplyFix, aiAccept, ...) проверяет
   backend/tests/test_ai_wizard_js.py; UI ниже них трогает DOM только внутри функций. */

const AI_STAGES = ['Описание', 'Шаги', 'Проверка', 'Улучшения'];
const AI_MASK = '********';
const AI_ACTIVE = ['queued', 'running', 'held', 'cancelling'];
const AI_STATUS = {
    queued: 'в очереди', running: 'идёт', held: 'ждёт человека', cancelling: 'останавливается',
    passed: 'прошёл', failed: 'упал', cancelled: 'остановлен', canceled: 'остановлен',
};
const AI_BASIS = {analysis: 'по анализу', result: 'по результату запуска', assumption: 'предположение'};
const AI_SEV = {high: 'важно', med: 'средне', low: 'мелочь'};
const AI_OBS = {
    confirmed: 'Подтверждено', probable: 'Вероятно', unverified: 'Не проверено',
};
const AI_KIND = {
    click: 'Нажать', tap: 'Нажать на экран', type: 'Ввести текст', swipe: 'Смахнуть',
    wait: 'Пауза', key: 'Клавиша', back: 'Назад', home: 'Домой', launch: 'Открыть приложение',
    app: 'Открыть приложение', ensure_app: 'Приложение готово', expect: 'Проверить экран',
};

/* ------------------------------------------------------------ чистые функции */

function aiIsActive(status) {
    return AI_ACTIVE.includes(status);
}

function aiStepLabel(step) {
    if (!step || typeof step !== 'object') return 'Шаг';
    const a = step.args && typeof step.args === 'object' ? step.args : {};
    const head = AI_KIND[step.kind] || String(step.kind || 'Шаг');
    let tail = '';
    const sel = step.selector && typeof step.selector.args === 'string'
        ? /(?:text|description)="([^"]+)"/.exec(step.selector.args) : null;
    if (sel) tail = '«' + sel[1] + '»';
    else {
        const v = ['text', 'name', 'label', 'package', 'app', 'key', 'seconds', 'value']
            .map(k => a[k]).find(x => typeof x === 'string' || typeof x === 'number');
        if (v !== undefined) tail = '«' + String(v).slice(0, 60) + '»';
    }
    return tail ? head + ' ' + tail : head;
}

function aiTextArg(step) {
    return step && step.kind === 'type' && step.args && typeof step.args.text === 'string'
        ? 'text' : null;
}

/* Одна правка: replace/insert/delete по индексу (0-based). Не мутирует вход.
   -> {steps} или {error: 'причина'}. insert вставляет ПЕРЕД index (index == длине — в конец). */
function aiApplyFix(steps, fix) {
    if (!fix || typeof fix !== 'object') return {error: 'у замечания нет готовой правки'};
    const n = steps.length, i = fix.index;
    if (!Number.isInteger(i)) return {error: 'правка без номера шага'};
    const out = steps.slice();
    if (fix.op === 'delete') {
        if (i < 0 || i >= n) return {error: 'шага с таким номером уже нет'};
        out.splice(i, 1);
    } else if (fix.op === 'replace') {
        if (i < 0 || i >= n) return {error: 'шага с таким номером уже нет'};
        if (!fix.step || !fix.step.kind) return {error: 'в правке нет нового шага'};
        out[i] = fix.step;
    } else if (fix.op === 'insert') {
        if (i < 0 || i > n) return {error: 'неверное место для вставки'};
        if (!fix.step || !fix.step.kind) return {error: 'в правке нет нового шага'};
        out.splice(i, 0, fix.step);
    } else {
        return {error: 'неизвестный тип правки'};
    }
    return {steps: out};
}

/* Замечание корректно для списка из n шагов (клиентская страховка к серверной проверке). */
function aiFindingValid(f, n) {
    if (!f || typeof f !== 'object' || !f.id || !f.title) return false;
    if (!Array.isArray(f.steps) || !f.steps.length) return false;
    if (!f.steps.every(i => Number.isInteger(i) && i >= 0 && i < n)) return false;
    if (f.fix) {
        if (!['replace', 'insert', 'delete'].includes(f.fix.op) || !Number.isInteger(f.fix.index)) return false;
        const lim = f.fix.op === 'insert' ? n : n - 1;
        if (f.fix.index < 0 || f.fix.index > lim) return false;
    }
    return true;
}

/* После принятой правки остальные замечания сдвигаются; задетые — устаревают. */
function aiShiftFindings(findings, fix, doneId) {
    const shift = fix.op === 'delete' ? -1 : (fix.op === 'insert' ? 1 : 0);
    return findings.map(f => {
        if (f.id === doneId) return f;
        const g = Object.assign({}, f);
        const hit = i => (fix.op === 'insert' ? false : i === fix.index);
        if (g.steps.some(hit) || (g.fix && g.fix.op !== 'insert' && hit(g.fix.index))) {
            if (g.state === undefined || g.state === 'pending') g.state = 'stale';
            return g;
        }
        const mv = i => (i > fix.index || (fix.op === 'insert' && i === fix.index)) ? i + shift : i;
        g.steps = g.steps.map(mv);
        if (g.fix) g.fix = Object.assign({}, g.fix, {index: mv(g.fix.index)});
        return g;
    });
}

/* Ответ принимается, только если он на последний запрос своего канала, шаги не менялись
   с момента запроса и (если версии известны) версия та же. cur = {req:{канал:n}, editSeq}. */
function aiAccept(cur, tok, reply) {
    if (!tok || !reply) return false;
    if ((cur.req[tok.ch] || 0) !== tok.n) return false;
    if (tok.seq !== undefined && tok.seq !== cur.editSeq) return false;
    if (tok.request_id && reply.request_id && reply.request_id !== tok.request_id) return false;
    if (tok.version && reply.version && reply.version !== tok.version) return false;
    return true;
}

/* Что говорит шапка про проверку на телефоне. */
function aiRunBadge(runs, dirty, hasSteps) {
    const last = (runs || [])[0];
    if (!hasSteps) return {kind: 'none', text: ''};
    if (!last) return {kind: 'need', text: 'Не проверен на телефоне'};
    if (dirty || !last.is_current) return {kind: 'need', text: 'Нужна новая проверка'};
    // «Проверен» — только если запуск дошёл до конца: остановленная или упавшая проверка ничего не подтверждает.
    const s = last.status;
    if (!s || s === 'passed') return {kind: 'ok', text: 'Проверен · текущая версия'};
    if (s === 'failed' || s === 'error') return {kind: 'bad', text: 'Проверка не прошла'};
    if (s === 'cancelled' || s === 'canceled') return {kind: 'need', text: 'Проверка остановлена'};
    return {kind: 'need', text: 'Идёт проверка'};
}

function aiGroupObs(list) {
    const g = {confirmed: [], probable: [], unverified: []};
    (list || []).forEach(o => {
        if (!o || !o.text) return;
        (g[o.basis] || g.unverified).push(o);   // неизвестная основа — только «не проверено»
    });
    return g;
}

/* Прогресс локальной загрузки: число — только если сервер дал percent. */
function aiProgress(task) {
    if (!task) return {kind: 'none', text: ''};
    const stage = task.stage || '';
    if (task.state === 'error') return {kind: 'error', text: task.error || 'ошибка загрузки'};
    if (task.state === 'cancelled') return {kind: 'cancelled', text: 'загрузка отменена'};
    if (task.state === 'done') return {kind: 'done', text: 'готово'};
    if (typeof task.percent === 'number') return {kind: 'real', value: task.percent, text: stage + ' ' + Math.round(task.percent) + '%'};
    return {kind: 'indeterminate', text: stage || 'идёт подготовка'};
}

function aiVisionText(v) {
    if (v === 'yes') return 'Картинки понимает';
    if (v === 'no') return 'Картинки не понимает: скриншоты не анализируются';
    return 'Картинки: не удалось выяснить';
}

function aiRiskyText(risky) {
    return (risky || []).map(r => `Шаг ${Number(r.index) + 1}: ${r.reason || 'рискованное действие'}`);
}

function aiKeyFromName() {
    const d = new Date(), p = n => String(n).padStart(2, '0');
    return `ai_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

/* ------------------------------------------------------------------- состояние */

const W = {
    open: false, stage: 0, key: null, name: '', steps: [], recipe: null,
    saved: false, dirty: false, version: null, editSeq: 0, req: {}, rid: 0,
    task: '', serial: '', questions: null, answers: [], needsScreen: false, notes: [],
    findings: null, dropped: 0, reviewMsg: '',
    runs: [], run: null, runMsg: '', risky: null, poll: null,
    analysis: null, analysisMsg: '', busy: {},
    set: null, setTimer: null, local: null, task2: null,
};

function aiBegin(ch, extra) {
    W.req[ch] = (W.req[ch] || 0) + 1;
    return Object.assign({ch, n: W.req[ch], seq: W.editSeq,
        request_id: `${ch}-${W.req[ch]}-${Date.now().toString(36)}`}, extra || {});
}

/* fetch с телом ошибки: api() теряет верхнеуровневый {risky}. */
async function aiCall(method, path, body) {
    let res;
    try {
        res = await fetch('/api/ai' + path, {method, headers: {'Content-Type': 'application/json'},
            body: body === undefined ? undefined : JSON.stringify(body)});
    } catch (e) {
        throw Object.assign(new Error('нет связи с фермой — программа фермы запущена?'), {status: 0});
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const d = data && data.detail;
        const msg = typeof d === 'string' ? d
            : res.status === 404 ? 'на ферме пока нет этой функции ИИ-мастера (обновите программу фермы)'
            : res.status >= 500 ? 'ошибка на ферме или в модели, попробуйте ещё раз' : 'запрос отклонён';
        throw Object.assign(new Error(msg), {status: res.status, body: data});
    }
    return data;
}

const aiGet = p => aiCall('GET', p);
const aiPost = (p, b) => aiCall('POST', p, b === undefined ? {} : b);

function aiTouch(clearFindings) {
    W.editSeq++;
    W.dirty = true;
    W.version = null;
    W.analysis = null;
    if (clearFindings) {
        W.findings = null;
        W.reviewMsg = 'Шаги изменились — запустите ревью заново.';
    }
}

function aiLive(text) {
    const box = $('aiLive');
    if (box) box.textContent = text;
}

/* ------------------------------------------------------------------- вход */

function aiOpen() {
    W.open = true;
    const sec = $('view-scen');
    sec.classList.add('ai-on');
    $('aiWiz').hidden = false;
    if (!W.wired) {
        W.wired = true;
        $('aiWiz').addEventListener('click', aiClick);
        $('aiWiz').addEventListener('change', aiChange);
        $('aiWiz').addEventListener('input', aiInput);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && W.open && W.run && aiIsActive(W.run.status)) aiPollStart();
        });
    }
    aiRender();
}

function aiClose() {
    if (W.dirty && W.steps.length && !confirm('В мастере есть несохранённые шаги. Закрыть без сохранения?')) return;
    aiPollStop();
    W.open = false;
    $('view-scen').classList.remove('ai-on');
    $('aiWiz').hidden = true;
}

/* ------------------------------------------------------------------- рендер */

function aiIc(id) {
    return `<svg class="ic" aria-hidden="true"><use href="#i-${id}"/></svg>`;
}

function aiRender() {
    const box = $('aiWiz');
    if (!box || !W.open) return;
    const had = document.activeElement && box.contains(document.activeElement)
        ? document.activeElement.getAttribute('data-focus') : null;
    const [body, side] = [aiStage0, aiStage1, aiStage2, aiStage3][W.stage]();
    box.innerHTML = aiHeader() + aiStepper() + `<div class="ai-grid${side ? '' : ' ai-solo'}">
        <div class="ai-body">${body}</div>${side ? `<aside class="ai-side" aria-label="Сводка">${side}</aside>` : ''}</div>
        <div id="aiLive" class="ai-sr" role="status" aria-live="polite"></div>`;
    if (had) {
        const el = box.querySelector(`[data-focus="${had}"]`);
        if (el) el.focus();
    }
}

function aiHeader() {
    const b = aiRunBadge(W.runs, W.dirty, W.steps.length > 0);
    const saved = W.saved && !W.dirty;
    // Две плашки вместо четырёх: «сохранено/черновик» и состояние проверки. Этап виден в степпере,
    // версия — в подсказке (она нужна, чтобы понимать, к чему относится проверка).
    const ver = W.version ? ` title="Версия шагов ${esc(W.version)} — неизменяемый снимок, к нему привязаны запуски"` : '';
    return `<header class="ai-head">
      <div class="ai-bar">
        <button class="sm ghost" data-act="close">${aiIc('back')}<span>Сценарии</span></button>
        <button class="sm ghost" data-act="settings" aria-label="Настройки ИИ">${aiIc('gear')}<span>Настройки ИИ</span></button>
      </div>
      <h2>${esc(W.name || 'Новый сюжет')}</h2>
      <div class="ai-meta"${ver}>
        <span class="ai-chip" data-kind="${saved ? 'ok' : 'warn'}">${saved ? 'Сохранён' : 'Черновик'}</span>
        ${b.kind === 'none' ? '' : `<span class="ai-chip" data-kind="${b.kind}">${esc(b.text)}</span>`}
      </div></header>`;
}

function aiStepper() {
    const can = [true, W.steps.length > 0, W.steps.length > 0, W.steps.length > 0];
    return `<ol class="ai-stepper" aria-label="Этапы">${AI_STAGES.map((s, i) => `
      <li><button class="sm" data-act="stage" data-i="${i}" data-focus="st${i}" ${can[i] ? '' : 'disabled title="Сначала нужны шаги"'}
        ${can[i] ? `title="${['Описание задачи', 'Шаги и замечания', 'Проверка на телефоне', 'Улучшения и повторная проверка'][i]}"` : ''}
        ${i === W.stage ? 'aria-current="step"' : ''}><b>${i + 1}</b><span>${esc(s)}</span></button></li>`).join('')}</ol>`;
}

function aiErr(msg) {
    return msg ? `<p class="ai-msg" data-kind="bad" role="alert">${esc(msg)}</p>` : '';
}

function aiStage0() {
    const busy = W.busy.draft;
    const phones = (typeof S !== 'undefined' ? S.devices : []).filter(d => d.online);
    const scen = (typeof S !== 'undefined' ? S.scenarios : []) || [];
    const qs = W.questions ? `<div class="ai-card" aria-label="Вопросы модели">
        <h3>Уточните</h3>
        ${W.questions.map((q, i) => `<label>${esc(q)}<input data-in="ans${i}" data-i="${i}" value="${esc(W.answers[i] || '')}"></label>`).join('')}
        <div class="ai-row"><button class="primary" data-act="answer" ${busy ? 'disabled' : ''}>Ответить</button></div></div>` : '';
    const main = `<section class="ai-card">
      <label>Задача
        <textarea data-in="task" rows="4" placeholder="Открыть настройки и вернуться домой" ${busy ? 'disabled' : ''}>${esc(W.task)}</textarea></label>
      <label>Телефон
        <select data-in="serial" title="С телефоном модель видит экран. Без него шаги строятся только по тексту.">
          <option value="">Без телефона</option>
          ${phones.map(d => `<option value="${esc(d.serial)}" ${d.serial === W.serial ? 'selected' : ''}>${esc(d.name)}</option>`).join('')}
        </select></label>
      ${aiErr(W.draftMsg)}
      <div class="ai-row"><button class="primary" data-act="draft" data-focus="draft" ${busy ? 'disabled' : ''}>${busy ? 'Составляю…' : 'Составить шаги'}</button></div>
    </section>${qs}`;
    const side = scen.length ? `<section class="ai-card">
      <label>Готовый сюжет
        <span class="ai-row">
          <select data-in="pick">
            <option value="">Выберите…</option>
            ${scen.map(s => `<option value="${esc(s.key)}" ${s.key === W.pick ? 'selected' : ''}>${esc(s.name || s.title || s.key)}</option>`).join('')}
          </select>
          <button data-act="load" ${W.pick ? '' : 'disabled'}>Открыть</button>
        </span></label>
      ${aiErr(W.loadMsg)}
    </section>` : '';
    return [main, side];
}

function aiStage1() {
    const steps = W.steps;
    const list = steps.length ? `<ol class="ai-steps">${steps.map((s, i) => {
        const tx = aiTextArg(s);
        return `<li class="ai-st"><span class="ai-n">${i + 1}</span>
          <span class="ai-lab">${tx ? `<input data-in="st${i}" data-act-input="text" data-i="${i}" value="${esc(s.args.text)}" aria-label="Текст шага ${i + 1}">` : esc(aiStepLabel(s))}</span>
          <span class="ai-acts">
            <button class="sm ghost" data-act="up" data-i="${i}" aria-label="Выше" ${i ? '' : 'disabled'}>↑</button>
            <button class="sm ghost" data-act="down" data-i="${i}" aria-label="Ниже" ${i < steps.length - 1 ? '' : 'disabled'}>↓</button>
            <button class="sm ghost danger" data-act="del" data-i="${i}" aria-label="Удалить шаг ${i + 1}">✕</button>
          </span></li>`;
    }).join('')}</ol>` : '<p class="ai-note">Шагов нет.</p>';
    const notes = (W.notes || []).length ? `<ul class="ai-notes">${W.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>` : '';
    const screen = W.needsScreen ? '<p class="ai-msg" data-kind="warn">Без экрана телефона: это черновик.</p>' : '';
    const main = `<section class="ai-card">
      <label>Название<input data-in="name" value="${esc(W.name)}" placeholder="Обход настроек"></label>
      ${screen}${notes}${list}
      ${aiErr(W.saveMsg)}
      <div class="ai-row">
        <button class="primary" data-act="save" ${W.busy.save ? 'disabled' : ''} data-focus="save">Сохранить</button>
        <button data-act="review" ${W.busy.review || !steps.length ? 'disabled' : ''}>${W.busy.review ? 'Проверяю…' : 'Проверить'}</button>
        <span class="ai-spacer"></span>
        <button class="ghost" data-act="savecopy" title="Сохранить как новый сюжет" ${W.busy.save || !steps.length ? 'disabled' : ''}>Копией</button>
        <button class="ghost" data-act="builder" ${W.saved && W.key ? '' : 'disabled title="Сначала сохраните"'}>В конструктор</button>
      </div>
    </section>`;
    const none = (W.findings === null || W.findings === undefined) && !W.reviewMsg;
    return [main, `<section class="ai-card"><h3>Замечания</h3>${none ? '<p class="ai-note">Появятся после проверки.</p>' : aiFindingsBlock(W.findings, W.reviewMsg, false)}</section>`];
}

function aiFindingsBlock(list, msg, stale) {
    if (list === null || list === undefined) return `<p class="ai-note">${esc(msg || 'Ещё не проверяли.')}</p>`;
    if (!list.length) return `<p class="ai-note">${esc(msg || 'Замечаний нет.')}${W.dropped ? ' Отброшено: ' + W.dropped + '.' : ''}</p>`;
    const open = list.filter(f => (f.state || 'pending') === 'pending').length;
    return `${msg ? `<p class="ai-note">${esc(msg)}</p>` : ''}
      <p class="ai-note" aria-live="polite">Осталось: ${open} из ${list.length}${W.dropped ? ' · отброшено: ' + W.dropped : ''}</p>
      <ul class="ai-finds">${list.map(f => aiFindingHtml(f, stale)).join('')}</ul>`;
}

function aiFindingHtml(f, stale) {
    const st = f.state || 'pending';
    const cur = i => W.steps[i] ? aiStepLabel(W.steps[i]) : '—';
    let diff = '';
    if (f.fix) {
        const was = f.fix.op === 'insert' ? '(новый шаг)' : cur(f.fix.index);
        const now = f.fix.op === 'delete' ? '(удалить)' : aiStepLabel(f.fix.step);
        diff = `<div class="ai-diff"><div class="was"><small>было</small>${f.fix.op === 'insert' ? esc(was) : esc(`${f.fix.index + 1}. ${was}`)}</div>
          <div class="now"><small>станет</small>${esc(now)}</div></div>`;
    }
    const states = {accepted: 'принято', rejected: 'отклонено', stale: 'устарело', failed: 'не применилось'};
    const acts = st === 'pending' ? `<div class="ai-row">
        ${f.fix ? `<button class="sm primary" data-act="accept" data-id="${esc(f.id)}" ${stale ? 'disabled title="Относится к другой версии шагов"' : ''}>Принять</button>` : ''}
        <button class="sm" data-act="reject" data-id="${esc(f.id)}">${f.fix ? 'Отклонить' : 'Понятно'}</button></div>`
        : `<p class="ai-note">${esc(f.note || states[st] || st)}</p>`;
    return `<li class="ai-find" data-st="${esc(st)}" data-sev="${esc(f.severity)}">
      <div class="ai-fh"><span class="ai-chip" data-kind="${f.severity === 'high' ? 'bad' : f.severity === 'med' ? 'warn' : ''}">${esc(AI_SEV[f.severity] || f.severity)}</span>
        <b>${esc(f.title)}</b></div>
      <p>${esc(f.why || '')}</p>
      <p class="ai-note">Шаги: ${f.steps.map(i => i + 1).join(', ')} · ${esc(AI_BASIS[f.basis] || 'предположение')}</p>
      ${diff}${acts}</li>`;
}

function aiStage2() {
    const devs = (typeof S !== 'undefined' ? S.devices : []).filter(d => d.enabled !== false && !(S.hidden && S.hidden.has(d.serial)));
    const busy = W.busy.run;
    const needSave = !W.saved || W.dirty;
    const risky = W.risky ? `<div class="ai-card ai-risky" role="alertdialog" aria-labelledby="aiRiskT">
        <h3 id="aiRiskT">Есть рискованные шаги</h3>
        <ul>${aiRiskyText(W.risky).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
        <p class="ai-note">Могут оплатить, удалить, отправить или ввести пароль. Запустить?</p>
        <div class="ai-row"><button data-act="risk-no" data-focus="riskno">Отмена</button>
        <button class="danger" data-act="risk-yes">Да, запустить</button></div></div>` : '';
    const main = `<section class="ai-card">
      <h3>Телефон</h3>
      ${devs.length ? `<div class="ai-phones" role="radiogroup" aria-label="Телефон для проверки">${devs.map(d => `
        <label class="ai-ph" data-off="${d.online ? 0 : 1}"><input type="radio" name="aiPhone" data-in-phone value="${esc(d.serial)}"
          ${W.serial === d.serial ? 'checked' : ''} ${d.online ? '' : 'disabled'}>
          <span><b>${esc(d.name)}</b><small>${d.online ? (d.busy_job ? 'занят другим запуском' : 'в сети') : 'не в сети'}</small></span></label>`).join('')}</div>`
        : '<p class="ai-msg" data-kind="warn">Нет телефонов. Подключите по USB.</p>'}
      ${aiErr(W.runMsg)}
      <div class="ai-row"><button class="primary" data-act="run" data-focus="run" title="Рискованные шаги спросят подтверждение" ${busy || !W.serial ? 'disabled' : ''}>
        ${busy ? 'Запускаю…' : needSave ? 'Сохранить и запустить' : 'Запустить'}</button></div>
    </section>${risky}${aiRunPanel()}`;
    return [main, aiSideSteps() + aiHistory()];
}

/* Правая колонка: шаги одним списком, во время проверки — с состоянием каждого. */
function aiSideSteps() {
    if (!W.steps.length) return '';
    const tl = W.run && Array.isArray(W.run.timeline) ? W.run.timeline : [];
    const st = i => { const x = tl.find((y, k) => (y.i != null ? y.i : (y.index != null ? y.index : k)) === i); return x ? (x.status || x.state || '') : ''; };
    return `<section class="ai-card"><h3>Шаги <span class="ai-dim">${W.steps.length}</span></h3>
      <ol class="ai-mini">${W.steps.map((s, i) => `<li data-st="${esc(st(i))}"><span class="ai-n">${i + 1}</span><span title="${esc(aiStepLabel(s))}">${esc(aiStepLabel(s))}</span></li>`).join('')}</ol></section>`;
}

function aiRunPanel() {
    const r = W.run;
    if (!r) return '';
    const active = aiIsActive(r.status);
    const tl = Array.isArray(r.timeline) ? r.timeline : [];
    const total = r.step_total || W.steps.length;
    const off = r.phone_state === 'offline';
    return `<div class="ai-card" aria-label="Ход проверки">
      <h3>Ход <span class="ai-chip" data-kind="${r.status === 'passed' ? 'ok' : r.status === 'failed' ? 'bad' : ''}">${esc(AI_STATUS[r.status] || r.status)}</span></h3>
      ${off ? '<p class="ai-msg" data-kind="bad" role="alert">Телефон не в сети. Проверьте кабель и запустите снова.</p>' : ''}
      ${r.error ? `<p class="ai-msg" data-kind="bad">${esc(r.error)}</p>` : ''}
      ${r.status === 'held' ? '<p class="ai-msg" data-kind="warn">Ферма ждёт решения. Остановите или решите в «Запусках».</p>' : ''}
      <p class="ai-note">Шаг ${r.step_index == null ? '—' : Number(r.step_index) + 1} из ${total || '—'}${r.is_current === false ? ' · старая версия' : ''}</p>
      ${tl.length ? `<ol class="ai-tl">${tl.map((x, k) => {
        const idx = x.i != null ? x.i : (x.index != null ? x.index : k);
        const stt = x.status || x.state || '';
        const rawShot = typeof (x.shot || x.screenshot) === 'string' ? (x.shot || x.screenshot) : '';
        // backend отдаёт только имя файла; сама картинка — артефакт задачи
        const shot = !rawShot ? '' : (/^(\/|https?:)/.test(rawShot) ? rawShot
          : (r.job_id ? `/api/jobs/${encodeURIComponent(r.job_id)}/artifacts/${encodeURIComponent(rawShot)}` : ''));
        return `<li data-st="${esc(stt)}"><span class="ai-n">${Number(idx) + 1}</span>
          <span class="ai-lab">${esc(x.label || (W.steps[idx] ? aiStepLabel(W.steps[idx]) : 'Шаг'))}
            <small>${esc(AI_STATUS[stt] || stt)}${x.error ? ': ' + esc(x.error) : ''}</small></span>
          ${shot ? `<a href="${esc(shot)}" target="_blank" rel="noopener"><img loading="lazy" src="${esc(shot)}" alt="Экран после шага ${Number(idx) + 1}"></a>` : ''}</li>`;
      }).join('')}</ol>` : '<p class="ai-note">Пока без подробностей.</p>'}
      <div class="ai-row">
        ${active ? '<button class="danger" data-act="stop">Остановить</button>' : ''}
        ${!active ? '<button data-act="stage" data-i="3">Улучшения</button>' : ''}
      </div></div>`;
}

/* started_at приходит секундами (число) или строкой ISO — показываем «12 нояб., 14:05». */
function aiWhen(v) {
    if (v == null || v === '') return '';
    const d = typeof v === 'number' ? new Date(v * 1000) : new Date(v);
    if (isNaN(d)) return '';
    return d.toLocaleString('ru-RU', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
}

function aiHistory() {
    if (!W.runs.length) return '';
    return `<div class="ai-card"><h3>История</h3><ul class="ai-hist">${W.runs.map(r => `
      <li><button class="sm ghost" data-act="openrun" data-id="${esc(r.run_id)}">
        <span>${esc(aiWhen(r.started_at) || r.run_id)}</span>
        <span class="ai-dim" title="Версия шагов">${esc(r.version)}</span>
        <span class="ai-chip" data-kind="${r.status === 'passed' ? 'ok' : r.status === 'failed' ? 'bad' : ''}">${esc(AI_STATUS[r.status] || r.status)}</span>
        <span class="ai-chip" data-kind="${r.is_current && !W.dirty ? 'ok' : 'warn'}">${r.is_current && !W.dirty ? 'текущая' : 'старая'}</span>
      </button></li>`).join('')}</ul></div>`;
}

function aiStage3() {
    const last = W.run && !aiIsActive(W.run.status) ? W.run : (W.runs.find(r => !aiIsActive(r.status)) || null);
    const a = W.analysis;
    let body;
    if (!last) body = '<p class="ai-note">Сначала проверьте на телефоне.</p>';
    else {
        const stale = a && (a.stale);
        body = `<p class="ai-note">Последняя: ${esc([AI_STATUS[last.status] || last.status, aiWhen(last.started_at)].filter(Boolean).join(", "))}</p>
          <div class="ai-row"><button class="primary" data-act="analyze" data-id="${esc(last.run_id)}" data-focus="analyze" ${W.busy.analyze ? 'disabled' : ''}>${W.busy.analyze ? 'Анализирую…' : 'Разобрать запуск'}</button></div>`;
        if (a) {
            const g = aiGroupObs(a.observations);
            body += `${a.vision_used ? '' : `<p class="ai-msg" data-kind="warn">${esc(a.note || 'Модель не видит картинки: выводы только по тексту.')}</p>`}
              ${stale ? '<p class="ai-msg" data-kind="warn">Анализ для другой версии шагов. Проверьте заново.</p>' : ''}
              ${['confirmed', 'probable', 'unverified'].map(k => `<section class="ai-obs" data-k="${k}"><h4>${AI_OBS[k]}</h4>
                ${g[k].length ? `<ul>${g[k].map(o => `<li>${esc(o.text)}</li>`).join('')}</ul>` : '<p class="ai-note">Ничего.</p>'}</section>`).join('')}
              <h4>Правки</h4>${aiFindingsBlock(a.suggestions, '', stale)}`;
        }
    }
    const main = `<section class="ai-card"><h3>Улучшения</h3>${aiErr(W.analysisMsg)}${body}
      <div class="ai-row"><button data-act="stage" data-i="2">Проверить снова</button>
      <span class="ai-spacer"></span>
      <button class="ghost" data-act="save" ${W.dirty ? '' : 'disabled'}>Сохранить</button>
      <button class="ghost" data-act="savecopy" title="Сохранить как новый сюжет">Копией</button></div></section>`;
    return [main, aiSideSteps() + aiHistory()];
}

/* ------------------------------------------------------------------- события */

function aiInput(e) {
    const el = e.target, k = el.dataset.in;
    if (k === 'task') W.task = el.value;
    else if (k === 'name') W.name = el.value;
    else if (k && k.startsWith('ans')) W.answers[Number(el.dataset.i)] = el.value;
    else if (el.dataset.actInput === 'text') {
        const s = W.steps[Number(el.dataset.i)];
        if (s) {
            s.args = Object.assign({}, s.args, {text: el.value});
            aiTouch(true);
            aiRefreshHead();
        }
    }
}

function aiRefreshHead() {
    const h = document.querySelector('#aiWiz .ai-head');
    if (h) h.outerHTML = aiHeader();
}

function aiChange(e) {
    const el = e.target;
    if (el.dataset.in === 'serial') W.serial = el.value;
    else if (el.dataset.in === 'pick') {
        W.pick = el.value;
        aiRender();
    } else if (el.hasAttribute('data-in-phone')) {
        W.serial = el.value;
        aiRender();
    }
}

function aiClick(e) {
    const b = e.target.closest('[data-act]');
    if (!b || b.disabled) return;
    const i = Number(b.dataset.i), id = b.dataset.id;
    switch (b.dataset.act) {
        case 'close': return aiClose();
        case 'settings': return aiSettings();
        case 'stage':
            W.stage = i;
            if (i === 2 && !W.serial) aiDefaultPhone();
            if (i >= 2 && W.run && aiIsActive(W.run.status) && !W.poll) aiPollStart();
            return aiRender();
        case 'draft': return aiDraft(false);
        case 'answer': return aiDraft(true);
        case 'load': return aiLoad(W.pick);
        case 'up': case 'down': return aiMove(i, b.dataset.act === 'up' ? -1 : 1);
        case 'del':
            W.steps.splice(i, 1);
            aiTouch(true);
            aiRender();
            return aiLive('Шаг удалён');
        case 'save': return aiSave(false);
        case 'savecopy': return aiSave(true);
        case 'builder': return typeof editScenario === 'function' && W.key ? editScenario(W.key) : undefined;
        case 'review': return aiReview();
        case 'accept': return aiAcceptFinding(id);
        case 'reject': return aiMarkFinding(id, 'rejected');
        case 'run': return aiRun(false);
        case 'risk-yes': W.risky = null; return aiRun(true);
        case 'risk-no': W.risky = null; return aiRender();
        case 'stop': return aiStop();
        case 'openrun': return aiOpenRun(id);
        case 'analyze': return aiAnalyze(id);
    }
}

function aiDefaultPhone() {
    const d = (typeof S !== 'undefined' ? S.devices : []).filter(x => x.online);
    if (d.length === 1) W.serial = d[0].serial;
}

function aiMove(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= W.steps.length) return;
    [W.steps[i], W.steps[j]] = [W.steps[j], W.steps[i]];
    aiTouch(true);
    aiRender();
    aiLive(`Шаг перемещён на позицию ${j + 1}`);
    const el = document.querySelector(`#aiWiz [data-act="${dir < 0 ? 'up' : 'down'}"][data-i="${j}"]`);
    if (el && !el.disabled) el.focus();
}

/* ------------------------------------------------------------------- шаг 0: черновик */

async function aiDraft(withAnswers) {
    const task = (W.task || '').trim();
    if (!task) {
        W.draftMsg = 'Опишите, что должен делать сюжет.';
        return aiRender();
    }
    const tok = aiBegin('draft');
    W.busy.draft = true;
    W.draftMsg = '';
    aiRender();
    aiLive('Составляю шаги');
    const body = {task};
    if (W.serial) body.serial = W.serial;
    if (withAnswers) body.clarify_answers = (W.questions || []).map((_, i) => W.answers[i] || '');
    try {
        const r = await aiPost('/draft', body);
        if (!aiAccept(W, tok, r)) return;
        if (r.status === 'questions') {
            W.questions = r.questions || [];
            W.answers = [];
            aiLive('Модель задала уточняющие вопросы');
        } else if (r.status === 'steps' && Array.isArray(r.steps) && r.steps.length) {
            W.questions = null;
            W.steps = r.steps;
            W.notes = r.notes || [];
            W.needsScreen = !!r.needs_screen;
            W.key = null; W.recipe = null; W.saved = false; W.version = r.version || null;
            W.dirty = true; W.findings = null; W.reviewMsg = ''; W.analysis = null; W.runs = []; W.run = null;
            W.editSeq++;
            if (!W.name) {
              // название — по первому предложению и по границе слова, а не «…зайди в разде»
              const first = task.split(/[.!?\n,;]/)[0].trim();
              const cut = first.length > 44 ? first.slice(0, 44).replace(/\s+\S*$/, '') + '…' : first;
              W.name = cut || task.slice(0, 40);
            }
            W.stage = 1;
            aiLive('Шаги составлены');
        } else {
            W.draftMsg = 'Модель вернула пустой ответ. Уточните описание и попробуйте ещё раз.';
        }
    } catch (e) {
        if (aiAccept(W, tok, {})) W.draftMsg = e.message;
    }
    if (W.req.draft === tok.n) W.busy.draft = false;
    aiRender();
}

async function aiLoad(key) {
    if (!key) return;
    W.loadMsg = '';
    try {
        const r = await api('/api/recorder/recipe/' + encodeURIComponent(key));
        W.recipe = r;
        W.key = key;
        W.name = (r.meta && r.meta.name) || key;
        W.steps = (r.steps || []).map(s => JSON.parse(JSON.stringify(s)));
        W.saved = true; W.dirty = false; W.editSeq++; W.findings = null; W.analysis = null;
        W.notes = []; W.needsScreen = false; W.stage = 1;
        await aiSnapshot();
        await aiRefreshRuns();
    } catch (e) {
        W.loadMsg = e.message;
    }
    aiRender();
}

/* ------------------------------------------------------------------- сохранение */

async function aiSnapshot() {
    const r = await aiPost('/versions', {scenario_key: W.key, steps: W.steps, label: W.name});
    W.version = r.version;
    return r;
}

async function aiSave(copy) {
    if (!W.steps.length) return;
    const name = (W.name || '').trim() || 'Сюжет из ИИ-мастера';
    const newKey = copy || !W.key;
    const key = newKey ? aiKeyFromName() : W.key;
    const rec = W.recipe || {};
    const body = Object.assign({}, rec, {key, steps: W.steps, params: rec.params || {},
        meta: Object.assign({}, rec.meta || {}, {name: copy ? name + ' (копия)' : name}),
        overwrite: !newKey});
    W.busy.save = true;
    W.saveMsg = '';
    aiRender();
    try {
        await api('/api/recorder/save', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
        W.key = key;
        W.name = body.meta.name;
        W.recipe = Object.assign({}, rec, {meta: body.meta, params: body.params});
        W.saved = true;
        W.dirty = false;
        await aiSnapshot();
        await aiRefreshRuns();
        toast(copy ? 'сохранено копией' : 'сюжет сохранён', 'ok');
        if (window.loadScenarios) loadScenarios(true);
    } catch (e) {
        W.saveMsg = 'Не удалось сохранить: ' + e.message;
        if (W.key === key) { W.dirty = true; W.version = null; }
    }
    W.busy.save = false;
    aiRender();
    return W.saved && !W.dirty;
}

/* ------------------------------------------------------------------- ревью и замечания */

async function aiReview() {
    const tok = aiBegin('review', {version: W.version});
    W.busy.review = true;
    W.reviewMsg = '';
    aiRender();
    aiLive('Проверяю шаги');
    const body = {steps: W.steps, request_id: tok.request_id};
    if (W.saved && W.key) body.scenario = W.key;
    try {
        const r = await aiPost('/review', body);
        if (aiAccept(W, tok, r)) {
            const all = Array.isArray(r.findings) ? r.findings : [];
            const ok = all.filter(f => aiFindingValid(f, W.steps.length));
            W.findings = ok.map(f => Object.assign({}, f, {state: 'pending'}));
            W.dropped = (r.dropped || 0) + (all.length - ok.length);
            W.reviewMsg = ok.length ? '' : 'Замечаний нет — шаги выглядят целыми.';
            aiLive(`Ревью готово: замечаний ${ok.length}`);
        }
    } catch (e) {
        if (aiAccept(W, tok, {})) W.reviewMsg = 'Ревью не удалось: ' + e.message;
    }
    if (W.req.review === tok.n) W.busy.review = false;
    aiRender();
}

function aiFindingList() {
    return W.stage === 3 && W.analysis ? W.analysis.suggestions : W.findings;
}

function aiMarkFinding(id, state, note) {
    const f = (aiFindingList() || []).find(x => x.id === id);
    if (f) { f.state = state; if (note) f.note = note; }
    aiRender();
}

function aiAcceptFinding(id) {
    const list = aiFindingList() || [];
    const f = list.find(x => x.id === id);
    if (!f || (f.state || 'pending') !== 'pending') return;
    if (W.stage === 3 && W.analysis && W.analysis.stale) return;
    const r = aiApplyFix(W.steps, f.fix);
    if (r.error) return aiMarkFinding(id, 'failed', r.error);
    const fix = f.fix;
    W.steps = r.steps;
    const shifted = aiShiftFindings(list, fix, id);
    shifted.forEach((g, k) => { list[k] = g; });
    f.state = 'accepted';
    W.editSeq++;
    W.dirty = true;
    W.version = null;
    aiRender();
    aiLive('Правка применена. Нужна новая проверка на телефоне.');
}

/* ------------------------------------------------------------------- запуск на телефоне */

async function aiRefreshRuns() {
    if (!W.key) { W.runs = []; return; }
    try {
        const r = await aiGet('/runs?scenario_key=' + encodeURIComponent(W.key));
        W.runs = (Array.isArray(r) ? r : []).slice().sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
    } catch (e) {
        W.runs = [];
    }
}

async function aiRun(confirmRisky) {
    if (!W.serial) return;
    W.runMsg = '';
    const dev = (typeof S !== 'undefined' ? S.devices : []).find(d => d.serial === W.serial);
    if (dev && !dev.online) {
        W.runMsg = 'Телефон не в сети: выберите другой или включите этот.';
        return aiRender();
    }
    W.busy.run = true;
    aiRender();
    try {
        if (!W.saved || W.dirty) {
            const ok = await aiSave(false);
            if (!ok) throw new Error(W.saveMsg || 'сначала нужно сохранить сюжет');
            W.busy.run = true;
        }
        const body = {scenario_key: W.key, version: W.version, serial: W.serial};
        if (confirmRisky) body.confirm_risky = true;
        const r = await aiPost('/run', body);
        W.run = {run_id: r.run_id, job_id: r.job_id, status: 'queued', version: W.version, timeline: []};
        aiLive('Проверка запущена');
        aiPollStart();
        aiRefreshRuns().then(() => W.open && aiRender());
    } catch (e) {
        const risky = e.body && (e.body.risky || (e.body.detail && e.body.detail.risky));
        if (e.status === 409 && risky) {
            W.risky = risky;
        } else if (e.status === 409) {
            W.runMsg = (e.message || 'Сюжет изменился.') + ' Сохраните текущие шаги и запустите снова.';
        } else {
            W.runMsg = e.message;
        }
    }
    W.busy.run = false;
    aiRender();
    if (W.risky) {
        const f = document.querySelector('#aiWiz [data-focus="riskno"]');
        if (f) f.focus();
    }
}

function aiPollStop() {
    if (W.poll) clearTimeout(W.poll);
    W.poll = null;
}

function aiPollStart() {
    aiPollStop();
    W.poll = setTimeout(aiPollTick, 1000);
}

async function aiPollTick() {
    W.poll = null;
    const run = W.run;
    if (!W.open || !run || document.hidden || W.stage < 2) return;   // вернёмся по visibilitychange / переходу на этап
    const tok = aiBegin('poll');
    try {
        const r = await aiGet('/runs/' + encodeURIComponent(run.run_id));
        if (W.req.poll !== tok.n || !W.run || W.run.run_id !== run.run_id) return;
        W.run = r;
        const prev = W.runLast;
        W.runLast = r.status;
        if (prev !== r.status) aiLive('Статус проверки: ' + (AI_STATUS[r.status] || r.status));
        if (W.stage === 2) aiRender();
        if (aiIsActive(r.status)) return aiPollStart();
        await aiRefreshRuns();
        if (W.open) aiRender();
    } catch (e) {
        if (W.req.poll !== tok.n) return;
        W.runMsg = 'Не удаётся получить ход проверки: ' + e.message;
        if (W.stage === 2) aiRender();
        if (e.status !== 404) W.poll = setTimeout(aiPollTick, 3000);
    }
}

async function aiStop() {
    if (!W.run) return;
    try {
        await aiPost('/runs/' + encodeURIComponent(W.run.run_id) + '/stop');
        aiLive('Останавливаю проверку');
        aiPollStart();   // статус покажем только реальный, из job
    } catch (e) {
        W.runMsg = 'Не удалось остановить: ' + e.message;
        aiRender();
    }
}

async function aiOpenRun(id) {
    try {
        W.run = await aiGet('/runs/' + encodeURIComponent(id));
        W.runMsg = '';
        if (aiIsActive(W.run.status)) aiPollStart();
    } catch (e) {
        W.runMsg = e.message;
    }
    aiRender();
}

/* ------------------------------------------------------------------- анализ */

async function aiAnalyze(runId) {
    const runInfo = (W.run && W.run.run_id === runId ? W.run : W.runs.find(r => r.run_id === runId)) || {};
    const tok = aiBegin('analyze', {version: runInfo.version});
    W.busy.analyze = true;
    W.analysisMsg = '';
    aiRender();
    aiLive('Анализирую запуск');
    try {
        const r = await aiPost('/analyze', {run_id: runId, request_id: tok.request_id});
        if (aiAccept(W, tok, r)) {
            const n = W.steps.length;
            const sug = (r.suggestions || []).filter(f => aiFindingValid(f, n));
            W.analysis = {observations: r.observations || [], vision_used: !!r.vision_used, note: r.note || '',
                suggestions: sug.map(f => Object.assign({}, f, {state: 'pending'})),
                stale: W.dirty || (runInfo.version && W.version && runInfo.version !== W.version)};
            W.dropped = (r.suggestions || []).length - sug.length;
            aiLive('Анализ готов');
        }
    } catch (e) {
        W.analysisMsg = e.message;
    }
    if (W.req.analyze === tok.n) W.busy.analyze = false;
    aiRender();
}

/* ------------------------------------------------------------------- настройки ИИ */

async function aiSettings() {
    $('mTitle').textContent = 'Настройки ИИ';
    $('mBody').innerHTML = '<div class="ai-set" id="aiSet"><p class="ai-note">Загружаю…</p></div>';
    $('mActs').innerHTML = '<button onclick="aiSettingsClose()">Закрыть</button>';
    if (typeof modalSheet === 'function') modalSheet('wide');
    openModal();
    W.setEdits = {};
    await Promise.all([aiSetLoad(), aiLocalLoad()]);
}

function aiSettingsClose() {
    clearTimeout(W.setTimer);
    W.setTimer = null;
    closeModal();
}

const aiSetAlive = () => !!$('aiSet');

async function aiSetLoad() {
    try {
        W.set = await api('/api/vlm');
        W.setErr = '';
    } catch (e) {
        W.set = null;
        W.setErr = e.message;
    }
    aiSetPaint();
}

function aiSetPaint() {
    if (!aiSetAlive()) return;
    const box = $('aiSet');
    const d = W.set;
    const m = W.models;
    box.innerHTML = `<div class="ai-two">
      <section class="ai-card" aria-label="Свой сервер">${aiServerCard(d, m)}</section>
      <section class="ai-card" aria-label="Локальная модель">${aiLocalCard()}</section></div>`;
    box.querySelectorAll('[data-sact]').forEach(b => b.addEventListener('click', aiSetClick));
}

function aiServerCard(d, m) {
    if (!d) return `<h3>Свой сервер</h3>${aiErr(W.setErr || 'Настройки не загрузились')}<button data-sact="reload">Повторить</button>`;
    const pr = W.probe;
    const v = pr ? pr.vision : d.vision;
    return `<h3>Свой сервер</h3>
      <label>Адрес<input id="aiUrl" value="${esc(d.url || '')}" placeholder="http://127.0.0.1:1234/v1" autocomplete="off" title="Любой сервер с OpenAI-совместимым адресом: LM Studio, vLLM, Ollama"></label>
      <label>Ключ<input id="aiKey" type="password" value="${esc(d.key || '')}" autocomplete="off" placeholder="для локальных не нужен"></label>
      <label>Модель<input id="aiModel" list="aiModels" value="${esc(d.model || '')}" autocomplete="off">
        <datalist id="aiModels">${(m && m.models || []).map(x => `<option value="${esc(x.id)}">`).join('')}</datalist></label>
      ${m ? (m.error ? aiErr('Список моделей: ' + m.error) : `<p class="ai-note">Найдено моделей: ${(m.models || []).length}</p>`) : ''}
      ${W.probeBusy ? '<p class="ai-note" role="status">Проверяю связь и картинки…</p>' : ''}
      ${pr ? `<p class="ai-msg" data-kind="${pr.reachable && pr.text_ok ? 'ok' : 'bad'}" role="status">
        ${pr.reachable ? (pr.text_ok ? 'Сервер отвечает.' : 'Сервер доступен, но не ответил на текст.') : 'Сервер недоступен.'} ${esc(pr.detail || '')}</p>` : ''}
      ${(pr || d.vision) ? `<p class="ai-chip" data-kind="${v === 'yes' ? 'ok' : v === 'no' ? 'warn' : ''}">${esc(aiVisionText(v))}</p>` : ''}
      ${W.setMsg ? aiErr(W.setMsg) : ''}
      <div class="ai-row"><button class="primary" data-sact="probe">Сохранить и проверить</button>
        <button class="ghost" data-sact="models">Список моделей</button></div>
      <p class="ai-note">Шаги и скриншоты отправляются на этот сервер.</p>`;
}

function aiLocalCard() {
    const L = W.local;
    if (!L) return `<h3>Локальная модель (Ollama)</h3>${W.localErr ? aiErr(W.localErr) : '<p class="ai-note">Загружаю…</p>'}<button data-sact="localreload">Повторить</button>`;
    const hw = W.hw;
    const o = L.ollama || {};
    const task = W.task2;
    const p = aiProgress(task);
    // Без сырого имени процессора («AMD64 Family 26…»): оператору важны память, диск и видеокарта.
    const hwParts = hw ? [hw.ram_gb != null ? `${Math.round(hw.ram_gb)} ГБ памяти` : '', hw.disk_free_gb != null ? `${Math.round(hw.disk_free_gb)} ГБ свободно`
        : '', ...(hw.gpus || []).map(g => g.name + (g.vram_gb ? ` (${Math.round(g.vram_gb)} ГБ)` : ''))].filter(Boolean) : [];
    const hwTxt = hwParts.join(' · ');
    let state;
    if (!o.installed) state = `<p class="ai-msg" data-kind="warn">Ollama не найдена. Установите и запустите её.</p>
      <div class="ai-row"><a class="ai-link" href="${esc(o.url || o.download_url || 'https://ollama.com/download')}" target="_blank" rel="noopener">Скачать Ollama</a>
      <button class="sm" data-sact="localreload">Проверить снова</button></div>`;
    else if (!o.running) state = `<p class="ai-msg" data-kind="warn">Ollama установлена, но не запущена.</p><div class="ai-row"><button class="sm" data-sact="localreload">Проверить снова</button></div>`;
    else state = `<span class="ai-chip" data-kind="ok">Ollama работает</span>`;
    const have = (L.models || []).map(x => `<li>${esc(x.name)} <small>${x.size_gb} ГБ</small>
        <button class="sm" data-sact="connect" data-m="${esc(x.name)}">Подключить</button></li>`).join('');
    const recs = (L.recommended || []).map(r => {
        const asked = W.pullAsk === r.id;
        return `<li class="ai-rec" data-fits="${r.fits ? 1 : 0}">
          <div><b>${esc(r.title)}</b> <span class="ai-chip" data-kind="${r.vision ? 'ok' : ''}">${r.vision ? 'понимает картинки' : 'только текст'}</span>
            ${r.fits ? '' : '<span class="ai-chip" data-kind="warn">может не потянуть</span>'}</div>
          <p class="ai-note">${esc(r.why || '')}</p>
          <p class="ai-dim">≈ ${r.download_gb} ГБ загрузка · ≈ ${r.ram_gb_est} ГБ памяти</p>
          ${asked ? `<p class="ai-msg" data-kind="warn">Будет скачано около ${r.download_gb} ГБ в папку ${esc(L.install_path || 'Ollama')}. Продолжить?</p>
            <div class="ai-row"><button class="primary" data-sact="pull" data-m="${esc(r.id)}" data-gb="${r.download_gb}">Да, скачать</button>
            <button data-sact="pullno">Отмена</button></div>`
          : `<button class="sm" data-sact="pullask" data-m="${esc(r.id)}" ${o.running && !(task && ['queued', 'running'].includes(task.state)) ? '' : 'disabled'}>Скачать…</button>`}</li>`;
    }).join('');
    const prog = task ? `<div class="ai-prog" role="status" aria-live="polite">
        ${p.kind === 'real' ? `<progress max="100" value="${p.value}"></progress>` : p.kind === 'indeterminate' ? '<progress></progress>' : ''}
        <p class="${p.kind === 'error' ? 'ai-msg' : 'ai-note'}" ${p.kind === 'error' ? 'data-kind="bad"' : ''}>${esc(p.text)}</p>
        <div class="ai-row">${task.can_cancel ? '<button class="sm danger" data-sact="cancel">Отменить</button>' : ''}
        ${task.can_retry ? '<button class="sm" data-sact="retry">Повторить</button>' : ''}
        ${task.state === 'done' ? `<button class="sm primary" data-sact="connect" data-m="${esc(W.pullModel)}">Подключить модель</button>` : ''}</div></div>` : '';
    return `<h3>Локальная модель</h3>
      ${hwTxt ? `<p class="ai-note" title="Характеристики компьютера фермы">${esc(hwTxt)}</p>` : ''}${state}
      ${have ? `<h4>Скачано</h4><ul class="ai-recs">${have}</ul>` : ''}
      ${recs ? `<h4>Рекомендуем</h4><ul class="ai-recs">${recs}</ul><p class="ai-dim">Папка установки: ${esc(L.install_path || '—')}</p>` : ''}
      ${prog}${W.localMsg ? aiErr(W.localMsg) : ''}`;
}

async function aiLocalLoad() {
    try {
        const [st, hw] = await Promise.all([aiGet('/local/status'), aiGet('/hardware').catch(() => null)]);
        W.local = st;
        W.hw = hw;
        W.localErr = '';
    } catch (e) {
        W.local = null;
        W.localErr = e.message;
    }
    aiSetPaint();
}

function aiSetBody() {
    const url = $('aiUrl'), key = $('aiKey'), model = $('aiModel');
    return {url: url.value.trim(), key: key.value, model: model.value.trim()};
}

async function aiSetClick(e) {
    const b = e.currentTarget, a = b.dataset.sact;
    W.setMsg = ''; W.localMsg = '';
    try {
        if (a === 'reload') return aiSetLoad();
        if (a === 'localreload') { W.local = null; aiSetPaint(); return aiLocalLoad(); }
        if (a === 'models') {
            const f = aiSetBody();
            const tok = aiBegin('models');
            const body = {url: f.url};
            if (f.key && f.key !== W.set.key && !/^\*+$/.test(f.key)) body.key = f.key;
            const r = await aiPost('/models', body);
            if (W.req.models !== tok.n) return;
            W.models = r;
            W.set = Object.assign({}, W.set, f, {key: W.set.key});
            return aiSetPaint();
        }
        if (a === 'probe') {
            const f = aiSetBody();
            const tok = aiBegin('probe');
            W.probeBusy = true; W.probe = null; aiSetPaint();
            const d = W.set;
            await api('/api/vlm', {method: 'PUT', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({enabled: d.enabled !== false, url: f.url, model: f.model, key: f.key || d.key || '',
                    max_per_job: d.max_per_job, max_per_day: d.max_per_day})});
            const r = await aiPost('/probe', {url: f.url, model: f.model});
            if (W.req.probe !== tok.n) return;
            W.probe = r;
            W.probeBusy = false;
            await aiSetLoad();
            return;
        }
        if (a === 'pullask') { W.pullAsk = b.dataset.m; return aiSetPaint(); }
        if (a === 'pullno') { W.pullAsk = null; return aiSetPaint(); }
        if (a === 'pull' || a === 'retry') {
            const m = a === 'retry' ? W.pullModel : b.dataset.m;
            const rec = (W.local.recommended || []).find(x => x.id === m) || {};
            W.pullAsk = null;
            W.pullModel = m;
            const r = await aiPost('/local/pull', {model: m, confirm: true,
                download_gb: rec.download_gb, install_path: W.local.install_path});
            W.task2 = {state: 'queued', stage: 'ставлю в очередь', percent: null, can_cancel: true, id: r.task_id};
            aiSetPaint();
            return aiTaskPoll();
        }
        if (a === 'cancel' && W.task2) {
            await aiPost('/local/tasks/' + encodeURIComponent(W.task2.id) + '/cancel');
            return aiTaskPoll();
        }
        if (a === 'connect') {
            const r = await aiPost('/local/connect', {model: b.dataset.m});
            W.probe = r && r.reachable !== undefined ? r : W.probe;
            W.localMsg = '';
            await aiSetLoad();
            W.setMsg = '';
            return;
        }
    } catch (err) {
        W.probeBusy = false;
        if (a === 'probe' || a === 'models') W.setMsg = err.message; else W.localMsg = err.message;
        aiSetPaint();
    }
}

async function aiTaskPoll() {
    clearTimeout(W.setTimer);
    const t0 = W.task2;
    if (!t0 || !aiSetAlive()) return;
    const tok = aiBegin('task');
    try {
        const r = await aiGet('/local/tasks/' + encodeURIComponent(t0.id));
        if (W.req.task !== tok.n || !aiSetAlive()) return;
        W.task2 = Object.assign({}, r, {id: t0.id});
        aiSetPaint();
        if (!['done', 'error', 'cancelled'].includes(r.state)) {
            if (!document.hidden) W.setTimer = setTimeout(aiTaskPoll, 1000);
            else document.addEventListener('visibilitychange', function f() {
                document.removeEventListener('visibilitychange', f);
                aiTaskPoll();
            });
        } else if (r.state === 'done') {
            aiLocalLoad();
        }
    } catch (e) {
        if (W.req.task !== tok.n) return;
        W.task2 = Object.assign({}, t0, {state: 'error', error: e.message, can_cancel: false, can_retry: true});
        aiSetPaint();
    }
}
