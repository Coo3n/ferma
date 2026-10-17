/* Повтор по кругу в конструкторе: «листать ленту 10 минут», «лайкнуть 20
   постов». Сценарий — плоский список шагов, поэтому повтор — тоже шаг
   (kind 'loop', заголовок), а шаги его тела помечены step.inLoop = id
   заголовка и стоят сразу за ним. На сервер уходит span — сколько шагов
   за заголовком входит в тело (recPayload), обратно — по span (recLoopsFromSpan).

   Почему пометка, а не span в самом шаге: список правят руками — тащат,
   удаляют, дописывают записью. Число «следующих N шагов» от каждой правки
   съезжало бы, а пометка остаётся при шаге: вытащили шаг за рамку — он
   вышел из повтора, бросили внутрь рамки — вошёл (recLoopsFix). */

const LOOP_DEFAULT = {times: 10, pause_min: 1, pause_max: 3, watch: true};

function loopIsHead(step) {
    return step && step.kind === 'loop';
}

/* Порядок в списке — источник правды. Тело повтора — подряд идущие за
   заголовком шаги с его пометкой; всё остальное с этой пометкой из повтора
   выходит. Шаг без пометки, брошенный между двумя шагами одного повтора,
   в него входит. Повтор без тела исчезает: пустая рамка ничего не делает. */
function recLoopsFix() {
    let cur = null;
    REC.steps.forEach((step, i) => {
        if (loopIsHead(step)) {
            step.inLoop = null;
            cur = step.id;
            return;
        }
        if (cur != null) {
            if (step.inLoop === cur) return;
            const next = REC.steps[i + 1];
            if (next && next.inLoop === cur) {
                step.inLoop = cur;   // брошен внутрь рамки — вошёл в повтор
                return;
            }
        }
        step.inLoop = null;           // вне подряд идущего тела — не в повторе
        cur = null;
    });
    const empty = REC.steps.filter(s => loopIsHead(s) && !loopBody(s).length).map(s => s.id);
    if (empty.length) REC.steps = REC.steps.filter(s => !empty.includes(s.id));
}

function loopBody(head) {
    const at = REC.steps.indexOf(head);
    const out = [];
    for (let i = at + 1; i < REC.steps.length && REC.steps[i].inLoop === head.id; i++) out.push(REC.steps[i]);
    return out;
}

/* Рецепт с сервера: span → пометки у шагов тела. */
function recLoopsFromSpan() {
    REC.steps.forEach((step, i) => {
        if (!loopIsHead(step)) return;
        const span = Number(step.args.span) || 0;
        for (let k = 1; k <= span && REC.steps[i + k]; k++) REC.steps[i + k].inLoop = step.id;
        delete step.args.span;
    });
}

/* В payload: заголовок получает span, пометки тела на сервер не ходят. */
function loopPayloadArgs(step) {
    const a = step.args;
    const out = {span: loopBody(step).length};
    if (a.minutes != null) out.minutes = Number(a.minutes);
    else out.times = Number(a.times) || 1;
    if (a.pause_min != null && a.pause_max != null) {
        out.pause_min = Number(a.pause_min);
        out.pause_max = Math.max(Number(a.pause_min), Number(a.pause_max));
    }
    if (a.watch) out.watch = true;
    return out;
}

function loopMeasure(a) {
    if (a.minutes != null) return t('rec.povtor_minut', {n: recNum(a.minutes)});
    return t('rec.povtor_raz', {n: a.times, slovo: declOfNum(Number(a.times), t('rec.raz_formy').split('|'))});
}

function loopLabel(step) {
    return t('rec.povtoryat', {mera: loopMeasure(step.args)});
}

function loopCode(step) {
    const a = loopPayloadArgs(step);
    const parts = [a.times != null ? `times=${a.times}` : `minutes=${recNum(a.minutes)}`];
    if (a.pause_min != null) parts.push(`pause=(${recNum(a.pause_min)}, ${recNum(a.pause_max)})`);
    if (a.watch) parts.push('watch=True');
    return `for _ in ctx.loop(${parts.join(', ')}):`;
}

/* Классы строки списка: заголовок, тело, последняя строка тела — по ним
   CSS рисует рамку повтора прямо в списке. */
function loopRowClass(step) {
    if (loopIsHead(step)) return 'rs-loop';
    if (!step.inLoop) return '';
    const i = REC.steps.indexOf(step);
    const next = REC.steps[i + 1];
    return 'rs-in-loop' + (!next || next.inLoop !== step.inLoop ? ' rs-loop-end' : '');
}

/* Раскрытый шаг: у заголовка — настройки повтора, у обычного шага вне
   повтора — тихая ссылка «повторять по кругу». Так возможность находится там,
   где о ней думают: глядя на шаг, который хочется крутить. */
function recLoopEditor(step) {
    if (!loopIsHead(step)) {
        if (step.inLoop || step.kind === 'branch') return '';
        return `<div class="rs-loop-offer">
      <button class="sm ghost" onclick="recLoopWrap([${step.id}])">${recIcon('rotate')}${esc(t('rec.povtoryat_etot_shag'))}</button>
    </div>`;
    }
    const a = step.args;
    const byTime = a.minutes != null;
    return `<div class="loop-ed">
      <div class="loop-ed-row">
        <span class="loop-ed-k">${esc(t('rec.skolko'))}</span>
        <input type="number" class="loop-ed-n" min="1" step="1" aria-label="${esc(t('rec.skolko'))}"
               value="${byTime ? recNum(a.minutes) : a.times}"
               onchange="recLoopSet(${step.id}, 'amount', this.value)">
        <div class="chips" role="group">
          <button class="chip ${byTime ? '' : 'on'}" aria-pressed="${!byTime}"
                  onclick="recLoopSet(${step.id}, 'unit', 'times')">${esc(t('rec.raz'))}</button>
          <button class="chip ${byTime ? 'on' : ''}" aria-pressed="${byTime}"
                  onclick="recLoopSet(${step.id}, 'unit', 'minutes')">${esc(t('rec.minut'))}</button>
        </div>
      </div>
      <div class="loop-ed-row">
        <span class="loop-ed-k">${esc(t('rec.pauza_mezhdu_krugami'))}</span>
        <input type="number" min="0" step="0.5" value="${recNum(a.pause_min ?? 0)}" aria-label="${esc(t('rec.ot'))}"
               onchange="recLoopSet(${step.id}, 'pause_min', this.value)">
        <span>–</span>
        <input type="number" min="0" step="0.5" value="${recNum(a.pause_max ?? 0)}" aria-label="${esc(t('rec.do'))}"
               onchange="recLoopSet(${step.id}, 'pause_max', this.value)">
        <span class="dim">${esc(t('rec.sek_sluchayno'))}</span>
      </div>
      <label class="kb" title="${esc(t('rec.storozh_podskazka'))}">
        <input type="checkbox" ${a.watch ? 'checked' : ''} style="accent-color:var(--accent)"
               onchange="recLoopSet(${step.id}, 'watch', this.checked)">
        ${esc(t('rec.storozh'))}</label>
      <div class="loop-ed-row">
        <span class="dim">${esc(t('rec.v_povtore_shagov', {n: loopBody(step).length}))}</span>
        <span class="sp"></span>
        <button class="sm ghost" onclick="recLoopUnwrap(${step.id})">${esc(t('rec.ubrat_povtor'))}</button>
      </div>
    </div>`;
}

function recLoopSet(id, field, value) {
    const step = recFind(id);
    if (!loopIsHead(step)) return;
    const a = step.args;
    if (field === 'unit') {
        if (value === 'minutes' && a.minutes == null) {
            a.minutes = 10;
            delete a.times;
        } else if (value === 'times' && a.times == null) {
            a.times = 10;
            delete a.minutes;
        }
    } else if (field === 'amount') {
        const n = Math.max(1, Number(value) || 1);
        if (a.minutes != null) a.minutes = n;
        else a.times = Math.round(n);
    } else if (field === 'watch') {
        a.watch = !!value;
    } else {
        a[field] = Math.max(0, Number(value) || 0);
        if (a.pause_min > (a.pause_max ?? 0)) a.pause_max = a.pause_min;
    }
    recRender();
    recSave();
}

/* Обернуть шаги в повтор. Берётся отрезок от первого до последнего из
   выбранных: тело повтора идёт подряд, дырок в нём быть не может. */
function recLoopWrap(ids) {
    const idx = ids.map(id => REC.steps.findIndex(s => s.id === id)).filter(i => i >= 0);
    if (!idx.length) return;
    const from = Math.min(...idx), to = Math.max(...idx);
    const span = REC.steps.slice(from, to + 1);
    if (span.some(s => loopIsHead(s) || s.inLoop)) {
        toast(t('rec.uzhe_v_povtore'), 'bad');
        return;
    }
    const head = {id: REC.nextId++, kind: 'loop', args: Object.assign({}, LOOP_DEFAULT),
        param: null, note: '', warn: ''};
    span.forEach(s => { s.inLoop = head.id; });
    REC.steps.splice(from, 0, head);
    REC.open = head.id;
    if (REC.sel) REC.sel.clear();
    recRender();
    recSave();
    toast(recFirstHint('loop', t('rec.povtor_dobavlen_dlinno'), t('rec.povtor_dobavlen')));
}

function recSelLoop() {
    recLoopWrap(REC.steps.filter(s => REC.sel.has(s.id)).map(s => s.id));
}

/* «Убрать повтор»: шаги остаются, рамка уходит. */
function recLoopUnwrap(id) {
    REC.steps.forEach(s => { if (s.inLoop === id) s.inLoop = null; });
    REC.steps = REC.steps.filter(s => s.id !== id);
    if (REC.open === id) REC.open = null;
    recRender();
    recSave();
}

/* Куда попал переставленный шаг. Между двумя шагами одного повтора (или
   сразу за заголовком) — в повторе. На нижней границе рамки решает
   направление: пришёл снизу (стрелкой вверх, бросили на строку повтора) —
   вошёл, ушёл вниз из тела — вышел. Иначе — вне повтора. */
function loopPlace(step, enter) {
    if (loopIsHead(step)) return;
    const i = REC.steps.indexOf(step);
    const prev = REC.steps[i - 1], next = REC.steps[i + 1];
    const atPrev = prev ? (loopIsHead(prev) ? prev.id : prev.inLoop) : null;
    const atNext = next ? next.inLoop : null;
    step.inLoop = atPrev && (atPrev === atNext || enter) ? atPrev : null;
}

/* Перестановка повтора двигает его целиком: заголовок без тела ничего не
   значит, а тело без заголовка — уже не повтор. */
function loopBlock(step) {
    return loopIsHead(step) ? [step, ...loopBody(step)] : [step];
}

/* Дубль заголовка — дубль всего повтора (рамка с копиями шагов). */
const loopOrigDup = window.recDup;
window.recDup = function (id) {
    const head = recFind(id);
    if (!loopIsHead(head)) return loopOrigDup.apply(this, arguments);
    const block = loopBlock(head);
    const copyHead = stCopyOf(head);
    const copies = [copyHead, ...block.slice(1).map(s => Object.assign(stCopyOf(s), {inLoop: copyHead.id}))];
    const at = REC.steps.indexOf(block[block.length - 1]);
    REC.steps.splice(at + 1, 0, ...copies);
    REC.open = copyHead.id;
    recRender();
    recSave();
};

/* ------------------------------------------------------------------ схема */

const GR_LOOP_INDENT = 26;   // тело повтора на схеме — со сдвигом вправо
const GR_LOOP_PAD = 10;

/* Рамки повторов на схеме: прямоугольник вокруг заголовка и тела, подпись
   «↻ 10 раз» и стрелка «назад, к началу круга» справа — повтор читается
   как петля, а не как ещё одна карточка в столбике. */
function grLoopFrames(layout) {
    const parts = [];
    REC.steps.filter(loopIsHead).forEach(head => {
        const block = loopBlock(head);
        const boxes = block.map(s => layout.pos.get(s.id)).filter(Boolean);
        if (!boxes.length) return;
        const x1 = Math.min(...boxes.map(b => b.x)) - GR_LOOP_PAD;
        const y1 = Math.min(...boxes.map(b => b.y)) - GR_LOOP_PAD;
        const x2 = Math.max(...boxes.map(b => b.x)) + layout.nodeW + GR_LOOP_PAD;
        const y2 = Math.max(...boxes.map(b => b.y)) + GR_NODE_H + GR_LOOP_PAD;
        const last = layout.pos.get(block[block.length - 1].id);
        const first = layout.pos.get(block[Math.min(1, block.length - 1)].id);
        const ax = x2 + 14;
        parts.push(`<rect class="gr-loop-box" x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" rx="12"/>`);
        parts.push(`<path class="gr-loop-back" d="M${last.x + layout.nodeW},${last.y + GR_NODE_H / 2}
            C${ax},${last.y + GR_NODE_H / 2} ${ax},${first.y + GR_NODE_H / 2} ${first.x + layout.nodeW},${first.y + GR_NODE_H / 2}"
            marker-end="url(#grLoopArrow)"/>`);
    });
    if (!parts.length) return '';
    return `<defs><marker id="grLoopArrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L8,4 L0,8 z" class="gr-loop-arrow"/></marker></defs>${parts.join('')}`;
}
