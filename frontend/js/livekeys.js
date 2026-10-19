'use strict';

/* Живая клавиатура: чистая логика без DOM (тесты — backend/tests/test_livekeys_js.py).
   Нажатия копятся и уходят на телефон пачкой по порядку: «привет» — один
   запрос, а не шесть параллельных, которые приходили вперемешку. */

const LIVE_KEYMAP = {
    Backspace: 'delete', Enter: 'enter', Escape: 'back', Tab: 'tab',
    ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
};
const LIVE_KEY_MAX_REPEAT = 50;

/* Что делать с событием keydown: {k:'key',name} | {k:'text',v} |
   'defer' — символ придёт через input (IME, кириллица с виртуальной
   клавиатуры, вставка) | null — не наше. */
function liveKeyOp(ev) {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return null;
    if (ev.isComposing || ev.key === 'Process' || ev.key === 'Unidentified'
        || ev.key === 'Dead') return 'defer';
    if (LIVE_KEYMAP[ev.key]) return {k: 'key', name: LIVE_KEYMAP[ev.key], n: 1};
    if (ev.key && ev.key.length === 1) return {k: 'text', v: ev.key};
    return null;
}

/* Добавить действие в очередь: соседний текст склеивается, повтор одной
   клавиши (удержанный Backspace) — в счётчик. */
function liveKeyMerge(queue, op) {
    const last = queue[queue.length - 1];
    if (last && op.k === 'text' && last.k === 'text') last.v += op.v;
    else if (last && op.k === 'key' && last.k === 'key' && last.name === op.name
        && last.n < LIVE_KEY_MAX_REPEAT) last.n += op.n || 1;
    else queue.push(Object.assign({}, op, op.k === 'key' ? {n: op.n || 1} : {}));
    return queue;
}

/* Очередь → тела запросов к /action. */
function liveKeyActions(queue) {
    return queue.map(op => op.k === 'text'
        ? {type: 'text', value: op.v}
        : (op.n > 1 ? {type: 'key', name: op.name, count: op.n} : {type: 'key', name: op.name}));
}

/* input-событие скрытого поля → действие (виртуальные клавиатуры, IME). */
function liveInputOp(inputType, data) {
    if (inputType === 'deleteContentBackward') return {k: 'key', name: 'delete', n: 1};
    if (inputType === 'insertLineBreak') return {k: 'key', name: 'enter', n: 1};
    if (data && /^(insert|replace)/.test(inputType || 'insertText')) return {k: 'text', v: data};
    return null;
}
