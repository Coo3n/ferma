'use strict';

/* «Окна-помехи»: что ферма делает сама, когда сценарию мешает окно.

   Правило — «окно → чем узнаём → что делаем»: нажать кнопку на нём,
   нажать «Назад» или запустить свою команду. Правила лежат на сервере по
   приложениям (guards/<пакет>.json) или для всех (global.json) и
   срабатывают в любом сценарии этого приложения, когда шаг не нашёл свою
   кнопку. Так и складывается «граф» обходов: окно → команда.

   Раньше панель показывала только правила-«отводы» (запуск блока),
   простые «нажать «Не сейчас»» и «Назад» были не видны, новое правило
   рождалось только после падения, а удалить его было нельзя. */

const POP = {};   // открытое окно «Научить новое окно»

function popSelArgs(dict) {
    return Object.entries(dict || {}).map(([k, v]) => `${k}=${typeof v === 'number' ? v : JSON.stringify(String(v))}`).join(', ');
}

/* Признак словами для человека: «Разрешить», а не textMatches «(?i)Разрешить»;
   «элемент permission allow button», а не resourceId. */
function popWhat(dict) {
    const clean = v => String(v).replace(/\(\?i\)/g, '').replace(/\.\*/g, ' … ').replace(/[\^$\\]/g, '')
        .replace(/\|/g, ' / ').replace(/\s+/g, ' ').trim();
    for (const k of ['text', 'textContains', 'textMatches', 'description', 'descriptionContains', 'descriptionMatches']) {
        if (dict && dict[k] != null) return `«${clean(dict[k])}»`;
    }
    const id = dict && (dict.resourceId || dict.resourceIdMatches);
    if (id) return t('pop.element', {name: clean(String(id).split('/').pop()).replace(/_/g, ' ')});
    return recFeatText(popSelArgs(dict));
}

function popWhenText(rule) {
    const first = ((rule.when && rule.when.any) || [])[0];
    return first ? popWhat(first) : '';
}

function popActionText(action, rule) {
    if (!action) return '';
    const first = rule && ((rule.when && rule.when.any) || [])[0];
    if (action.click && first && popWhat(first) === popWhat(action.click)) return t('pop.nazhat_eyo_kratko');
    if (action.click) return t('pop.nazhat', {what: popWhat(action.click)});
    if (action.key) return action.key === 'back' ? t('pop.nazad') : action.key === 'home' ? t('pop.domoy')
        : t('pop.klavisha', {k: action.key});
    if (action.run) return t('pop.zapustit', {name: recScenName(action.run)});
    return '';
}

/* Подвал конструктора: правила этого приложения и всех + встреченные, но не
   разобранные окна. Вызывается из recSchemeSideLoad вместо старой разметки. */
function popSideHtml(карта, package_) {
    const rules = карта.rules || [];
    const gaps = карта.obstacles || [];
    const ruleRow = r => `<li class="pop-rule">
        <span class="pop-if">${esc(t('pop.esli_vidno'))}</span>
        <span class="pop-when" title="${esc(JSON.stringify(r.when))}">${esc(popWhenText(r) || r.name)}</span>
        <svg class="ic pop-arrow" aria-hidden="true"><use href="#i-right"/></svg>
        <span class="pop-act">${esc(popActionText(r.action, r))}</span>
        <span class="pop-where">${esc(r.source === 'global' ? t('pop.vse_prilozheniya') : recApp(r.source).replace(/[«»]/g, ''))}</span>
        <button type="button" class="pop-x" title="${esc(t('pop.udalit'))}" aria-label="${esc(t('pop.udalit'))}"
          onclick="popDelete(this, ${esc(JSON.stringify(r.name))}, '${esc(r.source === 'global' ? '' : r.source)}')">${recIcon('x')}</button>
      </li>`;
    const gapRow = o => {
        const {title, hint} = schObstacleLabel(o);
        return `<li class="pop-gap">
          <svg class="ic" aria-hidden="true"><use href="#i-alert"/></svg>
          <span class="pop-gap-tx"><b>${esc(title)}</b>${hint ? `<small>${esc(hint)}</small>` : ''}</span>
          <span class="pop-hits">${esc(t('pop.vstrech', {n: o.hits}))}</span>
          <button class="sm" onclick="teachDetour('${esc(o.job || '')}', '${esc(o.file || '')}')" ${o.job ? '' : 'disabled'}>${esc(t('pop.nauchit'))}</button>
        </li>`;
    };
    return `<div class="pop">
      <div class="pop-head">
        <p>${esc(t('pop.ob_etom'))}</p>
        <button type="button" class="sm primary" onclick="popNew('${esc(package_ || '')}')">${recIcon('plus')}${esc(t('pop.novoe'))}</button>
      </div>
      ${rules.length ? `<ol class="pop-rules">${rules.map(ruleRow).join('')}</ol>`
        : `<p class="pop-empty">${esc(t('pop.pusto'))}</p>`}
      ${gaps.length ? `<h5 class="pop-sub">${esc(t('pop.vstrechalis'))}</h5><ul class="pop-gaps">${gaps.map(gapRow).join('')}</ul>` : ''}
    </div>`;
}

async function popDelete(btn, name, package_) {
    if (!armConfirm(btn, t('pop.udalit_tochno'))) return;
    try {
        await api(`/api/detours/rules?name=${encodeURIComponent(name)}&package=${encodeURIComponent(package_)}`, {method: 'DELETE'});
        toast(t('pop.udaleno'), 'ok');
        if (window.recSchemeSideLoad) recSchemeSideLoad();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* ------------------------------------------- «Научить новое окно» */

async function popNew(package_) {
    if (!S.active) return toast(t('how.net_telefona'), 'bad');
    Object.assign(POP, {package: package_, node: null, sel: null, act: 'click', run: '', scope: 'app'});
    $('mTitle').textContent = t('pop.novoe');
    $('mBody').innerHTML = '<div class="rp-skel" aria-busy="true"><div class="rp-skel-line"></div><div class="rp-skel-shot"></div></div>';
    $('mActs').innerHTML = `<span class="sp"></span><button class="sm" onclick="closeModal()">${esc(t('rec.otmena'))}</button>`;
    modalSheet('wide');
    openModal();
    try {
        POP.dump = await api(`/api/devices/${encodeURIComponent(S.active)}/inspect`);
    } catch (e) {
        $('mBody').innerHTML = `<p class="dim">${esc(t('how.ekran_ne_prishel', {error: e.message}))}</p>`;
        return;
    }
    POP.list = repairNodes(POP.dump);
    const boxes = POP.list.map((node, i) => {
        const [x1, y1, x2, y2] = node.bounds;
        return `<div class="rp-box" data-i="${i}" style="left:${x1 * 100}%;top:${y1 * 100}%;width:${(x2 - x1) * 100}%;height:${(y2 - y1) * 100}%"></div>`;
    }).join('');
    $('mBody').innerHTML = `<p class="how-note">${esc(t('pop.otkroyte'))}</p>
      <div class="how-pick">
        <div class="rp-stage" id="popStage">
          <img class="rp-shot" id="popShot" alt="" draggable="false" src="${esc(POP.dump.screenshot)}">
          <div class="rp-layer" id="popLayer">${boxes}</div>
        </div>
        <div class="how-side" id="popSide"></div>
      </div>`;
    $('mActs').innerHTML = `<button class="sm ghost" onclick="popNew('${esc(package_ || '')}')">${recIcon('refresh')}${esc(t('pop.snyat_zanovo'))}</button>
      <span class="sp"></span><button class="sm" onclick="closeModal()">${esc(t('rec.otmena'))}</button>
      <button class="primary" id="popSave" onclick="popSave()">${esc(t('pop.sohranit'))}</button>`;
    const stage = $('popStage');
    stage.addEventListener('click', ev => popPointer(ev, false));
    stage.addEventListener('mousemove', ev => popPointer(ev, true));
    popSide();
}

function popPointer(ev, hover) {
    const rect = $('popShot').getBoundingClientRect();
    if (!rect.width) return;
    const x = (ev.clientX - rect.left) / rect.width, y = (ev.clientY - rect.top) / rect.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    const hit = recHit(x, y, POP.dump);
    const node = hit ? POP.dump.nodes[hit.target] : null;
    const i = node ? POP.list.indexOf(node) : -1;
    document.querySelectorAll(`#popLayer .rp-box.${hover ? 'hov' : 'on'}`).forEach(b => b.classList.remove(hover ? 'hov' : 'on'));
    const box = i >= 0 && document.querySelector(`#popLayer .rp-box[data-i="${i}"]`);
    if (box) box.classList.add(hover ? 'hov' : 'on');
    if (hover) return;
    POP.node = node;
    const sels = popCands(node);
    POP.sel = sels.length ? sels[0].args : null;
    popSide();
}

function popCands(node) {
    if (!node) return [];
    const shaky = s => s.fragile || s.dynamic || /(?:^|,\s*)(?:index|instance)=/.test(s.args);
    return (node.selectors || []).filter(s => s.call === 'click' && !s.oversized && !shaky(s));
}

function popSide() {
    const box = $('popSide');
    if (!box) return;
    /* Команды первыми — короткие действия как раз для обхода окна. */
    const cmds = (S.scenarios || []).filter(s => s.command || (s.editable && !s.template))
        .sort((a, b) => (b.command ? 1 : 0) - (a.command ? 1 : 0));
    const sels = popCands(POP.node);
    const pkg = POP.node && POP.node.package;
    const step1 = !POP.node ? `<p class="how-h">${esc(t('pop.tknite'))}</p>`
        : !sels.length ? `<p class="how-h">${esc(t('how.nenadezhno'))}</p>`
        : `<p class="how-h"><b>1.</b> ${esc(t('pop.uznavat_po'))}</p>
           <div class="how-cands">${sels.slice(0, 4).map(s => `<button type="button" class="how-cand ${s.args === POP.sel ? 'on' : ''}"
              data-args="${esc(s.args)}" onclick="POP.sel=this.dataset.args;popSide()"><span>${esc(recFeatText(s.args))}</span></button>`).join('')}</div>`;
    const radio = (name, value, cur, label, extra = '') => `<label class="pop-opt"><input type="radio" name="${name}" value="${value}"
        ${cur === value ? 'checked' : ''} onchange="POP.${name}=this.value;popSide()">${label}${extra}</label>`;
    const step2 = POP.sel ? `<p class="how-h"><b>2.</b> ${esc(t('pop.chto_delat'))}</p>
        ${radio('act', 'click', POP.act, esc(t('pop.nazhat_eyo')))}
        ${radio('act', 'back', POP.act, esc(t('pop.nazad')))}
        ${cmds.length ? radio('act', 'run', POP.act, esc(t('pop.komanda')), ` <select onchange="POP.run=this.value" ${POP.act === 'run' ? '' : 'disabled'}>
            ${cmds.map(c => `<option value="${esc(c.key)}" ${POP.run === c.key ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select>`) : ''}
        <p class="how-h"><b>3.</b> ${esc(t('pop.gde'))}</p>
        ${radio('scope', 'app', POP.scope, esc(t('pop.tolko_v', {app: pkg ? recApp(pkg).replace(/[«»]/g, '') : '—'})))}
        ${radio('scope', 'all', POP.scope, esc(t('pop.vse_prilozheniya')))}` : '';
    if (POP.act === 'run' && !POP.run && cmds.length) POP.run = cmds[0].key;
    box.innerHTML = step1 + step2;
    disableWithReason($('popSave'), !POP.sel, t('pop.snachala_tknite'));
}

async function popSave() {
    const when = repairParseSel(POP.sel);
    if (!when) return;
    const action = POP.act === 'back' ? {key: 'back'} : POP.act === 'run' ? {run: POP.run} : {click: when};
    const pkg = POP.scope === 'all' ? '' : ((POP.node && POP.node.package) || POP.package || '');
    try {
        const r = await post('/api/detours/rules', {package: pkg, name: recNodeLabel(POP.node) || t('pop.okno'), when: [when], action});
        closeModal();
        toast(t('pop.sohraneno', {name: r.name}), 'ok');
        if (window.recSchemeSideLoad) recSchemeSideLoad();
    } catch (e) {
        toast(e.message, 'bad');
    }
}
