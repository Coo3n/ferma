'use strict';

/* Онбординг: приветственный тур (раз за сессию) и подсказка при первом
   заходе в раздел (тоже раз за сессию). «?» в шапке открывает тур снова.
   Не лезет поверх модалок и записи. Грузится после app.js: оборачивает showView. */

const ONB_SEEN_KEY = 'farm.onb.tour';        // sessionStorage: тур уже показан
const ONB_OFF_KEY = 'farm.onb.off';          // localStorage: «больше не показывать»
const ONB_DONE_KEY = 'farm.onb.done';        // localStorage: знакомство уже было — один раз навсегда
const ONB = {tour: null, step: 0, opener: null};

function onbSession(key, value) {
    try {
        if (value === undefined) return sessionStorage.getItem(key);
        sessionStorage.setItem(key, value);
    } catch (e) { /* приватный режим: покажем, но без памяти */ }
    return null;
}

function onbOff() {
    return !!(window.store && store.get(ONB_OFF_KEY, false));
}

/* Можно ли сейчас что-то показывать: не поверх модалки, записи и тура. */
function onbBusy() {
    const modal = $('modal');
    return !!(modal && modal.classList.contains('on'))
        || !!(window.REC && (REC.on || REC.builder))
        || !!ONB.tour
        || !!(window.COACH && COACH.key);
}

/* ------------------------------------------------------------ иллюстрации */

function onbTile(x, y, w, h, kind) {
    const bar = kind ? `<rect x="${x}" y="${y}" width="${w}" height="3" rx="1.5" class="${kind === 'bad' ? 'a-bad' : 'a-busy'}"/>` : '';
    const edge = kind === 'bad' ? 'a-badd' : kind === 'busy' ? 'a-busyd' : 'a-p1';
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" class="${edge}"/>${bar}
        <rect x="${x + 6}" y="${y + 9}" width="${w - 12}" height="${h - 24}" rx="4" class="a-glass"/>
        <rect x="${x + 6}" y="${y + h - 10}" width="${Math.round(w * .45)}" height="4" rx="2" class="a-line"/>`;
}

function onbArtFleet() {
    let tiles = '';
    for (let r = 0; r < 2; r++) {
        for (let c = 0; c < 4; c++) {
            const kind = (r === 0 && c === 2) ? 'bad' : ((r + c) % 3 === 1 ? 'busy' : '');
            const g = onbTile(26 + c * 84, 14 + r * 74, 70, 64, kind);
            tiles += (kind === 'bad') ? `<g class="pulse">${g}</g>` : g;
        }
    }
    return `<svg viewBox="0 0 360 210" aria-hidden="true">${tiles}
        <rect x="52" y="164" width="256" height="30" rx="15" class="a-badd"/>
        <circle cx="70" cy="179" r="5" class="a-bad"/>
        <text x="84" y="183" class="t-hi">Телефон 13 — батарея 9%</text></svg>`;
}

function onbArtPult() {
    const icons = ['left', 'home', 'layers', 'volume-low', 'volume-high', 'rotate'];
    const keys = icons.map((n, i) => {
        const x = 168 + (i % 3) * 56, y = 18 + Math.floor(i / 3) * 50;
        return `<rect x="${x}" y="${y}" width="48" height="42" rx="8" class="a-p2"/>
            <svg x="${x + 15}" y="${y + 12}" width="18" height="18" class="a-ico"><use href="#i-${n}"/></svg>`;
    }).join('');
    return `<svg viewBox="0 0 360 210" aria-hidden="true">
        <rect x="30" y="12" width="104" height="186" rx="16" class="a-glass"/>
        <rect x="44" y="34" width="76" height="8" rx="4" class="a-line"/>
        <rect x="44" y="52" width="52" height="8" rx="4" class="a-line"/>
        <rect x="44" y="80" width="76" height="52" rx="8" class="a-p2"/>
        <circle cx="92" cy="104" r="18" class="a-ac tap"/><circle cx="92" cy="104" r="5" class="a-ac"/>
        ${keys}
        <rect x="168" y="124" width="48" height="26" rx="13" class="a-acd"/>
        <rect x="222" y="124" width="48" height="26" rx="13" class="a-p2"/>
        <rect x="276" y="124" width="48" height="26" rx="13" class="a-p2"/>
        <rect x="168" y="162" width="156" height="30" rx="8" class="a-glass"/>
        <rect x="178" y="174" width="70" height="6" rx="3" class="a-line"/></svg>`;
}

function onbArtFiles() {
    const keys = [0, 1, 2].map(r => Array.from({length: 7 - (r === 2 ? 2 : 0)}, (_, c) => {
        const x = 22 + c * 26 + (r === 2 ? 26 : 0);
        return `<rect x="${x}" y="${132 + r * 22}" width="22" height="18" rx="4" class="${r === 1 && c === 3 ? 'a-ac' : 'a-p2'}"/>`;
    }).join('')).join('');
    return `<svg viewBox="0 0 360 210" aria-hidden="true">
        <rect x="236" y="12" width="96" height="186" rx="16" class="a-glass"/>
        <rect x="250" y="34" width="68" height="8" rx="4" class="a-line"/>
        <rect x="250" y="52" width="46" height="8" rx="4" class="a-line"/>
        <rect x="250" y="130" width="68" height="26" rx="6" class="a-acd"/>
        <rect x="26" y="20" width="76" height="86" rx="8" class="a-p1"/>
        <path d="M76 20h8l18 18v8H76z" class="a-p2"/>
        <rect x="38" y="62" width="40" height="6" rx="3" class="a-line"/>
        <rect x="38" y="76" width="30" height="6" rx="3" class="a-line"/>
        <path d="M112 62h104" class="a-dash flow"/><path d="m208 54 10 8-10 8" class="a-stk"/>
        ${keys}</svg>`;
}

function onbArtScen() {
    const rows = [[t('onb.a_najat'), 1], [t('onb.a_vvesti'), 2], [t('onb.a_podozhdat'), 3]].map(([label, n], i) => {
        const y = 52 + i * 46;
        return `<g class="seq" style="animation-delay:${i * .5}s"><rect x="24" y="${y}" width="196" height="36" rx="8" class="a-p1"/>
            <circle cx="44" cy="${y + 18}" r="10" class="a-p2"/><text x="44" y="${y + 22}" text-anchor="middle" class="t-hi">${n}</text>
            <text x="64" y="${y + 22}">${label}</text></g>`;
    }).join('');
    return `<svg viewBox="0 0 360 210" aria-hidden="true">
        <rect x="24" y="12" width="104" height="28" rx="14" class="a-badd"/>
        <circle cx="42" cy="26" r="6" class="a-bad pulse"/><text x="56" y="30" class="t-hi">${t('onb.a_zapis')}</text>
        ${rows}
        <path d="M234 100h18" class="a-dash flow"/>
        <rect x="262" y="12" width="76" height="186" rx="14" class="a-glass"/>
        <rect x="274" y="32" width="52" height="8" rx="4" class="a-line"/>
        <rect x="274" y="96" width="52" height="24" rx="12" class="a-acd"/>
        <circle cx="300" cy="108" r="14" class="a-ac tap"/></svg>`;
}

function onbArtRuns() {
    let grid = '';
    for (let r = 0; r < 2; r++) {
        for (let c = 0; c < 3; c++) {
            grid += `<g class="seq" style="animation-delay:${(r * 3 + c) * .25}s">${onbTile(178 + c * 58, 30 + r * 58, 50, 48, 'busy')}</g>`;
        }
    }
    return `<svg viewBox="0 0 360 210" aria-hidden="true">
        ${onbTile(28, 52, 74, 68, '')}
        <circle cx="92" cy="58" r="12" class="a-ac"/>
        <path d="m86 58 4 4 7-8" fill="none" stroke="var(--accent-ink)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M112 86h50" class="a-dash flow"/><path d="m154 78 10 8-10 8" class="a-stk"/>
        ${grid}
        <text x="65" y="150" text-anchor="middle" class="t-hi">${t('onb.a_odin')}</text>
        <text x="264" y="168" text-anchor="middle" class="t-hi">${t('onb.a_ostalnye')}</text></svg>`;
}

function onbArtAccounts() {
    const rows = [['VK', 'a-busy'], ['IG', 'a-bad'], ['TG', 'a-busy']].map(([name, cls], i) => {
        const y = 24 + i * 52;
        return `<rect x="22" y="${y}" width="206" height="42" rx="8" class="a-p1"/>
            <circle cx="46" cy="${y + 21}" r="13" class="${cls}" opacity=".85"/>
            <text x="46" y="${y + 25}" text-anchor="middle" class="t-hi" style="fill:var(--glass)">${name}</text>
            <rect x="68" y="${y + 11}" width="70" height="7" rx="3.5" class="a-line"/>
            <text x="68" y="${y + 34}" class="t-dim">••••••••</text>
            <path d="M238 ${y + 21}h28" class="a-dash flow" style="animation-delay:${i * .3}s"/>`;
    }).join('');
    return `<svg viewBox="0 0 360 210" aria-hidden="true">${rows}
        ${onbTile(276, 70, 62, 70, '')}
        <circle cx="318" cy="76" r="11" class="a-ac"/>
        <svg x="311" y="69" width="14" height="14"><use href="#i-shield" style="stroke:var(--accent-ink);fill:none"/></svg></svg>`;
}

/* ------------------------------------------------------------------ тур */

function onbSlides() {
    return [
        {art: onbArtFleet(), title: t('onb.s1_title'), text: t('onb.s1_text')},
        {art: onbArtPult(), title: t('onb.s2_title'), text: t('onb.s2_text')},
        {art: onbArtFiles(), title: t('onb.s3_title'), text: t('onb.s3_text')},
        {art: onbArtScen(), title: t('onb.s4_title'), text: t('onb.s4_text')},
        {art: onbArtRuns(), title: t('onb.s5_title'), text: t('onb.s5_text')},
        {art: onbArtAccounts(), title: t('onb.s6_title'), text: t('onb.s6_text')},
    ];
}

function onbOpen() {
    if (ONB.tour) return;
    ONB.opener = document.activeElement;
    ONB.tour = onbSlides();
    ONB.step = 0;
    onbSession(ONB_SEEN_KEY, '1');
    if (window.coachAutoUsed) coachAutoUsed(true);   // после знакомства экранные туры сами не лезут
    if (window.store) store.set(ONB_DONE_KEY, true);
    const root = document.createElement('div');
    root.className = 'onb';
    root.id = 'onb';
    root.innerHTML = `<div class="onb-card" role="dialog" aria-modal="true" aria-labelledby="onbTitle" tabindex="-1">
        <div class="onb-art" id="onbArt"></div>
        <div class="onb-body">
            <p class="onb-step" id="onbStep" aria-live="polite"></p>
            <div class="onb-slide" id="onbSlide">
                <h2 class="onb-title" id="onbTitle"></h2>
                <p class="onb-text" id="onbText"></p>
            </div>
            <div class="onb-dots" id="onbDots"></div>
            <label class="onb-opt"><input type="checkbox" id="onbOff">${esc(t('onb.ne_pokazyvat'))}</label>
            <div class="onb-nav">
                <button class="ghost" id="onbSkip" onclick="onbClose()">${esc(t('onb.propustit'))}</button>
                <span class="sp"></span>
                <button id="onbBack" onclick="onbGo(-1)">${esc(t('onb.nazad'))}</button>
                <button class="primary" id="onbNext" onclick="onbGo(1)"></button>
            </div>
        </div></div>`;
    document.body.appendChild(root);
    $('onbOff').checked = onbOff();
    onbRender(false);
    $('onbNext').focus();
}

function onbRender(animate) {
    const slide = ONB.tour[ONB.step], last = ONB.step === ONB.tour.length - 1;
    $('onbArt').innerHTML = slide.art;
    setText($('onbTitle'), slide.title);
    setText($('onbText'), slide.text);
    setText($('onbStep'), t('onb.shag', {n: ONB.step + 1, total: ONB.tour.length}));
    setText($('onbNext'), last ? t('onb.nachat') : t('onb.dalee'));
    $('onbBack').hidden = ONB.step === 0;
    $('onbSkip').hidden = last;
    $('onbDots').innerHTML = ONB.tour.map((_, i) =>
        `<button class="onb-dot${i === ONB.step ? ' on' : ''}" aria-label="${esc(t('onb.shag', {n: i + 1, total: ONB.tour.length}))}"
            ${i === ONB.step ? 'aria-current="step"' : ''} onclick="onbJump(${i})"></button>`).join('');
    const box = $('onbSlide');
    box.classList.remove('in');
    if (animate) {
        void box.offsetWidth;   // перезапуск анимации
        box.classList.add('in');
    }
}

function onbJump(i) {
    ONB.step = i;
    onbRender(true);
}

function onbGo(dir) {
    const next = ONB.step + dir;
    if (next >= ONB.tour.length) return onbClose();
    if (next < 0) return;
    ONB.step = next;
    onbRender(true);
    if ($('onbNext')) $('onbNext').focus();
}

function onbClose() {
    const root = $('onb');
    if (!root) return;
    if (window.store) store.set(ONB_OFF_KEY, $('onbOff').checked);
    root.remove();
    ONB.tour = null;
    if (ONB.opener && ONB.opener.focus) ONB.opener.focus();
    ONB.opener = null;
}

/* Капча на клавиатуру: стрелки, Esc, Tab по кругу. Ловим в capture и глушим,
   чтобы g/s/j и Esc приложения не срабатывали под туром. */
document.addEventListener('keydown', ev => {
    if (!ONB.tour) return;
    if (ev.key === 'Tab') {
        const items = [...$('onb').querySelectorAll('button:not([hidden]), input')];
        const first = items[0], last = items[items.length - 1];
        if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
        else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
        else if (!$('onb').contains(document.activeElement)) { ev.preventDefault(); first.focus(); }
        ev.stopImmediatePropagation();
        return;
    }
    if (ev.key === 'Escape') onbClose();
    else if (ev.key === 'ArrowRight') onbGo(1);
    else if (ev.key === 'ArrowLeft') onbGo(-1);
    else if (ev.key === 'Enter' || ev.key === ' ') {
        if (ev.target.tagName === 'BUTTON' || ev.target.tagName === 'INPUT') return;   // нативное действие
    }
    ev.stopImmediatePropagation();
}, true);

/* Подсказки по разделам живут в coach.js: затемнение и подсветка прямо на
   экране, а не карточка в углу. */

/* Приветствие: после загрузки, когда ничто не мешает. Метим «показано» только
   в момент показа — тогда занятый экран (модалка, запись) не съедает тур. */
(function autoTour() {
    if (onbOff() || onbSession(ONB_SEEN_KEY) || (window.store && store.get(ONB_DONE_KEY, false))) return;
    let tries = 0;
    const timer = setInterval(() => {
        if (++tries > 100) return clearInterval(timer);
        if (document.hidden || onbBusy() || document.documentElement.classList.contains('boot')) return;
        clearInterval(timer);
        onbOpen();
    }, 200);
})();
