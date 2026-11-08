'use strict';

/* Галерея готовых сюжетов: вкладка раздела «Сценарии».

   Шапка: поиск, чипы платформ со счётчиками, «N из M». Карточка: плитка
   платформы, название, строка описания, бейджи (правится в конструкторе /
   только параметры / не проверено), «Что делает» — сворачиваемый список шагов,
   метки полей формы. Единственный основной ярлык карточки — «Добавить в мои».
   После добавления тост с «Открыть», карточка становится «Уже в моих · Открыть».

   Клавиатура (roving tabindex): стрелки — между карточками, Enter/Пробел —
   «Что делает», A — добавить, O — открыть добавленное. */

const GALLERY = {
    list: null,          // null — ещё грузим
    error: '',           // текст ошибки загрузки
    query: '',
    platform: '',        // '' — все
    open: new Set(),     // ключи карточек с раскрытым «Что делает»
    mine: {},            // ключ сюжета → ключ копии, добавленной в этой сессии
    busy: new Set(),     // ключи, которые добавляются прямо сейчас
    focus: '',           // карточка с tabindex=0
};

/* ------------------------------------------------------------ чистые функции */

/* Поиск по словам: каждое слово запроса должно встретиться в названии,
   описании, платформе, шагах или метках полей. Платформа '' — все. */
function galleryFilter(items, query, platform) {
    const words = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
    return (items || []).filter(item => {
        if (platform && item.platform !== platform) return false;
        if (!words.length) return true;
        const hay = [
            item.name, item.description, item.platform,
            ...(item.steps_text || []).map(s => s.text),
            ...(item.params || []).map(p => p.label),
        ].join(' ').toLowerCase();
        return words.every(w => hay.includes(w));
    });
}

/* Платформы с числом сюжетов: [[платформа, число], …] по алфавиту — порядок
   чипов не прыгает, пока человек печатает. */
function galleryPlatforms(items) {
    const counts = new Map();
    for (const item of items || []) {
        const name = item.platform || '';
        if (name) counts.set(name, (counts.get(name) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], 'ru'));
}

/* Цвет плитки — из токенов, по имени платформы: одна и та же платформа всегда
   одного цвета. */
const GAL_TONES = ['accent', 'busy', 'warn', 'bad', 'text2'];

function galleryTone(platform) {
    let h = 0;
    for (const ch of String(platform || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return GAL_TONES[h % GAL_TONES.length];
}

function galleryStepsHtml(steps) {
    return (steps || []).map(s => {
        const depth = Math.max(0, Math.min(4, parseInt(s.depth, 10) || 0));
        return `<li style="--d:${depth}"><span>${esc(s.text)}</span></li>`;
    }).join('');
}

/* state: {open, focus, busy}. Все строки экранируются. */
function galleryCard(item, state) {
    const st = state || {};
    const key = esc(item.key);
    const tab = st.focus ? 0 : -1;
    const steps = item.steps_text || [];
    const params = item.params || [];
    /* Один ярлык максимум: «Правится». «Не проверено» и «только параметры» —
       в подсказке, а не жёлтой плашкой на каждой карточке. */
    const badge = item.editable
        ? `<span class="gal-badge ok" title="${esc(t('gallery.pravitsya_d'))}">${esc(t('gallery.pravitsya'))}</span>` : '';
    const tip = [item.verified ? '' : t('gallery.ne_proveren') + '. ' + t('gallery.ne_proveren_d'),
        item.editable ? '' : t('gallery.tolko_parametry') + '. ' + t('gallery.tolko_parametry_d'),
        params.length ? t('gallery.polya_d') + ': ' + params.map(p => p.label || p.name).join(', ') : '']
        .filter(Boolean).join('\n');
    const what = steps.length ? `
        <button type="button" class="gal-what" tabindex="${tab}" aria-expanded="${st.open ? 'true' : 'false'}"
                aria-controls="galSteps_${key}" onclick="galleryToggle('${key}')">
          <svg class="ic chev" aria-hidden="true"><use href="#i-down"/></svg>
          <span>${esc(t('gallery.chto_delaet'))}</span><b>${steps.length}</b>
        </button>` : '<span></span>';
    const list = steps.length ? `
        <div class="gal-steps" id="galSteps_${key}" role="region" aria-label="${esc(t('gallery.chto_delaet'))}">
          <div><ol>${galleryStepsHtml(steps)}</ol></div>
        </div>` : '';
    const action = item.added
        ? `<button type="button" class="sm gal-open" tabindex="${tab}" onclick="galleryOpenMine('${key}')">
             <svg class="ic" aria-hidden="true"><use href="#i-check"/></svg>${esc(t('gallery.uzhe_otkryt'))}</button>`
        : `<button type="button" class="sm primary" tabindex="${tab}" ${st.busy ? 'disabled' : ''}
             onclick="galleryAdd('${key}')">${esc(t('gallery.dobavit'))}</button>`;
    const letter = esc(String(item.platform || item.name || '?').trim().charAt(0).toUpperCase());
    return `<article class="gal-card" data-key="${key}" data-open="${st.open ? '1' : '0'}" tabindex="${tab}"
             aria-label="${esc(item.name)}"${tip ? ` title="${esc(tip)}"` : ''}>
        <header>
          <span class="gal-tile" data-tone="${galleryTone(item.platform)}" aria-hidden="true">${letter}</span>
          <div class="gal-head"><b title="${esc(item.name)}">${esc(item.name)}</b>
            <span class="gal-sub"><span class="gal-plat">${esc(item.platform)}</span>${badge}</span></div>
        </header>
        <p>${esc(item.description)}</p>
        ${list}
        <footer>${what}${action}</footer>
      </article>`;
}
/* ---------------------------------------------------------------- отрисовка */

async function galleryShow() {
    GALLERY.error = '';
    if (!GALLERY.list) galleryRender();
    await galleryLoad();
}

async function galleryLoad() {
    try {
        GALLERY.list = await api('/api/gallery');
        GALLERY.error = '';
    } catch (e) {
        GALLERY.error = e.message || String(e);
    }
    galleryRender();
}

function galleryRetry() {
    GALLERY.error = '';
    GALLERY.list = null;
    galleryRender();
    galleryLoad();
}

function gallerySkeleton() {
    const card = `<div class="gal-card gal-skel" aria-hidden="true">
        <div class="gal-skel-head"><span class="sk gal-skel-tile"></span><span class="sk-line sk" style="--w:55%"></span></div>
        <span class="sk-line sk"></span><span class="sk-line sk" style="--w:70%"></span>
        <span class="sk-chip sk" style="--w:120px"></span></div>`;
    return `<div class="gal-grid" aria-busy="true">${card.repeat(6)}</div>`;
}

function galleryChipsHtml() {
    const list = GALLERY.list || [];
    const all = galleryPlatforms(list);
    const hits = new Map(galleryPlatforms(galleryFilter(list, GALLERY.query, '')));
    const total = [...hits.values()].reduce((a, b) => a + b, 0);
    const chip = (name, label, n) => `<button type="button" class="gal-pill${GALLERY.platform === name ? ' on' : ''}"
        aria-pressed="${GALLERY.platform === name}" data-n="${n}" onclick="galleryPick('${esc(name)}')">
        ${esc(label)}<b>${n}</b></button>`;
    return chip('', t('gallery.vse'), total) + all.map(([name]) => chip(name, name, hits.get(name) || 0)).join('');
}

function galleryRender() {
    const box = $('galList');
    if (!box) return;
    const list = GALLERY.list;
    const chips = $('galChips');
    const count = $('galCount');
    if (!list) {
        if (chips) setHTML(chips, '');
        if (count) count.textContent = '';
        if (GALLERY.error) {
            setHTML(box, emptyBig({
                art: 'calm', title: esc(t('gallery.oshibka')), text: esc(GALLERY.error),
                action: {label: esc(t('gallery.povtorit')), onClick: 'galleryRetry()', icon: 'refresh'},
            }));
        } else {
            setHTML(box, gallerySkeleton());
        }
        return;
    }
    if (!list.length) {
        if (chips) setHTML(chips, '');
        if (count) count.textContent = '';
        setHTML(box, emptyBig({art: 'scenario', title: esc(t('gallery.pusto')), text: esc(t('gallery.pusto_d'))}));
        return;
    }
    const shown = galleryFilter(list, GALLERY.query, GALLERY.platform);
    if (chips) setHTML(chips, galleryChipsHtml());
    if (count) count.textContent = t('gallery.naydeno', {n: shown.length, total: list.length});
    if (!shown.length) {
        setHTML(box, emptyBig({
            art: 'steps', title: esc(t('gallery.nichego')), text: esc(t('gallery.nichego_d')),
            action: {label: esc(t('gallery.sbrosit')), onClick: 'galleryReset()'},
        }));
        return;
    }
    if (!shown.some(i => i.key === GALLERY.focus)) GALLERY.focus = shown[0].key;
    setHTML(box, `<div class="gal-grid">${shown.map(item => galleryCard(item, {
        open: GALLERY.open.has(item.key),
        focus: item.key === GALLERY.focus,
        busy: GALLERY.busy.has(item.key),
    })).join('')}</div>`);
}

function gallerySearch(value) {
    GALLERY.query = value;
    galleryRender();
}

function galleryPick(platform) {
    GALLERY.platform = GALLERY.platform === platform ? '' : platform;
    galleryRender();
}

function galleryReset() {
    GALLERY.query = '';
    GALLERY.platform = '';
    const input = $('galSearch');
    if (input) input.value = '';
    galleryRender();
}

/* ----------------------------------------------------------------- действия */

/* setHTML помнит последнюю разметку; после правки DOM руками сбрасываем, чтобы
   следующая перерисовка не посчитала список «не изменившимся». */
function galleryHtmlSync() {
    const box = $('galList');
    if (box) box._html = null;
}

/* Раскрытие меняет атрибуты на месте, а не перерисовывает карточку: иначе
   высота не успела бы плавно измениться. */
function galleryToggle(key) {
    const card = document.querySelector(`#galList .gal-card[data-key="${CSS.escape(key)}"]`);
    if (!card) return;
    const open = !GALLERY.open.has(key);
    if (open) GALLERY.open.add(key); else GALLERY.open.delete(key);
    card.dataset.open = open ? '1' : '0';
    const button = card.querySelector('.gal-what');
    if (button) button.setAttribute('aria-expanded', open ? 'true' : 'false');
    galleryHtmlSync();
}

/* Клик по телу карточки — предпросмотр: то же, что «Что делает». */
function galleryCardClick(event, key) {
    if (event.target.closest('button')) return;
    galleryFocusCard(key, false);
    galleryToggle(key);
}

async function galleryAdd(key) {
    if (GALLERY.busy.has(key)) return;
    GALLERY.busy.add(key);
    galleryRender();
    let res;
    try {
        res = await api(`/api/gallery/${encodeURIComponent(key)}/add`, {method: 'POST'});
    } catch (e) {
        GALLERY.busy.delete(key);
        galleryRender();
        toast(e.message, 'bad');
        return;
    }
    GALLERY.busy.delete(key);
    GALLERY.mine[key] = (res && res.key) || key;
    const active = document.activeElement;
    const hadFocus = !!(active && active.closest &&
        active.closest(`#galList .gal-card[data-key="${CSS.escape(key)}"]`));
    try {
        await loadScenarios(true);
        GALLERY.list = await api('/api/gallery');
    } catch (e) {
        toast(e.message, 'bad');
    }
    galleryRender();
    if (hadFocus) galleryFocusCard(key, true);
    toast(t('gallery.dobavlen'), 'ok', {label: t('gallery.otkryt'), onClick: () => galleryOpenMine(key)});
}

/* Открыть добавленное: рецепт — в конструктор (то же, что «Править» в списке
   сценариев), код — выбрать в «Сценариях». */
async function galleryOpenMine(key) {
    const item = (GALLERY.list || []).find(i => i.key === key);
    const target = GALLERY.mine[key] || key;
    if (item && item.kind === 'recipe') {
        await editScenario(target);
        return;
    }
    showView('scen');
    if (!(S.scenarios || []).some(s => s.key === target)) await loadScenarios(true);
    pickScenario(target);
    const row = document.querySelector('#scList .sc.on');
    if (row) row.scrollIntoView({block: 'nearest'});
}

/* ----------------------------------------------------------------- клавиатура */

function galleryCards() {
    return [...document.querySelectorAll('#galList .gal-card[data-key]')];
}

/* Roving tabindex: tabindex=0 только у выбранной карточки и её кнопок. */
function galleryFocusCard(key, focus) {
    GALLERY.focus = key;
    for (const card of galleryCards()) {
        const on = card.dataset.key === key;
        card.tabIndex = on ? 0 : -1;
        card.querySelectorAll('button').forEach(b => { b.tabIndex = on ? 0 : -1; });
        if (on && focus) card.focus();
    }
    galleryHtmlSync();
}

function galleryColumns(cards) {
    if (cards.length < 2) return 1;
    const top = cards[0].offsetTop;
    const n = cards.findIndex(c => c.offsetTop !== top);
    return n < 0 ? cards.length : n;
}

function galleryKey(event) {
    const card = event.target.closest && event.target.closest('.gal-card[data-key]');
    if (!card || event.ctrlKey || event.metaKey || event.altKey) return;
    const key = card.dataset.key;
    const onButton = event.target.closest('button');
    const cards = galleryCards();
    const at = cards.indexOf(card);
    const cols = galleryColumns(cards);
    const move = {ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols}[event.key];
    const item = (GALLERY.list || []).find(i => i.key === key);
    if (move) {
        event.preventDefault();
        const next = cards[Math.max(0, Math.min(cards.length - 1, at + move))];
        if (next) {
            galleryFocusCard(next.dataset.key, true);
            next.scrollIntoView({block: 'nearest'});
        }
    } else if ((event.key === 'Enter' || event.key === ' ') && !onButton) {
        event.preventDefault();
        galleryToggle(key);
    } else if ('aAфФ'.includes(event.key) && event.key.length === 1) {
        if (item && !item.added) {
            event.preventDefault();
            galleryAdd(key);
        }
    } else if ('oOщЩ'.includes(event.key) && event.key.length === 1) {
        if (item && item.added) {
            event.preventDefault();
            galleryOpenMine(key);
        }
    }
}

function galleryInit() {
    const box = $('galList');
    if (box && !box._galBound) {
        box._galBound = true;
        box.addEventListener('keydown', galleryKey);
        box.addEventListener('click', e => {
            const card = e.target.closest('.gal-card[data-key]');
            if (card) galleryCardClick(e, card.dataset.key);
        });
        box.addEventListener('focusin', e => {
            const card = e.target.closest('.gal-card[data-key]');
            if (card && card.dataset.key !== GALLERY.focus) galleryFocusCard(card.dataset.key, false);
        });
    }
    const input = $('galSearch');
    if (input && !input._galBound) {
        input._galBound = true;
        input.addEventListener('keydown', e => {
            if (e.key === 'ArrowDown') {
                const first = galleryCards()[0];
                if (first) {
                    e.preventDefault();
                    galleryFocusCard(first.dataset.key, true);
                }
            } else if (e.key === 'Escape' && input.value) {
                e.stopPropagation();
                galleryReset();
            }
        });
    }
}

if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', galleryInit);
    else galleryInit();
}
