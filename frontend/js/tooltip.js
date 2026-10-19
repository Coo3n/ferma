'use strict';

/* Единые подсказки вместо браузерных title. Один общий узел и делегирование
   на документе: на ферме из 40 плиток никаких наблюдателей на элемент.
   title забирается в data-tip при наведении/фокусе (нативный не мигает рядом),
   а disableWithReason, ставящий title заново, подхватывается при следующем
   наведении. На touch подсказок нет. */
(function () {
    const DELAY = 350;
    const GAP = 8;
    const EDGE = 8;
    if (!window.matchMedia || matchMedia('(hover: none)').matches) return;

    const tip = document.createElement('div');
    tip.id = 'tip';
    tip.setAttribute('role', 'tooltip');
    tip.innerHTML = '<b class="tip-head"></b><span class="tip-body"></span>'
        + '<span class="tip-keys"></span><i class="tip-arrow" aria-hidden="true"></i>';
    document.body.appendChild(tip);
    const head = tip.querySelector('.tip-head'), body = tip.querySelector('.tip-body'),
        keys = tip.querySelector('.tip-keys'), arrow = tip.querySelector('.tip-arrow');
    const KEY_NAMES = {Escape: 'Esc', Space: 'Пробел', ArrowLeft: '←', ArrowRight: '→',
        ArrowUp: '↑', ArrowDown: '↓'};

    let target = null, timer = 0;

    /* Забирает title в data-tip; пустой title стирает прежнюю подсказку
       (disableWithReason возвращает исходный пустой title при включении). */
    function textOf(el) {
        if (el.hasAttribute('title')) {
            const v = el.getAttribute('title');
            el.removeAttribute('title');
            if (v) el.dataset.tip = v; else delete el.dataset.tip;
        }
        return el.dataset.tip || '';
    }

    function hide() {
        clearTimeout(timer);
        timer = 0;
        tip.classList.remove('on');
        if (target) target.removeAttribute('aria-describedby');
        target = null;
    }

    function place(el) {
        const r = el.getBoundingClientRect();
        const w = tip.offsetWidth, h = tip.offsetHeight;
        const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
        const below = r.top - h - GAP < EDGE;
        let x = r.left + r.width / 2 - w / 2;
        x = Math.max(EDGE, Math.min(vw - w - EDGE, x));
        let y = below ? r.bottom + GAP : r.top - h - GAP;
        y = Math.max(EDGE, Math.min(vh - h - EDGE, y));
        tip.style.left = Math.round(x) + 'px';
        tip.style.top = Math.round(y) + 'px';
        tip.dataset.side = below ? 'bottom' : 'top';
        const ax = r.left + r.width / 2 - x;
        arrow.style.left = Math.max(12, Math.min(w - 12, ax)) + 'px';
    }

    function show(el) {
        const text = textOf(el);
        if (!text || !el.isConnected) return;
        /* «Крупно — видно экран»: до тире — заголовок, после — пояснение.
           Короткое начало, иначе тире внутри фразы рвало бы её пополам. */
        const cut = text.indexOf(' — ');
        const titled = cut > 0 && cut <= 32;
        head.textContent = titled ? text.slice(0, cut) : '';
        body.textContent = titled ? text.slice(cut + 3) : text;
        tip.classList.toggle('has-head', titled);
        const shortcuts = (el.getAttribute('aria-keyshortcuts') || '').split(/\s+/).filter(Boolean).slice(0, 4);
        keys.innerHTML = '';
        shortcuts.forEach(k => {
            const kbd = document.createElement('kbd');
            kbd.textContent = KEY_NAMES[k] || k;
            keys.appendChild(kbd);
        });
        tip.id = 'tip';
        el.setAttribute('aria-describedby', 'tip');
        tip.style.left = tip.style.top = '0px';
        place(el);
        tip.classList.add('on');
    }

    function enter(ev) {
        const el = ev.target.closest && ev.target.closest('[title],[data-tip]');
        if (!el || el === target) return;
        hide();
        if (!textOf(el)) return;
        target = el;
        /* Фокус с клавиатуры показываем сразу: ждать 350 мс некому. */
        timer = setTimeout(() => show(el), ev.type === 'focusin' ? 0 : DELAY);
    }

    function leave(ev) {
        if (target && (ev.type === 'focusout' || !target.contains(ev.relatedTarget))) hide();
    }

    document.addEventListener('pointerover', enter);
    document.addEventListener('pointerout', leave);
    document.addEventListener('focusin', enter);
    document.addEventListener('focusout', leave);
    document.addEventListener('pointerdown', hide, true);
    document.addEventListener('keydown', ev => { if (ev.key === 'Escape') hide(); }, true);
    window.addEventListener('scroll', hide, true);
    window.addEventListener('blur', hide);
    window.addEventListener('resize', hide);

    /* Узел, на котором висит подсказка, могут перерисовать (опрос фермы). */
    new MutationObserver(() => { if (target && !target.isConnected) hide(); })
        .observe(document.body, {childList: true, subtree: true});
})();
