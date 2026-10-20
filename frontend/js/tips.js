'use strict';

/* Советы «как записать точный сценарий»: перед первой записью один раз,
   потом по ссылке «Как записывать точно». Грузится после steptools.js:
   оборачивает recNew. */

const TIPS_KEY = 'farm.rec.tips';
/* Ключи строк пишутся целиком: тест на лишние строки ищет их по тексту.
   Четыре правила, у каждого — одна строка и пример «так / не так». */
const tipsList = () => [
    ['crosshair', t('tips.tekst_t'), t('tips.tekst_ok'), t('tips.tekst_bad')],
    ['pause', t('tips.pauza_t'), t('tips.pauza_ok'), t('tips.pauza_bad')],
    ['check-square', t('tips.shag_t'), t('tips.shag_ok'), t('tips.shag_bad')],
    ['phone', t('tips.odin_t'), t('tips.odin_ok'), t('tips.odin_bad')],
];

function recTipsOpen(then) {
    modalSheet('wide');
    $('mTitle').textContent = t('tips.title');
    $('mBody').innerHTML = `<div class="tips">${tipsList().map(([icon, head, ok, bad]) => `<section class="tip">
        <svg class="ic tip-ic" aria-hidden="true"><use href="#i-${icon}"/></svg>
        <h4>${esc(head)}</h4>
        <p class="tip-ok"><svg class="ic" aria-hidden="true"><use href="#i-check"/></svg>${esc(ok)}</p>
        <p class="tip-bad"><svg class="ic" aria-hidden="true"><use href="#i-x"/></svg>${esc(bad)}</p>
      </section>`).join('')}</div>`;
    $('mActs').innerHTML = '<span class="sp"></span>'
        + `<button class="primary" id="tipsGo">${esc(then ? t('tips.zapisyvat') : t('tips.ponyatno'))}</button>`;
    openModal();
    $('tipsGo').onclick = () => {
        store.set(TIPS_KEY, true);
        closeModal();
        if (then) then();
    };
}

(function wrapRecNew() {
    const original = window.recNew;
    window.recNew = function () {
        if (store.get(TIPS_KEY, false)) return original();
        recTipsOpen(original);
    };
})();
