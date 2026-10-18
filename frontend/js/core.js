'use strict';

/* Общее состояние и утилиты. Загружается первым.

   Состояние живёт на window намеренно: у обычного (не module) скрипта
   верхнеуровневый const не становится свойством window, и проверки вида
   `window.S` из соседних файлов давали бы undefined. См. docs/GOTCHAS.md. */

const HIDDEN_KEY = 'farm.hidden';
const TOAST_MS = 3000;
const TOAST_ERROR_MS = 6000;

const S = window.S = {
    devices: [],
    devicesLoaded: false,   // пока ферма не ответила, «пусто» показывать нельзя
    selected: new Set(),
    active: null,
    scenarios: [],
    scenario: null,
    jobs: [],
    job: null,
    deviations: [],
    streaming: true,
    devSig: '',
    hidden: new Set((() => { try { return JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]'); } catch (e) { return []; } })()),
    showHidden: false,
    query: '',
    view: 'fleet',
};

function $(id) {
    return document.getElementById(id);
}

function esc(value) {
    return String(value ?? '').replace(/[&<>"]/g, c => (
        {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]
    ));
}

/* ------------------------------------------------------- пустые состояния */

/* Рисунки для заглушек. Вшиты в код, а не грузятся по ссылке: ферма ведёт
   телефоны по USB и обязана подниматься без интернета — внешняя картинка
   дала бы в оффлайне битую иконку ровно на том экране, который объясняет
   новичку, что делать (та же причина у спрайта frontend/icons.svg).

   Все нарисованы в одной системе: холст 150×120, обводка 2, currentColor,
   opacity для второго плана. Одна рука — значит заглушки разных разделов
   выглядят роднёй, а не набором случайных иллюстраций. */
const EMPTY_ART = {
    /* Лист сценария со стрелкой ветвления: сюжет, которого ещё нет. */
    scenario: `<path d="M44 16h44l18 18v70a6 6 0 0 1-6 6H44a6 6 0 0 1-6-6V22a6 6 0 0 1 6-6z"
        stroke="currentColor" stroke-width="2" opacity=".9"/>
      <path d="M88 16v18h18" stroke="currentColor" stroke-width="2" opacity=".6"/>
      <path d="M56 52h30M56 64h22" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" opacity=".35"/>
      <circle cx="60" cy="82" r="4" stroke="currentColor" stroke-width="2" opacity=".8"/>
      <path d="M60 86v6a5 5 0 0 0 5 5h13" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" opacity=".7"/>
      <circle cx="84" cy="97" r="4" stroke="currentColor" stroke-width="2" opacity=".8"/>`,

    /* Очередь: три полосы задач и галочка — то, что здесь появится. */
    job: `<rect x="26" y="30" width="98" height="18" rx="5"
        stroke="currentColor" stroke-width="2" opacity=".85"/>
      <rect x="26" y="56" width="98" height="18" rx="5"
        stroke="currentColor" stroke-width="2" opacity=".5"/>
      <rect x="26" y="82" width="98" height="18" rx="5"
        stroke="currentColor" stroke-width="2" opacity=".28"/>
      <path d="M38 39h8M38 65h8M38 91h8" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" opacity=".6"/>
      <path d="M100 35l4 4 8-8" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round" opacity=".9"/>`,

    /* Щит с галочкой: отклонений нет — путь чист. */
    calm: `<path d="M75 16l34 13v27c0 25-15 40-34 48-19-8-34-23-34-48V29z"
        stroke="currentColor" stroke-width="2" opacity=".9"/>
      <path d="M62 60l10 10 20-21" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round" opacity=".85"/>`,

    /* Цепочка шагов с точкой ветвления: пустой конструктор. */
    steps: `<rect x="20" y="20" width="52" height="20" rx="6"
        stroke="currentColor" stroke-width="2" opacity=".9"/>
      <path d="M46 40v14" stroke="currentColor" stroke-width="2" opacity=".5"/>
      <rect x="20" y="54" width="52" height="20" rx="6"
        stroke="currentColor" stroke-width="2" opacity=".65"/>
      <path d="M46 74v14" stroke="currentColor" stroke-width="2" opacity=".5"/>
      <rect x="20" y="88" width="52" height="20" rx="6"
        stroke="currentColor" stroke-width="2" stroke-dasharray="4 4" opacity=".4"/>
      <path d="M72 64h16a6 6 0 0 1 6 6v10" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" opacity=".55"/>
      <rect x="80" y="80" width="46" height="20" rx="6"
        stroke="currentColor" stroke-width="2" stroke-dasharray="4 4" opacity=".4"/>`,

    /* Лента журнала с курсором: строки прогона, которых ещё не выбрали. */
    log: `<rect x="24" y="18" width="102" height="84" rx="8"
        stroke="currentColor" stroke-width="2" opacity=".9"/>
      <path d="M24 36h102" stroke="currentColor" stroke-width="2" opacity=".5"/>
      <circle cx="35" cy="27" r="2" fill="currentColor" opacity=".6"/>
      <circle cx="43" cy="27" r="2" fill="currentColor" opacity=".4"/>
      <path d="M38 50h46M38 62h62M38 74h30" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" opacity=".35"/>
      <path d="M76 74h14" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" opacity=".85"/>
      <path d="M38 88h22" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" opacity=".2"/>`,

    /* Телефон без подключения: устройство не выбрано. */
    device: `<rect x="49" y="12" width="52" height="86" rx="9"
        stroke="currentColor" stroke-width="2" opacity=".9"/>
      <rect x="55" y="19" width="40" height="66" rx="4" fill="currentColor" opacity=".08"/>
      <path d="M67 16h16" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" opacity=".7"/>
      <circle cx="75" cy="91" r="2.4" fill="currentColor" opacity=".7"/>
      <path d="M26 44h14M33 37v14" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" opacity=".4"/>
      <circle cx="120" cy="70" r="3" stroke="currentColor" stroke-width="2" opacity=".3"/>`,
};

function emptyArtSvg(name) {
    return `<svg class="art" viewBox="0 0 150 120" fill="none" aria-hidden="true">
    ${EMPTY_ART[name] || ''}</svg>`;
}

/* Сборка заглушки. Поля кроме art и title необязательны: у «Отклонений»
   нет ни шагов, ни кнопки — там пусто значит «всё хорошо», и звать никуда
   не надо. Текст в title/text/steps/action.label не экранируется: его
   пишем мы сами в коде, а не пользователь и не устройство.

   Внешний .emptywrap центрирует блок и служит контейнером для @container
   в base.css — узкая колонка ужимает заглушку сама, без флага в вызове. */
function emptyBig({art, title, text, steps, action}) {
    const шаги = (steps || []).length
        ? `<ol>${steps.map((s, i) => `<li><b>${i + 1}</b>${s}</li>`).join('')}</ol>`
        : '';
    const кнопка = action
        ? `<button class="sm" onclick="${action.onClick}">
        ${action.icon ? `<svg class="ic"><use href="#i-${action.icon}"/></svg>` : ''}
        ${action.label}</button>`
        : '';
    return `<div class="emptywrap"><div class="emptybig">
    ${emptyArtSvg(art)}
    <h3>${title}</h3>
    ${text ? `<p>${text}</p>` : ''}
    ${шаги}
    ${кнопка}
  </div></div>`;
}

/* Пишем разметку, только если она правда изменилась.

   Та же причина, что у setText, но злее: списки задач и отклонений
   перерисовываются опросом раз в несколько секунд, и присваивание
   innerHTML пересоздаёт узлы даже когда содержимое то же самое. Вместе с
   узлами заново проигрываются анимации появления — пустой раздел моргал
   рисунком на каждом цикле опроса. Плюс слетало выделение текста и
   позиция курсора в полях внутри. */
function setHTML(node, html) {
    if (!node || node._html === html) return;
    node._html = html;
    /* Данные правда сменились — узлы новые, но фокус и раскрытые <details>
       возвращаем на место (uikeep.js). */
    if (window.keepUi) keepUi(node, () => { node.innerHTML = html; });
    else node.innerHTML = html;
}

/* Пишем в узел, только если текст правда изменился.

   Дело не в скорости: присваивание textContent пересоздаёт текстовый узел, а
   вместе с ним слетает выделение мышью. Плитки фермы обновляются каждые
   2.5 с, и без этой проверки выделить серийник было бы невозможно. */
function setText(node, value) {
    const text = String(value ?? '');
    if (node && node.textContent !== text) node.textContent = text;
}

/* Слова для человека — одни на весь сайт. Раньше названия соцсетей жили
   в пяти файлах, а статус задачи показывался как есть: PASSED/FAILED. */
const PLATFORM_NAMES = window.PLATFORM_NAMES = {vk: 'VK', inst: 'Instagram', tiktok: 'TikTok', tg: 'Telegram'};

const JOB_STATUS_WORDS = {
    queued: 'в очереди', running: 'идёт', held: 'ждёт', cancelling: 'отменяется',
    passed: 'готово', failed: 'сбой', cancelled: 'отменено',
};

function jobStatusWord(status) {
    return JOB_STATUS_WORDS[status] || status;
}

/* Карточка-div с onclick (сценарий, задача) доступна с клавиатуры:
   tabindex + role=button в разметке, Enter/пробел — здесь, один раз на всех. */
document.addEventListener('keydown', ev => {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    const card = ev.target.closest && ev.target.closest('[data-kbd]');
    if (!card || ev.target !== card) return;
    ev.preventDefault();
    card.click();
});

function saveHidden() {
    store.set(HIDDEN_KEY, [...S.hidden]);
}

/* localStorage — в приватном режиме и при запрете сайтам хранить данные
   бросает исключение. Одна обёртка вместо try/catch в каждом файле. */
const store = window.store = {
    get(key, fallback) {
        try {
            const raw = localStorage.getItem(key);
            return raw == null ? fallback : JSON.parse(raw);
        } catch (e) {
            return fallback;
        }
    },
    set(key, value) {
        try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* приватный режим */ }
    },
};

/* Опасное действие подтверждается вторым нажатием той же кнопки в течение
   4 с — без confirm(), который блокирует страницу. true — подтверждено. */
function armConfirm(btn, armedText) {
    if (btn.dataset.armed) return true;
    /* Текст меняем, только если он задан: у кнопки-иконки textContent
       стёр бы саму иконку. Ей хватает класса .armed (красная заливка). */
    const label = armedText ? (btn.querySelector('span') || btn) : null;
    btn.dataset.armed = '1';
    btn.classList.add('armed');
    if (label) {
        btn.dataset.label = label.textContent;
        label.textContent = armedText;
    }
    setTimeout(() => {
        delete btn.dataset.armed;
        btn.classList.remove('armed');
        if (label) label.textContent = btn.dataset.label;
    }, 4000);
    return false;
}

/* action — необязательная {label, onClick}: тост со ссылкой на следующий
   шаг там, где он не очевиден с текущего экрана (например «сценарий
   сохранён» — а запускается сценарий с другой вкладки). Клик по ссылке
   не ждёт автоматического исчезновения. */
function toast(message, kind, action) {
    const el = document.createElement('div');
    el.className = 'toast ' + (kind || '');
    const dismiss = () => {
        /* Уходит туда же, откуда пришёл — вниз и чуть сжимаясь. Пара
           «пришёл снизу / ушёл вниз» читается как один предмет, а не как
           два разных события. */
        el.style.opacity = 0;
        el.style.transform = 'translateY(10px) scale(.97)';
        setTimeout(() => el.remove(), 250);
    };
    /* Тост — предложение: с заглавной буквы, как и весь интерфейс. */
    const text = String(message);
    el.append(document.createTextNode(text.charAt(0).toUpperCase() + text.slice(1)));
    if (action) {
        const link = document.createElement('button');
        link.type = 'button';
        link.className = 'toast-action';
        link.textContent = action.label;
        link.onclick = () => {
            action.onClick();
            dismiss();
        };
        el.appendChild(link);
    }
    const box = $('toast');
    /* Тот же текст уже на экране — не дублируем (двойной клик, повтор
       опроса). Больше трёх сразу не держим: стопка из пяти закрывала
       кнопки телефона, а читают всё равно последний. */
    for (const old of box.children) {
        if (old.firstChild && old.firstChild.nodeValue === el.firstChild.nodeValue) old.remove();
    }
    box.appendChild(el);
    while (box.children.length > 3) box.firstElementChild.remove();
    /* Длинные тосты (развёрнутые подсказки при первом клике по «Якорю»/
       «Развилке» — см. recFirstHint в recorder.js) читаются дольше пары
       слов — время на экране растёт с длиной текста, а не фиксировано. */
    const base = kind === 'bad' ? TOAST_ERROR_MS : TOAST_MS;
    const duration = Math.max(base, Math.min(message.length * 60, 10000));
    setTimeout(dismiss, duration);
}

async function api(path, options) {
    let response;
    try {
        response = await fetch(path, options);
    } catch (e) {
        /* Без этого человек видел английское «Failed to fetch». */
        throw new Error('нет связи с фермой — программа фермы запущена?');
    }
    const type = response.headers.get('content-type') || '';
    const body = type.includes('json')
        ? await response.json().catch(() => ({}))
        : await response.text();
    if (!response.ok) {
        /* FastAPI на ошибке проверки отдаёт detail массивом — без разбора
           человек видел тост «[object Object]». */
        let detail = body && body.detail;
        if (Array.isArray(detail)) {
            detail = 'проверьте заполнение полей: '
                + detail.map(d => (d.loc ? d.loc[d.loc.length - 1] : '') || d.msg || '').join(', ');
        } else if (detail && typeof detail === 'object') {
            detail = JSON.stringify(detail);
        }
        throw new Error(detail || (typeof body === 'string' && body.length < 300 && body)
            || (response.status >= 500
                ? `сбой на ферме (код ${response.status}) — повторите или перезапустите ферму`
                : `запрос не прошёл (код ${response.status}) — обновите страницу`));
    }
    return body;
}

function post(path, data) {
    return api(path, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data === undefined ? {} : data),
    });
}

/* ------------------------------------------------------------------ модалка

   Фокус обязан оставаться внутри открытого диалога: иначе табом уезжаешь в
   фоновую страницу, продолжая видеть модалку, и непонятно, что вообще в
   фокусе. Escape закрывает, при закрытии фокус возвращается туда, откуда
   диалог открыли. */

let modalReturn = null;

function modalFocusables() {
    return [...$('modal').querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
        .filter(el => !el.disabled && el.offsetParent !== null);
}

document.addEventListener('keydown', ev => {
    const modal = $('modal');
    if (!modal || !modal.classList.contains('on')) return;

    if (ev.key === 'Escape') {
        /* Esc закрывает только окно. Без stopImmediatePropagation тот же Esc
           доходил до горячих клавиш app.js и выкидывал с экрана телефона
           на ферму, ставя запись на паузу. */
        ev.preventDefault();
        ev.stopImmediatePropagation();
        closeModal();
        return;
    }
    if (ev.key !== 'Tab') return;

    const items = modalFocusables();
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault();
        last.focus();
    } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault();
        first.focus();
    }
});

function openModal() {
    modalReturn = document.activeElement;
    $('modal').classList.add('on');
    const items = modalFocusables();
    if (items.length) items[0].focus();
}

window.$ = $;
window.esc = esc;
window.setText = setText;
window.openModal = openModal;

/* Выключить кнопку, объяснив причину. Причина живёт в title: иначе человек
   видит серую кнопку и гадает, что не так — а это ровно та ситуация, из-за
   которой интерфейс кажется сломанным. */
function disableWithReason(button, disabled, reason) {
    if (!button) return;
    button.disabled = !!disabled;
    if (disabled) {
        /* === undefined, а не «пусто»: у кнопки без подсказки исходный title
           пустой, и второй вызов сохранял причину как «исходную» — она
           оставалась висеть и после включения. */
        if (button.dataset.title === undefined) button.dataset.title = button.title || '';
        button.title = reason;
    } else if (button.dataset.title !== undefined) {
        button.title = button.dataset.title;
    }
}

/* Material Design риплы на все кнопки. Срабатывает при клике, быстро
   расширяется с fade-out. Реализована через ::before и класс ripple,
   чтобы не было дополнительных DOM-узлов. */
function initRipples() {
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (!btn || btn.disabled) return;

        // Убрать класс если был на предыдущем клике
        btn.classList.remove('ripple');
        // Trigger reflow для перезапуска анимации
        void btn.offsetWidth;
        // Добавить класс для запуска анимации
        btn.classList.add('ripple');
        // Убрать класс когда анимация закончится
        setTimeout(() => btn.classList.remove('ripple'), 400);
    }, true);
}

window.disableWithReason = disableWithReason;

// Инициализировать риплы когда DOM готов
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initRipples);
} else {
    initRipples();
}
