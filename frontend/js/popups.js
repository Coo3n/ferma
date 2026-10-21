'use strict';

/* «Окна-помехи»: что ферма делает сама, когда шагу мешает окно.

   Правило — «окно → что делаем»: нажать кнопку на нём, «Назад» или
   запустить свою команду. Правила лежат на сервере по приложениям
   (guards/<пакет>.json) или для всех (global.json); в каждом сценарии
   приложения они срабатывают, когда шаг не нашёл свою кнопку. Для
   отдельного сценария их можно выключить (guards/scenarios_off.json).

   Где видно: подвал конструктора (popSideHtml), страница сценария
   (popScenarioLoad), карточка «ждёт решения» («Это мешающее окно»). */

const POP = {edit: null};

/* ------------------------------------------------ слова для человека */

function popSelArgs(dict) {
    return Object.entries(dict || {}).map(([k, v]) => `${k}=${typeof v === 'number' ? v : JSON.stringify(String(v))}`).join(', ');
}

function popWhat(dict) {
    return `«${vpFriendly(popSelArgs(dict)).value}»`;
}

function popWhenText(rule) {
    const first = ((rule.when && rule.when.any) || [])[0];
    return first ? popWhat(first) : rule.name;
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

function popWhere(rule) {
    return rule.source === 'global' ? t('pop.vse_prilozheniya') : recApp(rule.source).replace(/[«»]/g, '');
}

function popActKind(action) {
    return !action ? 'click' : action.key ? 'back' : action.run ? 'run' : 'click';
}

/* Команды и сценарии, которые можно запустить на окне: команды первыми. */
function popRunnable() {
    return (S.scenarios || []).filter(s => s.command || (s.editable && !s.template))
        .sort((a, b) => (b.command ? 1 : 0) - (a.command ? 1 : 0));
}

/* ------------------------------------------------------ строка правила */

function popRuleRow(r) {
    const id = `${r.source}\u0000${r.name}`;
    const editing = POP.edit === id;
    /* Нет снимка (правило из коробки или старое) — макет кнопки с её
       надписью: узнаётся глазом так же, как вырезка, а не одинаковый значок. */
    const word = popWhenText(r).replace(/[«»]/g, '');
    const thumb = r.img ? `<img class="pop-thumb" src="${esc(r.img)}" alt="">`
        : `<span class="pop-thumb mock" aria-hidden="true"><span>${esc(word)}</span></span>`;
    return `<li class="pop-rule ${editing ? 'editing' : ''}">
      <div class="pop-line">
        ${thumb}
        <span class="pop-tx">
          <span class="pop-when">${esc(popWhenText(r))}</span>
          <span class="pop-act">${recIcon('right')}${esc(popActionText(r.action, r))}</span>
        </span>
        <span class="pop-where">${esc(popWhere(r))}</span>
        <button type="button" class="pop-ic" title="${esc(t('pop.izmenit'))}" aria-label="${esc(t('pop.izmenit'))}"
          onclick="popEditToggle(${esc(JSON.stringify(id))})">${recIcon('pencil')}</button>
        <button type="button" class="pop-ic danger" title="${esc(t('pop.udalit'))}" aria-label="${esc(t('pop.udalit'))}"
          onclick="popDelete(this, ${esc(JSON.stringify(r.name))}, '${esc(r.source === 'global' ? '' : r.source)}')">${recIcon('x')}</button>
      </div>
      ${editing ? popEditHtml(r) : ''}
    </li>`;
}

/* Правка на месте: что делать и где — те же переключатели, что при
   обучении, без второго окна. */
function popEditHtml(r) {
    const kind = POP.editAct || popActKind(r.action);
    const run = POP.editRun || (r.action && r.action.run) || '';
    const scope = POP.editScope || (r.source === 'global' ? 'all' : 'app');
    const pkg = r.source === 'global' ? (POP.lastPkg || '') : r.source;
    const pkgArg = r.source === 'global' ? '' : r.source;
    return `<div class="pop-edit">
      ${popActSeg(kind, run, 'POP.editAct', 'POP.editRun', 'popRerender()')}
      ${popScopeSeg(scope, pkg, 'POP.editScope', 'popRerender()')}
      <div class="pop-edit-acts"><button class="sm" onclick="popEditToggle(null)">${esc(t('rec.otmena'))}</button>
        <button class="sm primary" onclick="popEditSave(${esc(JSON.stringify(r.name))}, '${esc(pkgArg)}')">${esc(t('pop.sohranit_izm'))}</button></div>
    </div>`;
}

/* Переключатели «что делать» и «где» — одна разметка для обучения и правки. */
function popActSeg(kind, run, kindVar, runVar, after) {
    const cmds = popRunnable();
    const btn = (k, label) => `<button type="button" role="radio" aria-checked="${kind === k}"
        onclick="${kindVar}='${k}';${after}">${esc(label)}</button>`;
    return `<div class="pop-field"><span class="pop-lbl">${esc(t('pop.chto_delat'))}</span>
      <div class="pop-seg" role="radiogroup">${btn('click', t('pop.nazhat_eyo'))}${btn('back', t('pop.nazad_kratko'))}${cmds.length ? btn('run', t('pop.komanda')) : ''}</div>
      ${kind === 'run' && cmds.length ? `<select class="pop-run" onchange="${runVar}=this.value">${cmds.map(c =>
        `<option value="${esc(c.key)}" ${c.key === run ? 'selected' : ''}>${esc(c.name)}${c.command ? '' : ' · ' + esc(t('pop.stsenariy'))}</option>`).join('')}</select>` : ''}
    </div>`;
}

function popScopeSeg(scope, pkg, scopeVar, after) {
    const btn = (k, label) => `<button type="button" role="radio" aria-checked="${scope === k}"
        onclick="${scopeVar}='${k}';${after}">${esc(label)}</button>`;
    return `<div class="pop-field"><span class="pop-lbl">${esc(t('pop.gde'))}</span>
      <div class="pop-seg" role="radiogroup">${pkg ? btn('app', t('pop.tolko_v', {app: recApp(pkg).replace(/[«»]/g, '')})) : ''}${btn('all', t('pop.vse_prilozheniya'))}</div>
    </div>`;
}

function popEditToggle(id) {
    POP.edit = POP.edit === id ? null : id;
    POP.editAct = POP.editRun = POP.editScope = null;
    popRerender();
}

function popRerender() {
    if ($('vpSide') && $('modal').classList.contains('on')) vpRender();
    if (window.recSchemeSideLoad && $('recSide') && $('recSide').open) recSchemeSideLoad();
    if (POP.scenKey && $('scPopups') && !$('scPopups').hidden) popScenarioLoad(POP.scenKey);
}

async function popEditSave(name, package_) {
    const rule = (POP.rules || []).find(r => r.name === name && (r.source === 'global' ? '' : r.source) === package_);
    if (!rule) return;
    const kind = POP.editAct || popActKind(rule.action);
    const first = ((rule.when && rule.when.any) || [])[0];
    const run = POP.editRun || (rule.action && rule.action.run) || (popRunnable()[0] || {}).key;
    const action = kind === 'back' ? {key: 'back'} : kind === 'run' ? {run}
        : (rule.action && rule.action.click ? rule.action : {click: first});
    const scope = POP.editScope || (rule.source === 'global' ? 'all' : 'app');
    const to = scope === 'all' ? '' : (package_ || POP.lastPkg || '');
    try {
        await api('/api/detours/rules', {method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, package: package_, action, to_package: to})});
        POP.edit = null;
        toast(t('pop.izmeneno'), 'ok');
        popRerender();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

async function popDelete(btn, name, package_) {
    if (!armConfirm(btn, t('pop.udalit_tochno'))) return;
    try {
        await api(`/api/detours/rules?name=${encodeURIComponent(name)}&package=${encodeURIComponent(package_)}`, {method: 'DELETE'});
        toast(t('pop.udaleno'), 'ok');
        popRerender();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* ---------------------------------------- подсказка по встреченному окну */

/* Встреченное окно с кнопкой «Не сейчас / Позже / Закрыть…» — правило
   одним нажатием, без обучения. */
const POP_CLOSE_WORDS = /^(не сейчас|позже|закрыть|пропустить|отмена|нет,? спасибо|понятно|ок|ok|close|skip|not now|later|cancel|no,? thanks|got it|dismiss)$/i;

function popSuggest(o) {
    const word = (o.texts || []).find(x => POP_CLOSE_WORDS.test(String(x).trim()));
    return word ? String(word).trim() : '';
}

async function popQuickRule(package_, word) {
    try {
        await post('/api/detours/rules', {package: package_, name: word, when: [{text: word}], action: {click: {text: word}}});
        toast(t('pop.sohraneno', {name: word}), 'ok');
        popRerender();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* ------------------------------------------------------- подвал конструктора */

function popSideHtml(карта, package_) {
    POP.rules = карта.rules || [];
    POP.lastPkg = package_ || '';
    const gaps = карта.obstacles || [];
    POP.gaps = gaps;
    POP.gapIcon = `<span class="pop-thumb ic-only warn">${recIcon('alert')}</span>`;
    const gapRow = o => {
        const {title} = schObstacleLabel(o);
        const word = popSuggest(o);
        return `<li class="pop-rule pop-gap"><div class="pop-line">
          ${o.job ? `<img class="pop-thumb shot" alt="" loading="lazy" src="/api/jobs/${esc(o.job)}/artifacts/${encodeURIComponent(popGapShot(o))}"
              onerror="this.outerHTML=POP.gapIcon">` : POP.gapIcon}
          <span class="pop-tx"><span class="pop-when">${esc(title)}</span>
            <span class="pop-act dim">${esc(word ? t('pop.pohozhe', {word}) : t('pop.vstrech', {n: o.hits}))}</span></span>
          ${word ? `<button class="sm primary" onclick="popQuickRule('${esc(o.package || package_ || '')}', ${esc(JSON.stringify(word))})">${esc(t('pop.nazhimat_word', {word}))}</button>` : ''}
          <button class="sm" onclick="popTeachGap(${esc(JSON.stringify(gaps.indexOf(o)))})" ${o.job ? '' : 'disabled'}>${esc(t('pop.nauchit'))}</button>
        </div></li>`;
    };
    return `<div class="pop">
      <div class="pop-head">
        <div><b>${esc(t('pop.zagolovok'))}</b><p>${esc(t('pop.ob_etom'))}</p></div>
        <button type="button" class="sm primary" onclick="popNew('${esc(package_ || '')}')">${recIcon('plus')}${esc(t('pop.novoe'))}</button>
      </div>
      ${POP.rules.length ? `<ol class="pop-rules">${POP.rules.map(popRuleRow).join('')}</ol>`
        : `<p class="pop-empty">${esc(t('pop.pusto'))}</p>`}
      ${gaps.length ? `<h5 class="pop-sub">${esc(t('pop.vstrechalis'))}</h5><ul class="pop-rules">${gaps.map(gapRow).join('')}</ul>` : ''}
    </div>`;
}

/* ------------------------------------------------------- страница сценария */

async function popScenarioLoad(key) {
    const box = $('scPopups');
    if (!box) return;
    POP.scenKey = key;
    let info;
    try {
        info = await api('/api/detours/scenario/' + encodeURIComponent(key));
    } catch (e) {
        box.hidden = true;
        return;
    }
    if (POP.scenKey !== key) return;
    POP.rules = info.rules || [];
    POP.lastPkg = (info.packages || [])[0] || '';
    box.hidden = false;
    setHTML(box, `<div class="pop pop-scen">
      <div class="pop-head">
        <div><b>${esc(t('pop.zagolovok'))}</b>
          <p>${esc(info.off ? t('pop.vyklyucheny') : t('pop.v_etom', {n: POP.rules.length}))}</p></div>
        <button type="button" class="live-switch sm ${info.off ? '' : 'on'}" role="switch" aria-checked="${!info.off}"
          onclick="popScenarioToggle('${esc(key)}', ${!info.off})"><span class="sw" aria-hidden="true"></span>${esc(t('pop.zakryvat_sami'))}</button>
      </div>
      ${!info.off && POP.rules.length ? `<ol class="pop-rules">${POP.rules.map(popRuleRow).join('')}</ol>` : ''}
    </div>`);
    if (window.coachOnce) coachOnce('scenpop', 'scen');
}

async function popScenarioToggle(key, off) {
    try {
        await post('/api/detours/scenario/' + encodeURIComponent(key), {off});
        toast(off ? t('pop.vyklyucheny_toast') : t('pop.vklyucheny_toast'), 'ok');
        popScenarioLoad(key);
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* --------------------------------------------- «Научить новое окно» */

function popNew(package_, serial) {
    Object.assign(POP, {pkg: package_ || '', act: 'click', run: '', scope: 'app'});
    vpOpen({
        title: t('pop.novoe'),
        serial,
        mode: 'element',
        side: v => vpChoiceHtml(t('pop.uznavat_po')) + (v.choice ? `<div class="pop-form">
            ${popActSeg(POP.act, POP.run, 'POP.act', 'POP.run', 'vpRender()')}
            ${popScopeSeg(POP.scope, (v.node && v.node.package) || POP.pkg, 'POP.scope', 'vpRender()')}</div>` : ''),
        acts: v => `<span class="sp"></span><button class="sm" onclick="closeModal()">${esc(t('rec.otmena'))}</button>
            <button class="primary" onclick="popSave()" ${v.choice ? '' : 'disabled'}>${esc(t('pop.sohranit'))}</button>`,
    });
}

async function popSave() {
    const when = repairParseSel(VP.choice);
    if (!when) return;
    const run = POP.run || (popRunnable()[0] || {}).key;
    const action = POP.act === 'back' ? {key: 'back'} : POP.act === 'run' ? {run} : {click: when};
    const pkg = POP.scope === 'all' ? '' : ((VP.node && VP.node.package) || POP.pkg || '');
    const img = VP.node ? await vpCrop(VP.node, 1.2) : '';
    try {
        const r = await post('/api/detours/rules', {package: pkg, name: recNodeLabel(VP.node) || t('pop.okno'),
            when: [when], action, img});
        closeModal();
        toast(t('pop.sohraneno', {name: r.name}), 'ok');
        popRerender();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* ------------------------------------- «Научить» по встреченному окну */

/* Снимок того экрана из запуска, где он встретился: obstacle.json — кадр
   падения, obstacle_escaped_NN.json — кадр обхода вслепую с тем же номером. */
function popGapShot(o) {
    return /^obstacle_escaped_\d+\.json$/.test(o.file || '') ? o.file.replace('.json', '.jpg') : '99_failure.jpg';
}

async function popTeachGap(i) {
    const o = (POP.gaps || [])[i];
    if (!o || !o.job) return;
    let job = null;
    try {
        job = await api('/api/jobs/' + encodeURIComponent(o.job));
    } catch (e) { /* запуск могли удалить — снимка не будет, учить всё равно можно */ }
    const shot = popGapShot(o);   // файл берём прямо по имени: запуска в журнале может уже не быть
    const {title} = schObstacleLabel(o);
    const texts = (o.texts || []).slice(0, 8);
    POP.noShot = `${recIcon('image')}<p>${esc(t('pop.snimka_net'))}</p>`;
    $('mTitle').textContent = t('pop.okno_meshalo');
    $('mBody').innerHTML = `<div class="vp">
        <div class="vp-shot"><img class="pop-gap-shot" src="/api/jobs/${esc(o.job)}/artifacts/${encodeURIComponent(shot)}" alt=""
              onerror="this.replaceWith(Object.assign(document.createElement('div'), {className: 'vp-empty', innerHTML: POP.noShot}))"></div>
        <div class="vp-side">
          <div><b class="pop-gap-title">${esc(title)}</b>
            <p class="how-note">${esc(t('pop.vstrech', {n: o.hits}))}${job ? ' · ' + esc(job.device_name || '') : ''}</p></div>
          ${texts.length ? `<p class="vp-h">${esc(t('pop.na_ekrane_bylo'))}</p>
            <div class="pop-words">${texts.map(x => `<span>${esc(x)}</span>`).join('')}</div>` : ''}
          <p class="vp-h">${esc(t('pop.kak_nauchit'))}</p>
          <button type="button" class="pop-way" onclick="closeModal();popNew('${esc(o.package || '')}', ${job ? `'${esc(job.serial)}'` : 'undefined'})">
            ${recIcon('crosshair')}<span><b>${esc(t('pop.way_knopka_t'))}</b><small>${esc(t('pop.way_knopka'))}</small></span></button>
          <button type="button" class="pop-way" onclick="closeModal();teachDetour('${esc(o.job)}', '${esc(o.file || '')}')">
            ${recIcon('record')}<span><b>${esc(t('pop.way_kliki_t'))}</b><small>${esc(t('pop.way_kliki'))}</small></span></button>
          <button type="button" class="pop-way quiet" onclick="popIgnoreGap(${i})">
            ${recIcon('check')}<span><b>${esc(t('pop.way_ne_pomeha_t'))}</b><small>${esc(t('pop.way_ne_pomeha'))}</small></span></button>
        </div>
      </div>`;
    $('mActs').innerHTML = `<span class="sp"></span><button class="sm" onclick="closeModal()">${esc(t('rec.otmena'))}</button>`;
    modalSheet('wide');
    openModal();
}

async function popIgnoreGap(i) {
    const o = (POP.gaps || [])[i];
    if (!o) return;
    try {
        await post('/api/detours/obstacles/ignore', {job: o.job, file: o.file});
        closeModal();
        toast(t('pop.ubrano'), 'ok');
        popRerender();
    } catch (e) {
        toast(e.message, 'bad');
    }
}
