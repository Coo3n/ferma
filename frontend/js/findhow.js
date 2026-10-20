'use strict';

/* «Как нажимать» в раскрытом шаге нажатия — на виду, а не под «Дополнительно».

   Два режима одной кнопкой: «По кнопке» (ищет элемент: основной способ и
   запасные «или так», потом картинка и точка) и «В точку» (жмёт в
   координаты, ничего не ищет — когда у элемента нет ни текста, ни имени,
   или экран всегда одинаковый).

   Запасной способ добавляют, ткнув в кнопку на снимке экрана телефона, — а не
   вписывая resourceId руками: ферма сама предлагает, по чему эту кнопку можно
   узнать («по тексту «Нравится»», «по подписи «Like»», «по имени iv_likes»).
   Вписать вручную по-прежнему можно — в «Дополнительно». */

const HOW = {};   // открытый выбор на экране: {id, mode, dump, list, node}

function howIsTap(step) {
    return step.kind === 'tap';
}

/* Только для нажатий: клик по элементу и тап в точку. */
function recHowHtml(step) {
    if (step.kind !== 'click' && step.kind !== 'tap') return '';
    const tap = howIsTap(step);
    const seg = `<div class="how-mode" role="radiogroup" aria-label="${esc(t('how.kak_nazhimat'))}">
        <button type="button" role="radio" aria-checked="${!tap}" onclick="howMode(${step.id}, 'button')">
          ${recIcon('pointer')}${esc(t('how.po_knopke'))}</button>
        <button type="button" role="radio" aria-checked="${tap}" onclick="howMode(${step.id}, 'point')">
          ${recIcon('target')}${esc(t('how.v_tochku'))}</button>
      </div>`;
    return `<section class="how">
      <div class="how-head"><b>${esc(t('how.kak_nazhimat'))}</b>${seg}</div>
      ${tap ? howPointHtml(step) : howListHtml(step)}
    </section>`;
}

function howListHtml(step) {
    const main = step.selector ? step.selector.args : '';
    const alts = recFallbacks(step);
    const row = (args, i) => `<li class="${i === 0 ? 'main' : ''}">
        <span class="how-n">${i + 1}</span>
        <span class="how-feat" title="${esc(args)}">${esc(recFeatText(args))}</span>
        ${i === 0 ? `<span class="how-tag">${esc(t('how.osnovnoy'))}</span>`
            : `<button type="button" class="how-x" title="${esc(t('how.ubrat'))}" aria-label="${esc(t('how.ubrat'))}"
                onclick="recOrToggle(${step.id}, this.dataset.args, false)" data-args="${esc(args)}">${recIcon('x')}</button>`}
      </li>`;
    const full = alts.length >= REC_OR_MAX;
    const layers = recLayers(step);
    return `<p class="how-h">${esc(t('how.ishchet_po_poryadku'))}</p>
      <ol class="how-list">${[main, ...alts].filter(Boolean).map(row).join('')}</ol>
      <div class="how-add">
        <button type="button" class="sm" onclick="howPick(${step.id}, 'or')" ${full ? 'disabled' : ''}
          title="${esc(full ? t('rec.ili_maks', {n: REC_OR_MAX}) : t('how.ukazat_title'))}">
          ${recIcon('crosshair')}${esc(t('how.ukazat_variant'))}</button>
        <button type="button" class="sm ghost" onclick="howManual(${step.id})">${esc(t('how.vpisat'))}</button>
      </div>
      ${layers.length ? `<p class="how-last">${recIcon('check')}${esc(t('how.esli_nichego', {list: layers.join(', ')}))}</p>` : ''}`;
}

function howPointHtml(step) {
    const a = step.args || {};
    const ok = [a.x, a.y].every(v => typeof v === 'number' && v >= 0 && v <= 1);
    const where = ok ? recWhere({x: a.x, y: a.y}) : '';
    return `<div class="how-point">
        <span class="how-phone">${ok && window.scStepVisual ? scStepVisual(step, {}) : ''}</span>
        <div>
          <p class="how-h">${esc(ok ? t('how.zhmet_v', {where, x: recNum(a.x), y: recNum(a.y)}) : t('how.tochka_ne_zadana'))}</p>
          <p class="how-note">${esc(t('how.tochka_note'))}</p>
          <button type="button" class="sm" onclick="howPick(${step.id}, 'point')">${recIcon('crosshair')}${esc(t('how.ukazat_tochku'))}</button>
        </div>
      </div>`;
}

/* «Вписать вручную» — старая строка «или так» в «Дополнительно». */
function howManual(id) {
    const more = document.querySelector(`#recSteps .rs[data-id="${id}"] details.rs-more`);
    if (!more) return;
    more.open = true;
    const field = $('orVal' + id);
    if (field) {
        field.scrollIntoView({block: 'center', behavior: 'smooth'});
        field.focus({preventScroll: true});
    }
}

/* Переключение режима. Клик → точка: элемент прячется в _click (только в
   конструкторе, на сервер не уходит), чтобы вернуть «По кнопке» без
   перезаписи. Точка → клик: из запаса, а если запаса нет (шаг записан
   тапом) — указать кнопку на экране. */
function howMode(id, mode) {
    const step = recFind(id);
    if (!step) return;
    if (mode === 'point' && step.kind === 'click') {
        const p = step.point || (step.bounds ? recPoint(step.bounds) : null);
        step._click = {selector: step.selector, or: step.or, alts: step.alts, texts: step.texts, crop: step.crop,
            point: step.point, point_rel: step.point_rel, within: step.within, near: step.near,
            scroll: step.scroll, note: step.note, bounds: step.bounds};
        step.kind = 'tap';
        step.args = p ? {x: p[0], y: p[1]} : {};
        ['selector', 'or', 'alts', 'texts', 'crop', 'point', 'point_rel', 'within', 'near', 'scroll'].forEach(k => delete step[k]);
        recRender();
        recSave();
        if (!p) howPick(id, 'point');
        return;
    }
    if (mode === 'button' && step.kind === 'tap') {
        if (!step._click) return howPick(id, 'button');
        Object.assign(step, step._click, {kind: 'click', args: {}});
        delete step._click;
        recRender();
        recSave();
    }
}

/* ------------------------------------------------------- выбор на снимке */

async function howPick(id, mode) {
    if (!S.active) return toast(t('how.net_telefona'), 'bad');
    HOW.id = id;
    HOW.mode = mode;
    HOW.node = null;
    $('mTitle').textContent = mode === 'point' ? t('how.ukazat_tochku') : t('how.ukazat_knopku');
    $('mBody').innerHTML = '<div class="rp-skel" aria-busy="true"><div class="rp-skel-line"></div><div class="rp-skel-shot"></div></div>';
    $('mActs').innerHTML = `<span class="sp"></span><button class="sm" onclick="closeModal()">${esc(t('rec.otmena'))}</button>`;
    modalSheet('wide');
    openModal();
    let dump;
    try {
        dump = await api(`/api/devices/${encodeURIComponent(S.active)}/inspect`);
    } catch (e) {
        $('mBody').innerHTML = `<p class="dim">${esc(t('how.ekran_ne_prishel', {error: e.message}))}</p>`;
        return;
    }
    if (HOW.id !== id || !$('modal').classList.contains('on')) return;
    HOW.dump = dump;
    HOW.list = repairNodes(dump);
    const boxes = mode === 'point' ? '' : HOW.list.map((node, i) => {
        const [x1, y1, x2, y2] = node.bounds;
        return `<div class="rp-box" data-i="${i}" style="left:${x1 * 100}%;top:${y1 * 100}%;width:${(x2 - x1) * 100}%;height:${(y2 - y1) * 100}%"></div>`;
    }).join('');
    $('mBody').innerHTML = `<div class="how-pick">
        <div class="rp-stage" id="howStage">
          <img class="rp-shot" id="howShot" alt="" draggable="false" src="${esc(dump.screenshot)}">
          <div class="rp-layer" id="howLayer">${boxes}<i class="how-dot" id="howDot" hidden></i></div>
        </div>
        <div class="how-side" id="howSide">${howSideHtml()}</div>
      </div>`;
    const stage = $('howStage');
    stage.addEventListener('click', howPointer);
    stage.addEventListener('mousemove', ev => howPointer(ev, true));
}

function howSideHtml() {
    if (HOW.mode === 'point') {
        return HOW.point
            ? `<p class="how-h">${esc(t('how.zhmet_v', {where: recWhere({x: HOW.point[0], y: HOW.point[1]}),
                x: recNum(HOW.point[0]), y: recNum(HOW.point[1])}))}</p>
               <button class="primary" onclick="howApplyPoint()">${esc(t('how.gotovo'))}</button>`
            : `<p class="how-h">${esc(t('how.klik_tochka'))}</p>`;
    }
    if (!HOW.node) return `<p class="how-h">${esc(t('how.klik_knopka'))}</p>`;
    /* Надёжные — сверху; «2-й по счёту» и меняющиеся — ниже, с пометкой. */
    const shaky = s => s.fragile || s.dynamic || /(?:^|,\s*)(?:index|instance)=/.test(s.args);
    const sels = (HOW.node.selectors || []).filter(s => s.call === 'click' && !s.oversized)
        .sort((a, b) => shaky(a) - shaky(b));
    if (!sels.length) return `<p class="how-h">${esc(t('how.nenadezhno'))}</p>`;
    const step = recFind(HOW.id) || {};
    const have = new Set([step.selector && step.selector.args, ...recFallbacks(step)].filter(Boolean));
    return `<p class="how-h"><b>${esc(recNodeLabel(HOW.node) || t('how.element'))}</b></p>
      <p class="how-note">${esc(HOW.mode === 'button' ? t('how.vyberite_kak') : t('how.chem_uznat'))}</p>
      <div class="how-cands">${sels.slice(0, 6).map(s => {
        const known = have.has(s.args);
        const mark = shaky(s) ? t('how.nenadezhnyy') : s.matches === 1 ? t('how.odin_na_ekrane')
            : s.matches > 1 ? t('how.takih_n', {n: s.matches}) : '';
        return `<button type="button" class="how-cand${shaky(s) ? ' shaky' : ''}" ${known ? 'disabled' : ''} data-args="${esc(s.args)}"
            onclick="howApplySel(this.dataset.args)">
            <span>${esc(recFeatText(s.args))}</span><small>${esc(known ? t('how.uzhe_est') : mark)}</small></button>`;
      }).join('')}</div>`;
}

function howPointer(ev, hover) {
    const rect = $('howShot').getBoundingClientRect();
    if (!rect.width) return;
    const x = (ev.clientX - rect.left) / rect.width, y = (ev.clientY - rect.top) / rect.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    if (HOW.mode === 'point') {
        if (hover) return;
        HOW.point = [Math.round(x * 1000) / 1000, Math.round(y * 1000) / 1000];
        const dot = $('howDot');
        dot.hidden = false;
        dot.style.left = x * 100 + '%';
        dot.style.top = y * 100 + '%';
        $('howSide').innerHTML = howSideHtml();
        return;
    }
    const hit = recHit(x, y, HOW.dump);
    const node = hit ? HOW.dump.nodes[hit.target] : null;
    const i = node ? HOW.list.indexOf(node) : -1;
    document.querySelectorAll('#howLayer .rp-box.hov, #howLayer .rp-box.on').forEach(b => {
        if (hover) b.classList.remove('hov'); else b.classList.remove('on', 'hov');
    });
    const box = i >= 0 && document.querySelector(`#howLayer .rp-box[data-i="${i}"]`);
    if (box) box.classList.add(hover ? 'hov' : 'on');
    if (hover) return;
    HOW.node = node;
    HOW.at = [x, y];
    $('howSide').innerHTML = howSideHtml();
}

function howApplySel(args) {
    const step = recFind(HOW.id);
    if (!step || !HOW.node) return;
    if (HOW.mode === 'button') {
        /* Тап → клик по выбранному элементу, этим способом основным. */
        const built = recBuildClickStep(HOW.node, HOW.dump, HOW.at);
        const chosen = (HOW.node.selectors || []).find(s => s.args === args) || built.selector;
        Object.assign(step, built, {kind: 'click', args: {}, selector: {call: 'click', args: chosen.args}});
        delete step.shot;
        delete step._click;
    } else {
        if (step.selector && step.selector.args === args) return;
        step.or = [...recFallbacks(step).filter(a => a !== args), args].slice(0, REC_OR_MAX);
    }
    closeModal();
    recRender();
    recSave();
    toast(HOW.mode === 'button' ? t('how.teper_po_knopke') : t('how.variant_dobavlen'), 'ok');
}

function howApplyPoint() {
    const step = recFind(HOW.id);
    if (!step || !HOW.point) return;
    if (step.kind === 'click') howMode(step.id, 'point');
    step.args = {x: HOW.point[0], y: HOW.point[1]};
    closeModal();
    recRender();
    recSave();
}
