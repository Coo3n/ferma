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
    if (window.coachOnce) setTimeout(() => document.querySelector('#recSteps .how') && coachOnce('how'), 0);
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

/* mode: 'or' — ещё один способ найти кнопку шага; 'button' — тап становится
   нажатием по кнопке; 'point' — точка для «В точку». */
function howPick(id, mode) {
    const step = recFind(id) || {};
    vpOpen({
        title: mode === 'point' ? t('how.ukazat_tochku') : t('how.ukazat_knopku'),
        mode: mode === 'point' ? 'point' : 'element',
        have: mode === 'or' ? [step.selector && step.selector.args, ...recFallbacks(step)].filter(Boolean) : [],
        side: v => mode === 'point'
            ? (v.point ? `<p class="vp-h">${esc(t('how.zhmet_v', {where: recWhere({x: v.point[0], y: v.point[1]}),
                x: recNum(v.point[0]), y: recNum(v.point[1])}))}</p>` : `<div class="vp-empty">${recIcon('target')}<p>${esc(t('how.klik_tochka'))}</p></div>`)
            : vpChoiceHtml(mode === 'button' ? t('how.vyberite_kak') : t('how.chem_uznat')),
        acts: v => `<span class="sp"></span><button class="sm" onclick="closeModal()">${esc(t('rec.otmena'))}</button>
            <button class="primary" id="vpGo" onclick="howApply(${id}, '${mode}')"
              ${(mode === 'point' ? v.point : v.choice) ? '' : 'disabled'}>${esc(mode === 'or' ? t('how.dobavit') : t('how.gotovo'))}</button>`,
    });
}

function howApply(id, mode) {
    const step = recFind(id);
    if (!step) return closeModal();
    if (mode === 'point') {
        if (!VP.point) return;
        if (step.kind === 'click') howMode(id, 'point');
        step.args = {x: VP.point[0], y: VP.point[1]};
    } else if (mode === 'button') {
        if (!VP.node || !VP.choice) return;
        const built = recBuildClickStep(VP.node, VP.dump, VP.at);
        Object.assign(step, built, {kind: 'click', args: {}, selector: {call: 'click', args: VP.choice}});
        delete step.shot;
        delete step._click;
    } else {
        if (!VP.choice || (step.selector && step.selector.args === VP.choice)) return;
        step.or = [...recFallbacks(step).filter(a => a !== VP.choice), VP.choice].slice(0, REC_OR_MAX);
    }
    closeModal();
    recRender();
    recSave();
    toast(mode === 'or' ? t('how.variant_dobavlen') : mode === 'button' ? t('how.teper_po_knopke') : t('how.tochka_zadana'), 'ok');
}
