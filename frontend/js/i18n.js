/* Строки интерфейса: один ресурс — strings/ru.json.

   Разметка помечает тексты ключами:
       <button data-t="fleet.vybrat_vse">Выбрать все</button>
       <input data-t-placeholder="fleet.poisk" placeholder="…">
   и при загрузке текст берётся из ru.json (текст в разметке — лишь запасной
   вариант и подсказка, что здесь написано). В JS — t('ключ', {n: 3}) с
   подстановкой {n}. Новый текст = новая строка в ru.json, а не литерал в коде;
   тест backend/tests/test_strings.py сверяет, что ключи на месте.

   Синхронная загрузка — намеренно: строки нужны до первой отрисовки, а файл
   локальный и маленький. */

const STRINGS = (function load() {
    try {
        const xhr = new XMLHttpRequest();
        xhr.open('GET', 'strings/ru.json', false);
        xhr.send();
        if (xhr.status === 200) return JSON.parse(xhr.responseText);
    } catch (e) {
        /* без файла строк интерфейс остаётся на запасных текстах разметки */
    }
    return {};
})();

function t(key, vars) {
    let s = STRINGS[key];
    if (s == null) {
        console.warn('нет строки в strings/ru.json:', key);
        return key;
    }
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, name) => (vars[name] != null ? vars[name] : m));
    return s;
}

const T_ATTRS = ['title', 'placeholder', 'aria-label', 'alt'];

/* Текст узла меняем точечно — первый собственный текстовый узел, — чтобы не
   снести иконку <svg> внутри кнопки. */
function applyStrings(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-t]').forEach(el => {
        const s = STRINGS[el.dataset.t];
        if (s == null) return;
        const node = [...el.childNodes].find(n => n.nodeType === 3 && n.nodeValue.trim());
        if (node) {
            const lead = node.nodeValue.match(/^\s*/)[0];
            const tail = node.nodeValue.match(/\s*$/)[0];
            node.nodeValue = lead + s + tail;
        } else {
            el.appendChild(document.createTextNode(s));
        }
    });
    T_ATTRS.forEach(attr => {
        scope.querySelectorAll(`[data-t-${attr}]`).forEach(el => {
            const s = STRINGS[el.getAttribute(`data-t-${attr}`)];
            if (s != null) el.setAttribute(attr, s);
        });
    });
}

applyStrings();
