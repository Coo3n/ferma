'use strict';

/* Советы «как записать точный сценарий»: перед первой записью один раз,
   потом по кнопке «Советы». Грузится после steptools.js: оборачивает recNew.

   Листалка по одному совету с картинкой: четыре карточки текста сразу
   читались как инструкция, которую пролистывают не глядя. Один совет —
   одна картинка «так / не так» и две короткие строки. */

const TIPS_KEY = 'farm.rec.tips';
const TIPS = {i: 0, then: null};

/* Ключи строк пишутся целиком: тест на лишние строки ищет их по тексту. */
const tipsList = () => [
    ['text', t('tips.tekst_t'), t('tips.tekst_ok'), t('tips.tekst_bad')],
    ['wait', t('tips.pauza_t'), t('tips.pauza_ok'), t('tips.pauza_bad')],
    ['one', t('tips.shag_t'), t('tips.shag_ok'), t('tips.shag_bad')],
    ['farm', t('tips.odin_t'), t('tips.odin_ok'), t('tips.odin_bad')],
];

/* Картинки — SVG на токенах (классы ta-*), без растровых файлов: ферма
   работает без интернета, и цвета следуют теме. */
const tipArt = () => ({
    text: `<svg viewBox="0 0 240 140" aria-hidden="true">
      <rect class="ta-body" x="34" y="8" width="70" height="124" rx="10"/>
      <rect class="ta-btn" x="46" y="74" width="46" height="18" rx="9"/>
      <text class="ta-t ta-on" x="69" y="87" text-anchor="middle">${esc(t('tips.a_voyti'))}</text>
      <rect class="ta-ok-ring" x="40" y="68" width="58" height="30" rx="14"/>
      <circle class="ta-ok-fill" cx="98" cy="68" r="9"/><path class="ta-mark" d="M94 68l3 3 5-6"/>
      <rect class="ta-body" x="136" y="8" width="70" height="124" rx="10"/>
      <rect class="ta-dim" x="148" y="30" width="46" height="8" rx="4"/>
      <rect class="ta-dim" x="148" y="44" width="30" height="8" rx="4"/>
      <circle class="ta-bad-dot" cx="182" cy="104" r="4"/>
      <circle class="ta-bad-ring" cx="182" cy="104" r="11"/>
      <circle class="ta-bad-fill" cx="200" cy="68" r="9"/><path class="ta-mark" d="M196 64l8 8M204 64l-8 8"/>
    </svg>`,
    wait: `<svg viewBox="0 0 240 140" aria-hidden="true">
      <path class="ta-line" d="M52 70H188"/>
      <rect class="ta-node" x="14" y="50" width="62" height="40" rx="10"/>
      <text class="ta-t" x="45" y="75" text-anchor="middle">${esc(t('tips.a_otkryt'))}</text>
      <circle class="ta-ok-soft" cx="120" cy="70" r="28"/>
      <circle class="ta-ok-stroke" cx="120" cy="72" r="13"/><path class="ta-ok-stroke" d="M120 72v-6M116 55h8"/>
      <text class="ta-t ta-acc" x="120" y="114" text-anchor="middle">${esc(t('tips.a_pauza'))}</text>
      <rect class="ta-node" x="164" y="50" width="62" height="40" rx="10"/>
      <text class="ta-t" x="195" y="75" text-anchor="middle">${esc(t('tips.a_nazhat'))}</text>
    </svg>`,
    one: `<svg viewBox="0 0 240 140" aria-hidden="true">
      <rect class="ta-pill" x="16" y="22" width="92" height="24" rx="12"/><text class="ta-t" x="62" y="38" text-anchor="middle">${esc(t('tips.a_nazhat'))}</text>
      <rect class="ta-pill" x="16" y="58" width="92" height="24" rx="12"/><text class="ta-t" x="62" y="74" text-anchor="middle">${esc(t('tips.a_podozhdat'))}</text>
      <rect class="ta-pill" x="16" y="94" width="92" height="24" rx="12"/><text class="ta-t" x="62" y="110" text-anchor="middle">${esc(t('tips.a_proverit'))}</text>
      <circle class="ta-ok-fill" cx="112" cy="22" r="9"/><path class="ta-mark" d="M108 22l3 3 5-6"/>
      <rect class="ta-pill-bad" x="132" y="52" width="96" height="36" rx="12"/>
      <text class="ta-t ta-dimt" x="180" y="66" text-anchor="middle">${esc(t('tips.a_dlinno1'))}</text>
      <text class="ta-t ta-dimt" x="180" y="80" text-anchor="middle">${esc(t('tips.a_dlinno2'))}</text>
      <circle class="ta-bad-fill" cx="226" cy="52" r="9"/><path class="ta-mark" d="M222 48l8 8M230 48l-8 8"/>
    </svg>`,
    farm: `<svg viewBox="0 0 240 140" aria-hidden="true">
      <rect class="ta-body ta-body-on" x="22" y="30" width="46" height="82" rx="8"/>
      <circle class="ta-ok-fill" cx="66" cy="32" r="9"/><path class="ta-mark" d="M62 32l3 3 5-6"/>
      <path class="ta-arrow" d="M88 71h40m-8-7l8 7-8 7"/>
      ${[0, 1, 2].map(c => [0, 1].map(r =>
        `<rect class="ta-body" x="${146 + c * 30}" y="${26 + r * 48}" width="24" height="42" rx="5"/>`).join('')).join('')}
    </svg>`,
});

function tipsRender() {
    const list = tipsList();
    const [art, head, ok, bad] = list[TIPS.i];
    const last = TIPS.i === list.length - 1;
    $('mBody').innerHTML = `<div class="tipc">
        <div class="tipc-art">${tipArt()[art]}</div>
        <div class="tipc-tx">
          <span class="tipc-n">${esc(t('tips.n_iz', {n: TIPS.i + 1, total: list.length}))}</span>
          <h3>${esc(head)}</h3>
          <p class="tip-ok"><svg class="ic" aria-hidden="true"><use href="#i-check"/></svg>${esc(ok)}</p>
          <p class="tip-bad"><svg class="ic" aria-hidden="true"><use href="#i-x"/></svg>${esc(bad)}</p>
        </div>
      </div>
      <div class="tipc-dots" role="tablist">${list.map((_, k) => `<button type="button" role="tab"
          aria-selected="${k === TIPS.i}" aria-label="${k + 1}" onclick="tipsGo(${k})"></button>`).join('')}</div>`;
    const finish = TIPS.then ? t('tips.zapisyvat') : t('tips.ponyatno');
    $('mActs').innerHTML = (TIPS.i ? `<button class="sm ghost" onclick="tipsGo(${TIPS.i - 1})">${esc(t('tips.nazad'))}</button>`
        : `<button class="sm ghost" onclick="tipsDone()">${esc(t('tips.propustit'))}</button>`)
        + '<span class="sp"></span>'
        + `<button class="primary" id="tipsNext" onclick="${last ? 'tipsDone()' : `tipsGo(${TIPS.i + 1})`}">${
            esc(last ? finish : t('tips.dalshe'))}</button>`;
    $('tipsNext').focus();
}

function tipsGo(i) {
    TIPS.i = Math.max(0, Math.min(tipsList().length - 1, i));
    tipsRender();
}

function tipsDone() {
    store.set(TIPS_KEY, true);
    closeModal();
    const then = TIPS.then;
    TIPS.then = null;
    if (then) then();
}

function recTipsOpen(then) {
    TIPS.i = 0;
    TIPS.then = typeof then === 'function' ? then : null;
    modalSheet('wide');
    $('mTitle').textContent = t('tips.title');
    openModal();
    tipsRender();
}

/* ← → листают советы, пока окно открыто. */
document.addEventListener('keydown', ev => {
    if (!$('tipsNext') || !$('modal').classList.contains('on')) return;
    if (ev.key === 'ArrowRight') tipsGo(TIPS.i + 1);
    else if (ev.key === 'ArrowLeft') tipsGo(TIPS.i - 1);
});

(function wrapRecNew() {
    const original = window.recNew;
    window.recNew = function (...args) {
        if (store.get(TIPS_KEY, false)) return original(...args);
        recTipsOpen(() => original(...args));
    };
})();
