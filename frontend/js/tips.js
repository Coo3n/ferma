'use strict';

/* Советы «как записать точный сценарий»: перед первой записью один раз,
   потом по ссылке «Как записывать точно». Грузится после steptools.js:
   оборачивает recNew. */

const TIPS_KEY = 'farm.rec.tips';
/* Ключи строк пишутся целиком: тест на лишние строки ищет их по тексту. */
const tipsList = () => [
    [t('tips.odin_shag_t'), t('tips.odin_shag')],
    [t('tips.pauza_t'), t('tips.pauza')],
    [t('tips.tekst_t'), t('tips.tekst')],
    [t('tips.proverka_t'), t('tips.proverka')],
    [t('tips.seychas_t'), t('tips.seychas')],
];

function recTipsOpen(then) {
    $('mTitle').textContent = t('tips.title');
    $('mBody').innerHTML = `<ol class="tips">${tipsList().map(([head, text], i) => `<li><span class="tips-n">${i + 1}</span>
        <div><b>${esc(head)}</b><p>${esc(text)}</p></div></li>`).join('')}</ol>`;
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
