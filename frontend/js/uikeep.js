'use strict';

/* Перерисовка, которая не сбивает человека.

   innerHTML пересоздаёт узлы: фокус уходит на <body>, раскрытые <details>
   схлопываются. Опросы перерисовывают списки раз в 2–3 с, и раньше это
   выглядело так: нажал Tab на карточке запуска — фокус пропал; раскрыл
   «ещё» у шага — запись следующего шага его закрыла. keepUi() запоминает
   эти две вещи до перерисовки и возвращает их на новые узлы того же смысла.

   «Того же смысла» — по ключу: id, иначе обработчик (onclick/onchange/
   oninput — в нём id задачи или шага) и data-id ближайшей строки.
   Раскрытые <details> только раскрываем обратно, а закрыть не пытаемся:
   разметка сама решает, что открыть (например, у шага на проверке). */

function uiFocusKey(el) {
    if (!el || !el.getAttribute) return '';
    if (el.id) return '#' + el.id;
    const handler = el.getAttribute('onclick') || el.getAttribute('onchange')
        || el.getAttribute('oninput') || el.getAttribute('data-f') || '';
    if (!handler) return '';
    const row = el.closest && el.closest('[data-id]');
    return (el.tagName || '') + '|' + (row ? row.getAttribute('data-id') : '') + '|' + handler;
}

function uiDetailsKey(el) {
    const row = el.closest ? el.closest('[data-id]') : null;
    return (row ? row.getAttribute('data-id') : '') + '|' + (el.className || '');
}

/* Ключи раскрытых details по порядку: одинаковые ключи различает номер. */
function uiOpenKeys(list) {
    const seen = {};
    const out = [];
    for (const el of list) {
        const key = uiDetailsKey(el);
        seen[key] = (seen[key] || 0) + 1;
        if (el.open) out.push(key + '#' + seen[key]);
    }
    return out;
}

function keepUi(node, render) {
    const active = document.activeElement;
    const focus = active && active !== node && node.contains(active) ? uiFocusKey(active) : '';
    const caret = focus && typeof active.selectionStart === 'number'
        ? [active.value, active.selectionStart, active.selectionEnd] : null;
    const open = new Set(uiOpenKeys(node.querySelectorAll('details')));

    render();

    if (open.size) {
        const seen = {};
        node.querySelectorAll('details').forEach(el => {
            const key = uiDetailsKey(el);
            seen[key] = (seen[key] || 0) + 1;
            if (!el.open && open.has(key + '#' + seen[key])) el.open = true;
        });
    }
    if (!focus || (document.activeElement && document.activeElement !== document.body)) return;
    const same = [...node.querySelectorAll('[id],[onclick],[onchange],[oninput],[data-f]')]
        .find(el => uiFocusKey(el) === focus);
    if (!same || same.disabled) return;
    same.focus({preventScroll: true});
    if (caret && same.value === caret[0]) {
        try { same.setSelectionRange(caret[1], caret[2]); } catch (e) { /* number и т.п. */ }
    }
}
