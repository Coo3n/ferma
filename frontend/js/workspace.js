'use strict';

/* Раскладка рабочего места устройства: ширина зеркала экрана и его
   сворачивание, плюс жесты холста схемы (колесо — масштаб, тяга пустого
   места — панорама).

   Почему это отдельный файл, а не recorder.js: колонки делят между собой
   зеркало и конструктор, и ни одна из сторон не главнее — раскладкой
   владеет рабочее место целиком. Загружается после recorder.js: зовёт
   recSchemeSpine(), когда холсту досталось другое место. */

const MIRROR_MIN = 240;        // уже — зеркало телефона нечитаемо
const MIRROR_MAX_SHARE = 0.55; // больше половины окна зеркалу не отдаём
const MIRROR_KEY = 'farm.work.mirror';
const MIRROR_STEP = 32;        // шаг стрелками с клавиатуры

/* -------------------------------------------------------- ширина зеркала */

function workEl() {
    return $('work');
}

/* clientWidth у закрытого рабочего места — ноль: вид спрятан display:none.
   Считать потолок от нуля значило бы ужимать зеркало до минимума при каждой
   загрузке страницы, начатой не с устройства, — то есть терять
   запомненную ширину. Пока вида нет, меряем по окну. */
function mirrorLimit() {
    const work = workEl();
    const total = (work && work.clientWidth) || window.innerWidth;
    return Math.max(MIRROR_MIN, Math.round(total * MIRROR_MAX_SHARE));
}

function mirrorWidth() {
    const work = workEl();
    if (!work) return MIRROR_MIN;
    const raw = parseInt(getComputedStyle(work).getPropertyValue('--mirror-w'), 10);
    return Number.isFinite(raw) ? raw : MIRROR_MIN;
}

/* Ширину запоминаем: человек один раз решает, сколько ему нужно телефона,
   и не должен растягивать колонку заново при каждом заходе. */
function mirrorResize(width, save) {
    const work = workEl();
    if (!work) return;
    const value = Math.min(mirrorLimit(), Math.max(MIRROR_MIN, Math.round(width)));
    work.style.setProperty('--mirror-w', value + 'px');
    if (save) {
        try {
            localStorage.setItem(MIRROR_KEY, JSON.stringify(
                {width: value, off: work.classList.contains('mirror-off')}));
        } catch (e) {
            /* переполненное хранилище не должно ломать раскладку */
        }
    }
    /* Ширина карточки холста считается от его видимого места (grNodeW) —
       без перерисовки подписи остались бы резаться там, где места уже
       хватает. */
    if (window.recSchemeSpine && REC.view === 'scheme') recSchemeSpine();
    /* Рамки узлов лежат поверх картинки и считаются от её прямоугольника —
       а он только что переехал вместе с колонкой. */
    if (window.recOverlaySync) recOverlaySync();
}

function workSplitStart(ev) {
    const work = workEl();
    const bar = $('workSplit');
    if (!work || !bar || ev.button !== 0) return;
    ev.preventDefault();
    const startX = ev.clientX;
    const base = mirrorWidth();

    bar.setPointerCapture(ev.pointerId);
    bar.classList.add('dragging');

    /* Колонка зеркала правая — тянем влево, она растёт. */
    const onMove = e => mirrorResize(base - (e.clientX - startX), false);
    const onUp = e => {
        bar.removeEventListener('pointermove', onMove);
        bar.removeEventListener('pointerup', onUp);
        bar.classList.remove('dragging');
        mirrorResize(base - (e.clientX - startX), true);
    };
    bar.addEventListener('pointermove', onMove);
    bar.addEventListener('pointerup', onUp);
}

/* Разделитель обязан двигаться и с клавиатуры: мышью тянуть границу —
   единственный способ был бы недоступен без неё (WCAG 2.1.1). */
function workSplitKey(ev) {
    const delta = ev.key === 'ArrowLeft' ? MIRROR_STEP
        : ev.key === 'ArrowRight' ? -MIRROR_STEP : 0;
    if (!delta) return;
    ev.preventDefault();
    mirrorResize(mirrorWidth() + delta, true);
}

/* ---------------------------------------------------- сворачивание зеркала */

function mirrorApply(on, save) {
    const work = workEl();
    if (!work) return;
    work.classList.toggle('mirror-off', !on);

    const btn = $('btnMirror');
    if (btn) {
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.title = on
            ? 'Свернуть экран'
            : 'Показать экран';
        setText(btn.querySelector('span'), on ? 'Экран' : 'Показать экран');
    }
    if (save) mirrorResize(mirrorWidth(), true);
    else if (window.recSchemeSpine && REC.view === 'scheme') recSchemeSpine();
}

function mirrorToggle() {
    const work = workEl();
    mirrorApply(!!(work && work.classList.contains('mirror-off')), true);
}

/* Зовётся из recStart(): кликать по экрану нечем, если он свёрнут. */
function mirrorShow() {
    const work = workEl();
    if (work && work.classList.contains('mirror-off')) mirrorApply(true, true);
}

function mirrorRestore() {
    let saved = null;
    try {
        saved = JSON.parse(localStorage.getItem(MIRROR_KEY) || 'null');
    } catch (e) {
        saved = null;
    }
    if (saved && saved.width) mirrorResize(saved.width, false);
    mirrorApply(!(saved && saved.off), false);
}

/* ------------------------------------------------------------ холст схемы */

/* Жесты вешаем слушателями, а не атрибутами в разметке: wheel обязан быть
   passive:false, иначе preventDefault() не отменит зум всей страницы по
   Ctrl+колесо, и масштабировался бы браузер, а не сюжет. */
(function initCanvas() {
    const view = $('recCanvas');
    if (!view) return;
    view.addEventListener('wheel', grWheel, {passive: false});
    view.addEventListener('pointerdown', grPanStart);
    const list = $('recSteps');
    if (list) list.addEventListener('pointerdown', recListMarquee);
    /* Пробел зажат — левая кнопка двигает холст вместо рамки (GR_SPACE). */
    window.addEventListener('keydown', e => {
        if (e.code === 'Space' && e.target.closest && !e.target.closest('input, textarea, select, [contenteditable]')
            && S.view === 'device' && REC.view === 'scheme') {
            GR_SPACE.down = true;
            e.preventDefault();
        }
    });
    window.addEventListener('keyup', e => {
        if (e.code === 'Space') GR_SPACE.down = false;
    });
})();

/* Окно меняет размер — меняется и видимое место холста, от которого
   считается ширина карточек. Реже, чем приходят события: полсотни
   перерисовок за одно перетаскивание рамки окна тут ни к чему. */
let workResizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(workResizeTimer);
    workResizeTimer = setTimeout(() => {
        mirrorResize(mirrorWidth(), false);
    }, 150);
});

mirrorRestore();
