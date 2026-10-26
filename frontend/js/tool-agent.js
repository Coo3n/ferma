'use strict';

/* Инструмент «ИИ-агент»: ведёт один телефон по шагам. Агент смотрит на кадр
   экрана и предлагает ОДНО действие; человек выполняет его, пропускает или
   останавливает всё. Режим «Выполнять сам» делает шаги без вопросов, но не
   больше выбранного числа. Само действие выполняет сервер после проверки.

   Файл делится на две части. Верхняя — чистая: конечный автомат agentNext,
   слова про действия и математика меток на кадре (проверяются в Node, см.
   tests/test_tool_agent_js.py). Нижняя — окно: оно только зовёт автомат и
   рисует то, что он решил. */

const AGENT_HARD_MAX = 30;       // больше сервер всё равно не даст (AGENT_MAX_STEPS)
const AGENT_DEFAULT_LIMIT = 15;
const AGENT_RUNNING = ['thinking', 'doing'];
const AGENT_LIVE = ['thinking', 'proposed', 'doing'];
const AGENT_END = ['done', 'needs_human', 'stopped', 'error'];

/* ------------------------------------------------------------ автомат */

function agentClampLimit(n) {
    n = Math.floor(Number(n));
    if (!isFinite(n) || n < 1) return AGENT_DEFAULT_LIMIT;
    return Math.min(n, AGENT_HARD_MAX);
}

function agentInit(auto, limit) {
    return {phase: 'idle', history: [], proposal: null, auto: !!auto,
            limit: agentClampLimit(limit == null ? AGENT_DEFAULT_LIMIT : limit),
            reason: '', error: '', errorFrom: '', inflight: false};
}

/* Потолок шагов сеанса: в режиме «сам» — выбранное число, иначе общий предел. */
function agentCap(s) {
    return s.auto ? s.limit : AGENT_HARD_MAX;
}

function agentPush(s, result) {
    const p = s.proposal || {};
    return s.history.concat([{action: p.action, why: p.why || '', result}]);
}

/* Следующий шаг после выполненного или пропущенного: либо снова «смотрю на
   экран», либо предел — тогда остановка, а не ещё один запрос. */
function agentAfterStep(s) {
    if (s.history.length >= agentCap(s)) return agentNext(s, {type: 'limit'});
    return Object.assign({}, s, {phase: 'thinking', proposal: null});
}

function agentNext(s, ev) {
    const type = ev && ev.type;
    const phase = s.phase;
    switch (type) {
    case 'start':
        if (AGENT_LIVE.includes(phase)) return s;
        return Object.assign(agentInit(ev.auto != null ? ev.auto : s.auto,
                                       ev.limit != null ? ev.limit : s.limit), {phase: 'thinking'});
    case 'reset':
        return agentInit(s.auto, s.limit);
    case 'auto':
        return Object.assign({}, s, {auto: !!ev.on,
            limit: ev.limit != null ? agentClampLimit(ev.limit) : s.limit});
    case 'proposal':
        if (phase !== 'thinking') return s;
        return Object.assign({}, s, {phase: s.auto ? 'doing' : 'proposed',
            proposal: {action: ev.action, why: ev.why || ''}, inflight: s.auto});
    case 'ask':
        if (phase !== 'thinking') return s;
        return Object.assign({}, s, {phase: 'needs_human', reason: ev.why || '', proposal: null});
    case 'done':
        if (phase !== 'thinking') return s;
        return Object.assign({}, s, {phase: 'done', reason: ev.why || '', proposal: null});
    case 'execute':
        if (phase !== 'proposed') return s;
        return Object.assign({}, s, {phase: 'doing', inflight: true});
    case 'executed':
        if (phase === 'doing') {
            return agentAfterStep(Object.assign({}, s, {history: agentPush(s, 'ok'), inflight: false}));
        }
        /* Остановили, пока действие шло: оно всё равно случилось на телефоне,
           значит попадает в историю (и в сценарий), но остановка остаётся. */
        if (phase === 'stopped' && s.inflight && s.proposal) {
            return Object.assign({}, s, {history: agentPush(s, 'ok'), proposal: null, inflight: false});
        }
        return s;
    case 'skip':
        if (phase !== 'proposed') return s;
        return agentAfterStep(Object.assign({}, s, {history: agentPush(s, 'skipped')}));
    case 'error':
        if (!AGENT_LIVE.includes(phase)) return s;
        return Object.assign({}, s, {phase: 'error', error: ev.message || '',
            errorFrom: phase === 'thinking' ? 'thinking' : 'doing', inflight: false});
    case 'retry':
        if (phase !== 'error') return s;
        return Object.assign({}, s, {phase: s.errorFrom === 'thinking' ? 'thinking' : 'doing',
            error: '', inflight: s.errorFrom !== 'thinking'});
    case 'stop':
        if (!AGENT_LIVE.includes(phase) && phase !== 'error') return s;
        return Object.assign({}, s, {phase: 'stopped', reason: 'user',
            inflight: phase === 'doing'});
    case 'limit':
        if (!AGENT_LIVE.includes(phase) && phase !== 'error') return s;
        return Object.assign({}, s, {phase: 'stopped', reason: 'limit', inflight: false});
    default:
        return s;
    }
}

/* Ответ /api/vlm/agent/step → событие автомата. */
function agentReplyEvent(res) {
    res = res || {};
    if (res.done) return {type: 'done', why: res.why || ''};
    if (res.ask) return {type: 'ask', why: res.why || ''};
    if (res.action) return {type: 'proposal', action: res.action, why: res.why || '', step_no: res.step_no};
    return {type: 'error', message: ''};
}

function agentHistoryForApi(history) {
    return history.map(h => ({action: h.action, why: h.why || '', result: h.result}));
}

function agentExecutedCount(history) {
    return history.filter(h => h.result === 'ok').length;
}

function agentCanSave(s) {
    return AGENT_END.includes(s.phase) && agentExecutedCount(s.history) >= 1;
}

function agentRunning(s) {
    return AGENT_RUNNING.includes(s.phase);
}

/* «Шаг N из M»: пока агент работает, N — шаг, который сейчас на очереди. */
function agentProgress(s) {
    const m = agentCap(s);
    const live = AGENT_LIVE.includes(s.phase);
    const n = Math.min(m, s.history.length + (live ? 1 : 0));
    return {n, m, pct: m ? Math.round(100 * n / m) : 0};
}

/* Что показать в полосе состояния: ключ строки и тон. */
function agentBanner(s) {
    switch (s.phase) {
    case 'thinking': return {key: 'agent.smotryu', tone: 'busy'};
    case 'proposed': return {key: 'agent.zhdu', tone: 'ask'};
    case 'doing': return {key: 'agent.vypolnyayu', tone: 'doing'};
    case 'done': return {key: 'agent.gotovo', tone: 'ok'};
    case 'needs_human': return {key: 'agent.nuzhen_chelovek', tone: 'warn'};
    case 'stopped': return {key: 'agent.ostanovleno', tone: 'dim'};
    case 'error': return {key: 'agent.oshibka', tone: 'bad'};
    default: return {key: '', tone: ''};
    }
}

/* ------------------------------------------------- действия словами */

function agentSwipeDir(a) {
    const dx = a.x2 - a.x1, dy = a.y2 - a.y1;
    if (Math.abs(dx) < 0.02 && Math.abs(dy) < 0.02) return '';
    if (Math.abs(dy) >= Math.abs(dx)) return dy < 0 ? 'up' : 'down';
    return dx < 0 ? 'left' : 'right';
}

function agentHost(url) {
    const m = /^https?:\/\/([^/?#]+)/i.exec(String(url || ''));
    return m ? m[1].replace(/^www\./, '') : '';
}

function agentActionText(a) {
    if (!a) return t('agent.a_unknown');
    switch (a.kind) {
    case 'tap': return t('agent.a_tap');
    case 'swipe': {
        const dir = agentSwipeDir(a);
        const words = {up: () => t('agent.a_up'), down: () => t('agent.a_down'),
                       left: () => t('agent.a_left'), right: () => t('agent.a_right')};
        return dir ? words[dir]() : t('agent.a_swipe');
    }
    case 'type': {
        const v = String(a.value == null ? '' : a.value);
        return t('agent.a_type', {text: v.length > 60 ? v.slice(0, 59) + '…' : v});
    }
    case 'key':
    {
        const keys = {back: () => t('agent.a_key_back'), home: () => t('agent.a_key_home'),
                      enter: () => t('agent.a_key_enter'), recents: () => t('agent.a_key_recents'),
                      delete: () => t('agent.a_key_delete')};
        return Object.prototype.hasOwnProperty.call(keys, a.name) ? keys[a.name]() : t('agent.a_key');
    }
    case 'launch_app': return t('agent.a_launch');
    case 'open_url': {
        const host = agentHost(a.url);
        return host ? t('agent.a_url', {host}) : t('agent.a_url0');
    }
    case 'wait': return t('agent.a_wait', {n: Math.round(Number(a.seconds) * 10) / 10 || 1});
    default: return t('agent.a_unknown');
    }
}

/* Шаг рецепта (из /api/vlm/plan) → то же действие словами. */
function agentStepWords(step) {
    const args = (step && step.args) || {};
    const kind = step && step.kind;
    if (kind === 'sleep') return agentActionText({kind: 'wait', seconds: args.seconds});
    if (kind === 'key') return agentActionText({kind: 'key', name: args.name});
    return agentActionText(Object.assign({}, args, {kind}));
}

/* ------------------------------------------- метки поверх кадра */

function agentFrac(v) {
    v = Number(v);
    return isFinite(v) ? Math.min(1, Math.max(0, v)) : 0;
}

/* Прицел: доли экрана → проценты рамки кадра (0.1 точности). */
function agentReticle(x, y) {
    const pct = v => Math.round(agentFrac(v) * 1000) / 10;
    return {left: pct(x), top: pct(y)};
}

/* Стрелка свайпа в пикселях кадра w×h: линия и наконечник-треугольник. Считаем
   в пикселях, а не в долях — иначе на вытянутом экране наконечник кривой. */
function agentArrow(a, w, h) {
    const x1 = agentFrac(a.x1) * w, y1 = agentFrac(a.y1) * h;
    const x2 = agentFrac(a.x2) * w, y2 = agentFrac(a.y2) * h;
    const len = Math.hypot(x2 - x1, y2 - y1);
    const size = Math.min(w, h) * 0.06;
    const r = v => Math.round(v * 10) / 10;
    let head = '';
    if (len > 0) {
        const ux = (x2 - x1) / len, uy = (y2 - y1) / len;
        const bx = x2 - ux * size, by = y2 - uy * size;
        head = [[x2, y2], [bx - uy * size * 0.55, by + ux * size * 0.55],
                [bx + uy * size * 0.55, by - ux * size * 0.55]]
            .map(p => r(p[0]) + ',' + r(p[1])).join(' ');
    }
    return {x1: r(x1), y1: r(y1), x2: r(x2), y2: r(y2), head, len: r(len)};
}

/* ---------------------------------------------------------- окно */

const AGENT = {
    st: agentInit(), run: 0, root: null, serial: '', task: '', vlm: null,
    plan: null, planBusy: false, saving: false, ar: 0,
};

const agentExamples = () => [t('agent.primer_1'), t('agent.primer_2'), t('agent.primer_3'), t('agent.primer_4')];

function agentJson(body) {
    return {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
}

function agentAlive() {
    return !!AGENT.root && document.body.contains(AGENT.root) && $('modal').classList.contains('on');
}

function agentPhones() {
    return (S.devices || []).filter(d => d.online && d.enabled !== false);
}

function agentIcon(name) {
    return `<svg class="ic" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

async function agentOpen() {
    const run = ++AGENT.run;
    AGENT.st = agentInit(false, store.get('farm.agent.limit', AGENT_DEFAULT_LIMIT));
    AGENT.plan = null;
    AGENT.root = null;
    $('mTitle').textContent = t('agent.zagolovok');
    $('mBody').innerHTML = `<div class="ag-load" role="status"><span class="ag-dots"><i></i><i></i><i></i></span>
        ${esc(t('agent.zagruzka'))}</div>`;
    agentActs();
    modalSheet('agent');
    openModal();
    let vlm;
    try {
        vlm = await api('/api/vlm');
    } catch (e) {
        if (run !== AGENT.run) return;
        $('mBody').innerHTML = emptyBig({art: 'calm', title: esc(t('agent.ne_zagruzilos')), text: esc(e.message),
            action: {label: esc(t('agent.povtorit')), onClick: 'agentOpen()'}});
        return;
    }
    if (run !== AGENT.run) return;
    AGENT.vlm = vlm;
    if (!(vlm.enabled && vlm.configured)) {
        $('mBody').innerHTML = emptyBig({art: 'calm', title: esc(t('agent.vykl_title')), text: esc(t('agent.vykl_text')),
            action: {label: esc(t('agent.otkryt_nastroyki')), onClick: 'vlmOpen()'}});
        return;
    }
    agentBuild();
}

function agentActs() {
    $('mActs').innerHTML = `<button id="agBack" onclick="agentLeave(this, toolsOpen)">${esc(t('tools.nazad'))}</button>
        <span class="sp"></span><button id="agClose" onclick="closeModal()">${esc(t('tools.zakryt'))}</button>`;
}

function agentBuild() {
    const phones = agentPhones();
    const saved = store.get('farm.agent.serial', '');
    const pick = [saved, S.active].find(s => s && phones.some(d => d.serial === s)) || (phones[0] || {}).serial || '';
    const task = store.get('farm.agent.task', '');
    const lim = AGENT.st.limit;
    $('mBody').innerHTML = `
      <div class="ag" id="agRoot" data-phase="idle">
        <section class="ag-setup" id="agSetup">
          <div class="ag-fields">
            <label class="ag-field ag-phone"><span>${esc(t('agent.telefon'))}</span>
              <select id="agPhone" onchange="agentFrame()" ${phones.length ? '' : 'disabled'}>${phones.length
                ? phones.map(d => `<option value="${esc(d.serial)}" ${d.serial === pick ? 'selected' : ''}>${esc(
                    d.busy_job ? t('agent.zanyat', {name: d.name}) : d.name)}</option>`).join('')
                : `<option>${esc(t('agent.net_telefonov'))}</option>`}</select></label>
            <label class="ag-field ag-task"><span>${esc(t('agent.zadacha'))}</span>
              <input id="agTask" maxlength="300" autocomplete="off" value="${esc(task)}"
                     placeholder="${esc(t('agent.zadacha_ph'))}"></label>
            <button class="primary ag-start" id="agStart" onclick="agentStart()">${agentIcon('play')}${esc(t('agent.nachat'))}</button>
          </div>
          <div class="ag-chips" id="agChips">${agentExamples().map(text =>
            `<button type="button" class="sm ag-chip" onclick="agentChip(this)">${esc(text)}</button>`).join('')}</div>
          <div class="ag-sub">
            <button class="sm" id="agPlanBtn" onclick="agentPlan()" title="${esc(t('agent.sostavit_podskazka'))}">
              ${agentIcon('list-checks')}${esc(t('agent.sostavit'))}</button>
            <small>${esc(t('agent.privatnost'))}</small>
          </div>
        </section>
        <section class="ag-summary" id="agSummary" hidden>
          <span class="ag-sum-phone">${agentIcon('phone')}<b id="agSumPhone"></b></span>
          <span class="ag-sum-task" id="agSumTask"></span>
          <button class="sm" id="agNew" onclick="agentReset()" hidden>${agentIcon('plus')}${esc(t('agent.novaya'))}</button>
        </section>
        <div class="ag-main">
          <section class="ag-screen">
            <div class="ag-device" id="agDevice">
              <img id="agFrame" alt="${esc(t('agent.kadr_alt'))}" hidden>
              <div class="ag-noframe" id="agNoFrame">${agentIcon('phone')}<span id="agNoFrameText">${esc(t('agent.kadr_pusto'))}</span></div>
              <div class="ag-over" id="agOver" aria-hidden="true"></div>
              <button class="sm ag-refresh" id="agRefresh" onclick="agentFrame()" title="${esc(t('agent.kadr_obnovit'))}"
                      aria-label="${esc(t('agent.kadr_obnovit'))}" hidden>${agentIcon('refresh')}</button>
            </div>
          </section>
          <section class="ag-side">
            <div class="ag-banner" id="agBanner" role="status" aria-live="polite" hidden></div>
            <div class="ag-prog" id="agProg" hidden>
              <span class="ag-prog-n" id="agProgN"></span>
              <span class="ag-prog-bar"><i id="agProgBar"></i></span>
              <span class="ag-prog-use" id="agUsage"></span>
            </div>
            <div class="ag-scroll" id="agScroll"><ol class="ag-tl" id="agTl"></ol><div id="agPlanOut"></div></div>
          </section>
        </div>
        <footer class="ag-bar" id="agBar">
          <div class="ag-auto">
            <button type="button" class="ag-sw" id="agAuto" role="switch" aria-checked="false" onclick="agentToggleAuto(this)"
                    title="${esc(t('agent.sam_title'))}"><i class="ag-track" aria-hidden="true"></i><span>${esc(t('agent.sam'))}</span></button>
            <label class="ag-lim">${esc(t('agent.ne_bolshe'))}
              <input type="number" id="agLimit" min="1" max="${AGENT_HARD_MAX}" value="${lim}" onchange="agentLimitChanged()">
              ${esc(t('agent.shagov'))}</label>
          </div>
          <div class="ag-acts">
            <button id="agStop" class="ag-stop" onclick="agentSend({type:'stop'})" hidden>${agentIcon('stop')}${esc(t('agent.ostanovit'))}<kbd>Esc</kbd></button>
            <button id="agSkip" onclick="agentSend({type:'skip'})" hidden>${esc(t('agent.propustit'))}<kbd>S</kbd></button>
            <button id="agRun" class="primary" onclick="agentSend({type:'execute'})" hidden>${agentIcon('check')}${esc(t('agent.vypolnit'))}<kbd>Enter</kbd></button>
            <button id="agSave" class="primary" onclick="agentSave()" hidden>${agentIcon('save')}${esc(t('agent.sohranit'))}</button>
          </div>
        </footer>
      </div>`;
    AGENT.root = $('agRoot');
    AGENT.root.addEventListener('keydown', agentFieldKey);
    agentUsagePaint();
    agentPaint(null);
    agentFrame();
    const input = $('agTask');
    if (input) input.focus();
}

/* ---- ввод и клавиши */

function agentFieldKey(ev) {
    if (ev.key === 'Enter' && ev.target && ev.target.id === 'agTask') {
        ev.preventDefault();
        ev.stopPropagation();
        agentStart();
    }
}

function agentChip(btn) {
    const input = $('agTask');
    input.value = btn.textContent;
    input.focus();
}

/* Горячие клавиши окна. Перехватываем раньше общего обработчика Esc из core.js:
   пока агент жив, Esc останавливает его, а не закрывает окно. */
document.addEventListener('keydown', ev => {
    if (!agentAlive() || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const s = AGENT.st;
    const tag = ev.target && ev.target.tagName;
    const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
    if (ev.key === 'Escape') {
        if (AGENT_LIVE.includes(s.phase) || s.phase === 'error') {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            agentSend({type: 'stop'});
        }
        return;
    }
    if (typing || tag === 'BUTTON' && ev.key === 'Enter') return;
    if (ev.key === 'Enter' && s.phase === 'proposed') {
        ev.preventDefault();
        agentSend({type: 'execute'});
    } else if ((ev.key === 's' || ev.key === 'S' || ev.key === 'ы' || ev.key === 'Ы') && s.phase === 'proposed') {
        ev.preventDefault();
        agentSend({type: 'skip'});
    }
}, true);

/* Закрыть окно, пока агент работает, — по второму нажатию: он остановится. */
(function agentHookClose() {
    const orig = window.closeModal;
    window.closeModal = function () {
        if (agentAlive() && agentRunning(AGENT.st)) {
            /* Второе нажатие — на «×» в шапке: красная заливка + подсказка словами. */
            const btn = document.querySelector('#modal .mhead button');
            if (btn && !armConfirm(btn)) {
                toast(t('agent.zakryt_podtverdit'));
                return;
            }
            agentSend({type: 'stop'});
        }
        if (agentAlive()) AGENT.run++;   // летящие ответы больше не наши
        return orig.apply(this, arguments);
    };
}());

function agentLeave(btn, then) {
    if (agentRunning(AGENT.st)) {
        if (!armConfirm(btn, t('agent.nazad_podtverdit'))) return;
        agentSend({type: 'stop'});
    }
    AGENT.run++;
    then();
}

function agentToggleAuto(btn) {
    const on = btn.getAttribute('aria-checked') === 'true';
    if (on) {
        agentSetAuto(false);
        return;
    }
    /* Включить «сам» — второе нажатие: агент начнёт нажимать без вопросов. */
    if (!armConfirm(btn, t('agent.sam_podtverdit'))) return;
    delete btn.dataset.armed;
    btn.classList.remove('armed');
    (btn.querySelector('span') || btn).textContent = btn.dataset.label;
    agentSetAuto(true);
}

function agentSetAuto(on) {
    const limit = agentClampLimit($('agLimit').value);
    store.set('farm.agent.limit', limit);
    agentSend({type: 'auto', on, limit});
}

function agentLimitChanged() {
    const input = $('agLimit');
    const limit = agentClampLimit(input.value);
    input.value = limit;
    store.set('farm.agent.limit', limit);
    agentSend({type: 'auto', on: AGENT.st.auto, limit});
}

/* ---- запуск и ход */

function agentStart() {
    if (AGENT_LIVE.includes(AGENT.st.phase)) return;
    const serial = ($('agPhone') || {}).value;
    const task = $('agTask').value.trim();
    if (!agentPhones().some(d => d.serial === serial)) return toast(t('agent.net_telefonov'), 'bad');
    if (!task) {
        toast(t('agent.opishite'), 'bad');
        return $('agTask').focus();
    }
    AGENT.serial = serial;
    AGENT.task = task;
    AGENT.plan = null;
    AGENT.run++;
    store.set('farm.agent.task', task);
    store.set('farm.agent.serial', serial);
    agentFrame();
    agentSend({type: 'start', limit: agentClampLimit($('agLimit').value)});
}

function agentReset() {
    AGENT.run++;
    AGENT.plan = null;
    agentSend({type: 'reset'});
    const input = $('agTask');
    if (input) input.focus();
}

function agentSend(ev) {
    const prev = AGENT.st;
    const next = agentNext(prev, ev);
    if (next === prev && ev.type !== 'auto') return;
    AGENT.st = next;
    agentPaint(prev);
    if (next.phase === 'thinking' && prev.phase !== 'thinking') agentFetchStep(ev.type === 'executed' ? 700 : 0);
    if (next.phase === 'doing' && prev.phase !== 'doing') agentExecute();
}

function agentSleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function agentFetchStep(settle) {
    const run = AGENT.run;
    if (settle) await agentSleep(settle);   // экран после действия успевает перерисоваться
    if (run !== AGENT.run || AGENT.st.phase !== 'thinking') return;
    if (settle) agentFrame();
    let res;
    try {
        res = await api('/api/vlm/agent/step', agentJson({
            serial: AGENT.serial, task: AGENT.task, history: agentHistoryForApi(AGENT.st.history)}));
    } catch (e) {
        if (run === AGENT.run) agentSend({type: 'error', message: e.message});
        return;
    }
    if (run !== AGENT.run) return;
    const ev = agentReplyEvent(res);
    if (ev.type === 'error') ev.message = t('agent.pustoy_otvet');
    agentSend(ev);
    agentUsageRefresh();
}

async function agentExecute() {
    const run = AGENT.run;
    const proposal = AGENT.st.proposal;
    if (!proposal) return;
    try {
        await api('/api/vlm/agent/do', agentJson({serial: AGENT.serial, action: proposal.action}));
    } catch (e) {
        if (run === AGENT.run) agentSend({type: 'error', message: e.message});
        return;
    }
    if (run !== AGENT.run) return;
    agentSend({type: 'executed'});
    if (AGENT.st.phase !== 'thinking') setTimeout(agentFrame, 700);   // иначе кадр обновит следующий шаг
}

async function agentUsageRefresh() {
    try {
        AGENT.vlm = await api('/api/vlm');
    } catch (e) {
        return;
    }
    agentUsagePaint();
    if (window.vlmChipPaint && window.VLM) { VLM.data = AGENT.vlm; vlmChipPaint(); }
}

function agentUsagePaint() {
    const d = AGENT.vlm;
    if (d && $('agUsage')) setText($('agUsage'), t('agent.limit_dnya', {n: d.used_today, m: d.max_per_day}));
}

/* ---- кадр телефона */

function agentFrame() {
    const img = $('agFrame');
    if (!img || !AGENT.root) return;
    const serial = AGENT.st.phase === 'idle' ? ($('agPhone') || {}).value : AGENT.serial;
    if (!serial || !agentPhones().some(d => d.serial === serial)) return;
    const run = AGENT.run, pre = new Image();
    pre.onload = () => {
        if (!agentAlive()) return;
        AGENT.ar = pre.naturalWidth / pre.naturalHeight;
        $('agDevice').style.setProperty('--ar', pre.naturalWidth + ' / ' + pre.naturalHeight);
        $('agDevice').dataset.w = pre.naturalWidth;
        $('agDevice').dataset.h = pre.naturalHeight;
        img.src = pre.src;
        img.hidden = false;
        $('agNoFrame').hidden = true;
        $('agRefresh').hidden = false;
        agentOverlay();
    };
    pre.onerror = () => {
        if (!agentAlive()) return;
        if (img.hidden) {   // старый кадр лучше пустоты: оставляем его
            setText($('agNoFrameText'), t('agent.kadr_oshibka'));
            $('agNoFrame').hidden = false;
        }
        $('agRefresh').hidden = false;
    };
    pre.src = `/api/devices/${encodeURIComponent(serial)}/frame?t=${Date.now()}`;
}

/* Метка предложенного действия поверх кадра. */
function agentOverlay() {
    const over = $('agOver');
    if (!over) return;
    const s = AGENT.st, a = s.proposal && s.proposal.action;
    const show = a && (s.phase === 'proposed' || s.phase === 'doing');
    if (!show) return setHTML(over, '');
    const dev = $('agDevice');
    const w = Number(dev.dataset.w) || 1080, h = Number(dev.dataset.h) || 2340;
    if (a.kind === 'tap') {
        const r = agentReticle(a.x, a.y);
        setHTML(over, `<span class="ag-ret" style="left:${r.left}%;top:${r.top}%"><i></i><i></i><b></b></span>`);
    } else if (a.kind === 'swipe') {
        const ar = agentArrow(a, w, h);
        const sw = Math.round(Math.min(w, h) * 0.012);
        setHTML(over, `<svg class="ag-arrow" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="--len:${ar.len}">
            <line x1="${ar.x1}" y1="${ar.y1}" x2="${ar.x2}" y2="${ar.y2}" stroke-width="${sw}"/>
            <polygon points="${ar.head}"/><circle cx="${ar.x1}" cy="${ar.y1}" r="${Math.round(Math.min(w, h) * 0.018)}"/></svg>`);
    } else if (a.kind === 'type') {
        setHTML(over, `<div class="ag-bubble">${agentIcon('text-input')}<span>${esc(a.value)}</span></div>`);
    } else {
        setHTML(over, `<div class="ag-bubble ag-bubble-plain">${esc(agentActionText(a))}</div>`);
    }
}

/* ---- отрисовка */

const AGENT_CARD_ICON = {ok: 'check', skip: 'right', err: 'alert', stop: 'stop', wait: 'target', doing: 'zap'};

function agentCardHtml(st, n, title, why, label) {
    const mark = st === 'doing' ? '<span class="ag-spin"></span>'
        : (AGENT_CARD_ICON[st] ? agentIcon(AGENT_CARD_ICON[st]) : '');
    return `<li class="ag-card" data-st="${st}">
        <span class="ag-mark">${mark}<em>${n}</em></span>
        <div class="ag-cbody"><div class="ag-ctitle">${esc(title)}</div>${why ? `<div class="ag-why">${esc(why)}</div>` : ''}</div>
        <span class="ag-cstate">${esc(label)}</span></li>`;
}

function agentTimelineHtml(s) {
    const cards = s.history.map((h, i) => h.result === 'skipped'
        ? agentCardHtml('skip', i + 1, agentActionText(h.action), h.why, t('agent.propusheno'))
        : agentCardHtml('ok', i + 1, agentActionText(h.action), h.why, t('agent.vypolneno')));
    const n = s.history.length + 1;
    const p = s.proposal;
    if (p && s.phase === 'proposed') cards.push(agentCardHtml('wait', n, agentActionText(p.action), p.why, t('agent.predlagaet')));
    else if (p && s.phase === 'doing') cards.push(agentCardHtml('doing', n, agentActionText(p.action), p.why, t('agent.vypolnyayu')));
    else if (p && s.phase === 'error' && s.errorFrom === 'doing') cards.push(agentCardHtml('err', n, agentActionText(p.action), p.why, t('agent.ne_vyshlo')));
    else if (p && s.phase === 'stopped' && s.inflight) cards.push(agentCardHtml('stop', n, agentActionText(p.action), p.why, t('agent.ostanovleno')));
    return cards.join('');
}

function agentBannerHtml(s) {
    const b = agentBanner(s);
    if (!b.key) return '';
    const dots = '<span class="ag-dots" aria-hidden="true"><i></i><i></i><i></i></span>';
    switch (s.phase) {
    case 'thinking': return `<div class="ag-bn-main">${dots}<b>${esc(t('agent.smotryu'))}</b></div>`;
    case 'proposed': return `<div class="ag-bn-main">${agentIcon('hand')}<b>${esc(t('agent.zhdu'))}</b></div>
        <p>${esc(t('agent.zhdu_podskazka'))}</p>`;
    case 'doing': return `<div class="ag-bn-main"><span class="ag-spin"></span><b>${esc(t('agent.vypolnyayu'))}</b></div>`;
    case 'done': return `<div class="ag-bn-main">${agentIcon('check-circle')}<b>${esc(t('agent.gotovo'))}</b></div>
        ${s.reason ? `<p>${esc(s.reason)}</p>` : ''}`;
    case 'needs_human': return `<div class="ag-bn-main">${agentIcon('hand')}<b>${esc(t('agent.nuzhen_chelovek'))}</b></div>
        <p>${esc(s.reason || t('agent.nuzhen_prichina'))}</p>`;
    case 'stopped': return `<div class="ag-bn-main">${agentIcon('stop')}<b>${esc(t('agent.ostanovleno'))}</b></div>
        <p>${esc(s.reason === 'limit' ? t('agent.ostanovleno_limit', {n: s.history.length}) : t('agent.ostanovleno_vami'))}</p>`;
    case 'error': return `<div class="ag-bn-main">${agentIcon('alert-circle')}<b>${esc(t('agent.oshibka'))}</b></div>
        <p>${esc(s.error || t('agent.pustoy_otvet'))}</p>
        <div class="ag-bn-act"><button class="sm" onclick="agentSend({type:'retry'})">${agentIcon('refresh')}${esc(t('agent.povtorit_shag'))}</button></div>`;
    default: return '';
    }
}

function agentPaint(prev) {
    if (!agentAlive()) return;
    const s = AGENT.st;
    const root = AGENT.root;
    root.dataset.phase = s.phase;
    root.dataset.tone = agentBanner(s).tone;
    const idle = s.phase === 'idle';
    const planShown = !!AGENT.plan;
    $('agSetup').hidden = !idle;
    $('agSummary').hidden = idle;
    if (!idle) {
        const dev = (S.devices || []).find(d => d.serial === AGENT.serial);
        setText($('agSumPhone'), dev ? dev.name : '');
        setText($('agSumTask'), AGENT.task);
        $('agNew').hidden = AGENT_LIVE.includes(s.phase);
    }
    $('agStart').classList.toggle('primary', !planShown);
    /* Полоса состояния и прогресс */
    const banner = $('agBanner');
    banner.hidden = idle;
    banner.dataset.tone = agentBanner(s).tone;
    setHTML(banner, agentBannerHtml(s));
    $('agProg').hidden = idle;
    const pr = agentProgress(s);
    setText($('agProgN'), t('agent.shag_n', {n: pr.n, m: pr.m}));
    $('agProgBar').style.width = pr.pct + '%';
    /* Лента */
    const tl = $('agTl');
    const html = idle ? '' : agentTimelineHtml(s);
    setHTML(tl, html);
    const empty = idle && !AGENT.plan && !AGENT.planBusy;
    setHTML($('agPlanOut'), empty ? emptyBig({art: 'steps', title: esc(t('agent.pusto')), text: esc(t('agent.pusto_d'))})
        : (idle ? agentPlanHtml() : ''));
    const box = $('agScroll');
    if (!prev || prev.history.length !== s.history.length || prev.phase !== s.phase) {
        box.scrollTo({top: box.scrollHeight, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    }
    /* Панель управления: кнопки по состоянию */
    $('agRun').hidden = s.phase !== 'proposed';
    $('agRun').classList.toggle('ag-pulse', s.phase === 'proposed');
    $('agSkip').hidden = s.phase !== 'proposed';
    $('agStop').hidden = !AGENT_LIVE.includes(s.phase) && s.phase !== 'error';
    const canSave = agentCanSave(s);
    $('agSave').hidden = !canSave;
    $('agSave').disabled = AGENT.saving;
    const sw = $('agAuto');
    sw.setAttribute('aria-checked', s.auto ? 'true' : 'false');
    if (document.activeElement !== $('agLimit')) $('agLimit').value = s.limit;
    agentOverlay();
}

/* ---- «Составить сразу, без выполнения» */

function agentPlanHtml() {
    if (AGENT.planBusy) {
        return `<div class="ag-plan-busy" role="status"><span class="ag-dots"><i></i><i></i><i></i></span>${esc(t('agent.sostavlyayu'))}</div>`;
    }
    const p = AGENT.plan;
    if (!p) return '';
    if (p.error) {
        return `<div class="ag-plan"><p class="ag-plan-err">${esc(p.error)}</p>
            <button class="sm" onclick="agentPlan()">${agentIcon('refresh')}${esc(t('agent.povtorit'))}</button></div>`;
    }
    return `<div class="ag-plan"><h3>${esc(t('agent.plan_zagolovok', {n: p.steps.length}))}</h3>
        <ol class="ag-tl">${p.steps.map((st, i) => agentCardHtml('plan', i + 1, agentStepWords(st), '', '')).join('')}</ol>
        <div class="ag-plan-act"><button class="accent" onclick="agentPlanSave()">${agentIcon('save')}${esc(t('agent.sohranit'))}</button></div>
        <small class="dim">${esc(t('agent.plan_podskazka'))}</small></div>`;
}

async function agentPlan() {
    const serial = ($('agPhone') || {}).value;
    const task = $('agTask').value.trim();
    if (!agentPhones().some(d => d.serial === serial)) return toast(t('agent.net_telefonov'), 'bad');
    if (!task) {
        toast(t('agent.opishite'), 'bad');
        return $('agTask').focus();
    }
    store.set('farm.agent.task', task);
    store.set('farm.agent.serial', serial);
    AGENT.serial = serial;
    AGENT.plan = null;
    AGENT.planBusy = true;
    agentFrame();
    agentPaint(AGENT.st);
    $('agPlanBtn').disabled = true;
    const run = AGENT.run;
    try {
        const res = await api('/api/vlm/plan', agentJson({serial, task}));
        if (run !== AGENT.run) return;
        AGENT.plan = {steps: res.steps || [], recipe: res.recipe};
    } catch (e) {
        if (run !== AGENT.run) return;
        AGENT.plan = {error: e.message};
    }
    AGENT.planBusy = false;
    if (agentAlive()) {
        $('agPlanBtn').disabled = false;
        agentPaint(AGENT.st);
    }
    agentUsageRefresh();
}

async function agentPlanSave() {
    if (!AGENT.plan || !AGENT.plan.recipe) return;
    await agentSaveRecipe(AGENT.plan.recipe);
}

/* ---- сохранить как сценарий */

async function agentSave() {
    if (AGENT.saving) return;
    AGENT.saving = true;
    $('agSave').disabled = true;
    try {
        const recipe = await api('/api/vlm/agent/recipe', agentJson({
            task: AGENT.task, history: agentHistoryForApi(AGENT.st.history)}));
        await agentSaveRecipe(recipe);
    } catch (e) {
        toast(e.message, 'bad');
    }
    AGENT.saving = false;
    if (agentAlive()) $('agSave').disabled = false;
}

async function agentSaveRecipe(recipe) {
    try {
        await api('/api/recorder/save', agentJson(recipe));
    } catch (e) {
        toast(e.message, 'bad');
        return;
    }
    const key = recipe.key;
    toast(t('agent.sohraneno', {name: recipe.meta.name}), 'ok', {
        label: t('agent.otkryt_konstruktor'),
        onClick: () => {
            closeModal();
            editScenario(key);
        }});
    if (window.loadScenarios) loadScenarios(true);
}

toolsRegister({id: 'agent', icon: 'target', title: t('agent.zagolovok'),
               sub: t('agent.tile_sub'), open: agentOpen});
