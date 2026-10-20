'use strict';

/* Выбор на снимке экрана телефона — общий для «Указать на экране» (шаг) и
   «Научить новое окно» (правило окна).

   Человек не должен видеть «resourceId» и «textMatches»: он видит вырезку
   кнопки, которую выбрал, и способы её узнать простыми словами — «по
   надписи «Подписаться»». Наведение на способ подсвечивает на снимке всё,
   что ферма этим способом найдёт: одно место — хорошо, три — может нажать
   не то. Лучший способ выбран сразу, так что чаще всего достаточно одного
   клика по кнопке и «Добавить». */

const VP = {};

/* ------------------------------------------------ чистая логика (тесты) */

/* Ключ=значение из строки способа: text="Войти", instance=1. */
function vpParse(args) {
    const out = {};
    String(args || '').replace(/(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|(-?\d+))/g, (m, k, q, n) => {
        out[k] = q != null ? q.replace(/\\(.)/g, '$1') : Number(n);
        return m;
    });
    return out;
}

/* Какие узлы снимка подходят под способ — чтобы показать «найдёт N мест». */
function vpMatches(nodes, args) {
    const sel = vpParse(args);
    const test = (n) => Object.entries(sel).every(([k, v]) => {
        if (k === 'instance' || k === 'index') return true;
        const val = k.startsWith('text') ? n.text : k.startsWith('description') ? n.description
            : k.startsWith('resourceId') ? n.resourceId : k === 'className' ? n.class : null;
        if (val == null) return false;
        if (k.endsWith('Contains')) return String(val).includes(v);
        if (k.endsWith('Matches')) {
            try { return new RegExp('^(?:' + String(v).replace(/^\(\?i\)/, '') + ')$', /^\(\?i\)/.test(v) ? 'i' : '').test(val); }
            catch (e) { return false; }
        }
        return String(val) === String(v);
    });
    const hits = (nodes || []).filter(test);
    const nth = sel.instance != null ? sel.instance : sel.index;
    return nth != null && hits[nth] ? [hits[nth]] : hits;
}

function vpShaky(s) {
    return !!(s.fragile || s.dynamic || /(?:^|,\s*)(?:index|instance)=/.test(s.args));
}

/* Способ словами: заголовок, значение и значок. Ключи строк — литералами. */
function vpFriendly(args) {
    const sel = vpParse(args);
    const nth = sel.instance != null ? sel.instance : sel.index;
    const tail = nth != null ? ' · ' + t('vp.po_schetu', {n: nth + 1}) : '';
    const v = x => String(x).replace(/\(\?i\)/g, '').replace(/\.\*/g, '').replace(/[\^$\\()]/g, '')
        .replace(/\|/g, ' / ').replace(/\s+/g, ' ').trim();
    if (sel.text != null) return {icon: 'text-input', title: t('vp.po_nadpisi'), value: v(sel.text) + tail};
    if (sel.textContains != null) return {icon: 'text-input', title: t('vp.po_chasti_nadpisi'), value: v(sel.textContains) + tail};
    if (sel.textMatches != null) return {icon: 'text-input', title: t('vp.po_nadpisi'), value: v(sel.textMatches) + tail};
    if (sel.description != null || sel.descriptionContains != null) {
        return {icon: 'eye', title: t('vp.po_skrytoy'), value: v(sel.description ?? sel.descriptionContains) + tail};
    }
    const id = sel.resourceId ?? sel.resourceIdMatches;
    if (id != null) return {icon: 'tag', title: t('vp.po_imeni'), value: v(String(id).split('/').pop()).replace(/_/g, ' ') + tail};
    if (sel.className != null) return {icon: 'layers', title: t('vp.po_tipu'), value: String(sel.className).split('.').pop() + tail};
    return {icon: 'pointer', title: t('vp.sposob'), value: String(args)};
}

/* Способы для выбранного узла, лучший первым: один на экране и не «по
   счёту»; из равных — надпись (её видно глазами) раньше внутреннего имени. */
function vpOptions(node, nodes) {
    const rank = s => (vpShaky(s) ? 100 : 0) + (s.n === 1 ? 0 : 10)
        + (/^text/.test(s.args) ? 0 : /^description/.test(s.args) ? 1 : 2);
    return (node && node.selectors || [])
        .filter(s => s.call === 'click' && !s.oversized)
        .map(s => Object.assign({}, s, {n: vpMatches(nodes, s.args).length || s.matches || 0}))
        .sort((a, b) => rank(a) - rank(b));
}

/* ------------------------------------------------------------------ DOM */

/* opts: {title, intro, serial, mode: 'element'|'point', side(VP) → html,
          acts(VP) → html, ready(VP)} */
async function vpOpen(opts) {
    const serial = opts.serial || S.active;
    if (!serial) return toast(t('how.net_telefona'), 'bad');
    Object.assign(VP, {opts, serial, node: null, point: null, choice: null, dump: null, token: (VP.token || 0) + 1});
    const token = VP.token;
    $('mTitle').textContent = opts.title;
    $('mBody').innerHTML = '<div class="rp-skel" aria-busy="true"><div class="rp-skel-line"></div><div class="rp-skel-shot"></div></div>';
    $('mActs').innerHTML = `<span class="sp"></span><button class="sm" onclick="closeModal()">${esc(t('rec.otmena'))}</button>`;
    modalSheet('wide');
    if (!$('modal').classList.contains('on')) openModal();
    let dump;
    try {
        dump = await api(`/api/devices/${encodeURIComponent(serial)}/inspect`);
    } catch (e) {
        $('mBody').innerHTML = `<p class="vp-err">${esc(t('how.ekran_ne_prishel', {error: e.message}))}</p>`;
        $('mActs').innerHTML = `<span class="sp"></span><button class="sm" onclick="vpOpen(VP.opts)">${esc(t('pop.snyat_zanovo'))}</button>`;
        return;
    }
    if (token !== VP.token || !$('modal').classList.contains('on')) return;
    VP.dump = dump;
    VP.list = repairNodes(dump);
    $('mBody').innerHTML = `<div class="vp">
        <div class="vp-shot">
          <div class="rp-stage" id="vpStage">
            <img class="rp-shot" id="vpImg" alt="" draggable="false" src="${esc(dump.screenshot)}">
            <div class="rp-layer" id="vpLayer"><i class="how-dot" id="vpDot" hidden></i></div>
          </div>
          <button type="button" class="sm ghost vp-again" onclick="vpOpen(VP.opts)">${recIcon('refresh')}${esc(t('pop.snyat_zanovo'))}</button>
        </div>
        <div class="vp-side" id="vpSide"></div>
      </div>`;
    const stage = $('vpStage');
    stage.addEventListener('click', ev => vpPointer(ev, false));
    stage.addEventListener('mousemove', ev => vpPointer(ev, true));
    stage.addEventListener('mouseleave', () => vpMark('hov', []));
    vpRender();
}

function vpRender() {
    const side = $('vpSide');
    if (!side) return;
    side.innerHTML = VP.opts.side(VP);
    $('mActs').innerHTML = VP.opts.acts(VP);
    vpMark('pick', VP.choice ? vpMatches(VP.dump.nodes, VP.choice) : VP.node ? [VP.node] : []);
}

/* Рамки поверх снимка: kind 'hov' (под мышью / наведён способ) и 'pick'. */
function vpMark(kind, nodes) {
    const layer = $('vpLayer');
    if (!layer) return;
    layer.querySelectorAll(`.vp-box.${kind}`).forEach(b => b.remove());
    nodes.forEach(n => {
        const [x1, y1, x2, y2] = n.bounds;
        const b = document.createElement('div');
        b.className = `vp-box ${kind}`;
        b.style.cssText = `left:${x1 * 100}%;top:${y1 * 100}%;width:${(x2 - x1) * 100}%;height:${(y2 - y1) * 100}%`;
        layer.appendChild(b);
    });
}

function vpPointer(ev, hover) {
    const rect = $('vpImg').getBoundingClientRect();
    if (!rect.width) return;
    const x = (ev.clientX - rect.left) / rect.width, y = (ev.clientY - rect.top) / rect.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    if (VP.opts.mode === 'point') {
        if (hover) return;
        VP.point = [Math.round(x * 1000) / 1000, Math.round(y * 1000) / 1000];
        const dot = $('vpDot');
        dot.hidden = false;
        dot.style.left = x * 100 + '%';
        dot.style.top = y * 100 + '%';
        vpRender();
        return;
    }
    const hit = recHit(x, y, VP.dump);
    const node = hit ? VP.dump.nodes[hit.target] : null;
    if (hover) return vpMark('hov', node ? [node] : []);
    VP.node = node;
    VP.at = [x, y];
    const opts = vpOptions(node, VP.dump.nodes);
    VP.options = opts;
    VP.choice = opts.length ? opts[0].args : null;
    vpCrop(node).then(src => { VP.crop = src; vpRender(); });
    vpRender();
}

/* Вырезка выбранного места со снимка (с полями) — «вот эта кнопка». */
function vpCrop(node, pad) {
    return new Promise(resolve => {
        if (!node || !VP.dump) return resolve('');
        const img = new Image();
        img.onload = () => {
            const [x1, y1, x2, y2] = node.bounds;
            const p = pad == null ? 0.25 : pad;
            const w = x2 - x1, h = y2 - y1;
            const sx = Math.max(0, x1 - w * p), sy = Math.max(0, y1 - h * p);
            const ex = Math.min(1, x2 + w * p), ey = Math.min(1, y2 + h * p);
            const c = document.createElement('canvas');
            const scale = Math.min(1, 240 / ((ex - sx) * img.width));
            c.width = Math.max(1, Math.round((ex - sx) * img.width * scale));
            c.height = Math.max(1, Math.round((ey - sy) * img.height * scale));
            c.getContext('2d').drawImage(img, sx * img.width, sy * img.height, (ex - sx) * img.width,
                (ey - sy) * img.height, 0, 0, c.width, c.height);
            resolve(c.toDataURL('image/jpeg', 0.8));
        };
        img.onerror = () => resolve('');
        img.src = VP.dump.screenshot;
    });
}

/* Карточка «вот что выбрано» + способы узнать (радио). label — заголовок. */
function vpChoiceHtml(label) {
    if (!VP.node) return `<div class="vp-empty">${recIcon('pointer')}<p>${esc(t('vp.tknite'))}</p></div>`;
    const opts = VP.options || [];
    const picked = `<div class="vp-picked">
        ${VP.crop ? `<img src="${esc(VP.crop)}" alt="">` : '<span class="vp-noimg"></span>'}
        <div><small>${esc(t('vp.vybrano'))}</small><b>${esc(recNodeLabel(VP.node) || t('how.element'))}</b></div>
      </div>`;
    if (!opts.length) return picked + `<p class="vp-warn">${esc(t('vp.nechem_uznat'))}</p>`;
    const have = new Set(VP.opts.have || []);
    return picked + `<p class="vp-h">${esc(label)}</p>
      <div class="vp-opts" role="radiogroup">${opts.slice(0, 5).map((o, i) => {
        const f = vpFriendly(o.args);
        const known = have.has(o.args);
        const many = o.n > 1, shaky = vpShaky(o);
        const note = known ? t('how.uzhe_est') : shaky ? t('vp.mozhet_sdvinutsya')
            : many ? t('vp.naydet_n', {n: o.n}) : t('vp.naydet_odno');
        return `<label class="vp-opt ${o.args === VP.choice ? 'on' : ''} ${known ? 'off' : ''}"
            onmouseenter="vpMark('hov', vpMatches(VP.dump.nodes, this.dataset.args))" onmouseleave="vpMark('hov', [])"
            data-args="${esc(o.args)}">
          <input type="radio" name="vpOpt" ${o.args === VP.choice ? 'checked' : ''} ${known ? 'disabled' : ''}
            onchange="VP.choice=this.closest('label').dataset.args;vpRender()">
          ${recIcon(f.icon)}
          <span class="vp-opt-tx"><span>${esc(f.title)}</span><b>«${esc(f.value)}»</b></span>
          <span class="vp-opt-n ${shaky || many ? 'warn' : 'ok'}">${esc(note)}</span>
          ${i === 0 && !shaky && !many && !known ? `<span class="vp-best">${esc(t('vp.luchshe'))}</span>` : ''}
        </label>`;
      }).join('')}</div>`;
}
