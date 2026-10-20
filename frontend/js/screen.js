'use strict';

/* Трансляция экрана, жесты по картинке и ручной ввод. */

const LONG_TAP_MS = 600;
const LONG_TAP_DURATION = 0.8;
const SWIPE_MIN_DISTANCE = 0.03;
const SWIPE_MIN_DURATION = 0.1;
const SWIPE_MAX_DURATION = 0.8;

/* ------------------------------------------------------------------ просмотр

   Экран на сайте — витрина. Жесты и клавиши уходят на телефон только при
   включённой записи: конструктор иначе нечем наполнять. В остальное время
   ручная работа живёт в отдельном окне scrcpy — MJPEG отстаёт на десятые доли
   секунды, и случайный тап «мимо» дороже удобства. */

/* Экран оживает и когда задача на этом устройстве стоит и ждёт человека
   (HELD): именно затем она и держит телефон — поправить экран руками и
   ответить «повторить». Тап при этом не записывается: запись выключена. */
function heldHere() {
    return (S.jobs || []).some(job => job.serial === S.active && job.status === 'held')
        || !!(window.REC && REC.run && REC.run.job && REC.run.job.status === 'held'
            && REC.run.job.serial === S.active);
}

function canInteract() {
    return !!(window.REC && (REC.on || REC.blockPick != null)) || heldHere() || !!S.liveControl
        || pultLive();
}

/* Пульт: телефон открыли, чтобы управлять, — экран живой сразу. Но не когда
   на нём идёт запуск: случайный клик «посмотреть» сбил бы сценарий. */
function pultLive() {
    if (!(window.pultOn && pultOn())) return false;
    const device = S.devices.find(d => d.serial === S.active);
    return !(device && device.busy_job);
}

/* «Управлять»: трогать устройство, не записывая шаги, вместо перехода в
   scrcpy для мелочи вроде закрыть системный диалог или отскроллить один
   раз. Тот же неточный поток, что и у записи, — не обещаем большего.
   Выключается сама при старте записи и при уходе с устройства: индикатор
   «управляю», оставшийся висеть на чужом экране, был бы ровно той путаницей,
   которую эта кнопка должна снять. */
function toggleLiveControl() {
    S.liveControl = !S.liveControl;
    syncInteractive();
}

function liveControlOff() {
    if (!S.liveControl) return;
    S.liveControl = false;
    syncInteractive();
}

/* Задача, которая держит именно активное устройство — если такая есть. */
function heldJobHere() {
    return (S.jobs || []).find(job => job.serial === S.active && job.status === 'held');
}

/* «Открыть устройство» из решения по HELD-задаче (jobs.js: decisionBar)
   роняет человека в конструктор, где не видно ни причины, ни «повторить
   шаг» — решать всё равно приходится, вернувшись на «Задачи». Тот же
   decisionBar, показанный прямо тут, делает то же самое, что и обещает
   README: «открыл → поправил руками → повторить шаг», без прыжка обратно. */
function syncDeviceHeldBar() {
    const box = $('deviceHeldBar');
    if (!box || !window.decisionBar) return;
    const job = heldJobHere();
    /* Уже показываем, как быть на этом экране, — второй раз ту же кнопку не
       предлагаем: после «Сохранить» запуск продолжится сам. */
    const учим = job && window.REC && REC.teach && REC.teach.resume === job.id;
    /* Зовётся с каждым опросом задач: innerHTML заново грузил миниатюру
       снимка в полосе, и она мигала пустой рамкой раз в 2 с. */
    setHTML(box, job && !учим ? decisionBar(job, {onDevice: true}) : '');
}

function syncInteractive() {
    const live = canInteract();
    document.querySelectorAll('[data-live]').forEach(el =>
        disableWithReason(el, !live, 'Включите «Управлять телефоном» над экраном'));
    const stage = document.querySelector('.stage');
    if (stage) stage.classList.toggle('ro', !live);
    /* Пока идёт запись или задача HELD, экран и так управляется —
       переключатель прячем, иначе он противоречил бы происходящему. */
    const toggle = $('btnLiveControl');
    if (toggle) {
        const recording = !!(window.REC && REC.on);
        const held = heldHere();
        toggle.hidden = !S.active || recording || held || pultLive();
        toggle.classList.toggle('on', !!S.liveControl);
        toggle.setAttribute('aria-checked', String(!!S.liveControl));
    }
    syncDeviceHeldBar();
}

/* Клик по витрине не уходит на устройство, а предлагает scrcpy — иначе
   молчаливое бездействие читается как «сайт завис». */
function offerScrcpy() {
    if ($('modal').classList.contains('on')) return;
    const device = S.devices.find(d => d.serial === S.active);
    const busy = !!(device && device.busy_job);
    $('mTitle').textContent = busy ? t('screen.view_busy_title') : t('screen.view_only_title');
    $('mBody').innerHTML = `<div class="viewonly">
        <svg class="viewonly-art" viewBox="0 0 96 96" aria-hidden="true">
            <rect x="30" y="8" width="36" height="72" rx="7" class="vo-body"/>
            <rect x="35" y="16" width="26" height="50" rx="2" class="vo-screen"/>
            <circle cx="48" cy="73" r="2.2" class="vo-dot"/>
            <path d="M64 70c6-9 18-9 24 0c-6 9-18 9-24 0z" class="vo-eye"/>
            <circle cx="76" cy="70" r="3.4" class="vo-pupil"/>
        </svg>
        <p class="viewonly-text">${esc(busy ? t('screen.view_busy_text') : t('screen.view_only_text'))}</p>
    </div>`;
    $('mActs').innerHTML = '<span class="sp"></span>'
        + `<button class="sm" onclick="closeModal();openScrcpy()">
            <svg class="ic"><use href="#i-external"/></svg>${esc(t('screen.in_window'))}</button>`
        + (busy ? '' : `<button class="primary" onclick="closeModal();if(!S.liveControl)toggleLiveControl()">
            ${esc(t('screen.enable_control'))}</button>`);
    openModal();
}

function streamUrl() {
    const kind = S.streaming ? 'stream' : 'frame';
    /* live — кадры чаще: на экране работают руками (пульт, запись, ожидание) */
    const live = S.streaming && canInteract() ? '&live=1' : '';
    return `/api/devices/${S.active}/${kind}?t=${Date.now()}${live}`;
}

/* Узел <img> пересоздаётся, а не переиспользуется: смена src не рвёт
   MJPEG-соединение и исчерпывает лимит сокетов. См. docs/GOTCHAS.md. */
const EMPTY_NONE = ['Телефон не выбран',
    'Откройте телефон на ферме.'];
const EMPTY_OFFLINE = ['Телефон не в сети',
    'Проверьте кабель или Wi-Fi — экран появится сам.'];

/* Офлайн-устройство сервер отвергает 409, и <img> молча оставался пустым —
   читалось как «трансляция сломалась». Неизвестное устройство (заход по
   ссылке до первого опроса) не считаем офлайном: пусть попробует. */
function activeOffline() {
    const device = (S.devices || []).find(d => d.serial === S.active);
    return !!device && !device.online;
}

function startStream() {
    const empty = $('scrEmpty');
    /* «Выбрать на ферме» — только когда телефон не выбран: у открытого
       телефона кнопка звала бы туда, откуда только что пришли. */
    $('scrEmptyFleet').hidden = !!S.active;
    const img = document.createElement('img');
    img.id = 'screen';
    img.alt = '';
    $('screen').replaceWith(img);
    S.streamOffline = activeOffline();

    if (!S.active || S.streamOffline) {
        const [title, text] = S.active ? EMPTY_OFFLINE : EMPTY_NONE;
        setText($('scrEmptyTitle'), title);
        setText($('scrEmptyText'), text);
        img.style.display = 'none';
        /* flex, а не block: .emptybig — флекс-колонка, и inline-стиль block
           убил бы и gap между рисунком и текстом, и центрирование. */
        empty.style.display = 'flex';
        $('scrLoad').hidden = true;
        syncInteractive();
        return;
    }

    empty.style.display = 'none';
    img.style.display = 'block';
    /* Пока не пришёл первый кадр — крутилка, а не чёрное поле. */
    $('scrLoad').hidden = false;
    img.onload = () => { $('scrLoad').hidden = true; };
    /* Поток не пришёл у телефона «в сети» — раньше оставалось пустое
       чёрное поле. Говорим, что случилось, и даём повторить. */
    img.onerror = () => {
        img.classList.add('dead');
        img.style.display = 'none';
        $('scrLoad').hidden = true;
        setText($('scrEmptyTitle'), 'Экран не пришёл');
        $('scrEmptyText').innerHTML = 'Телефон занят или только подключился.'
            + '<br><button class="sm" style="margin-top:var(--s3)" onclick="startStream()">Повторить</button>';
        empty.style.display = 'flex';
    };
    img.src = streamUrl();
    syncInteractive();
}

/* Меняем иконку и подпись по отдельности: textContent на всей кнопке снёс бы
   вложенный <svg> вместе с иконкой. */
function syncStreamBtn() {
    const button = $('btnStream');
    button.querySelector('use').setAttribute('href', S.streaming ? '#i-pause' : '#i-play');
    setText(button.querySelector('span'), S.streaming ? 'стоп-кадр' : 'смотреть');
    button.title = S.streaming
        ? 'Заморозить кадр'
        : 'Возобновить трансляцию';
}

function toggleStream() {
    S.streaming = !S.streaming;
    syncStreamBtn();
    startStream();
}

async function openScrcpy() {
    if (!S.active) return;
    try {
        toast((await post(`/api/devices/${S.active}/scrcpy`)).message, 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
}

async function act(payload) {
    if (!S.active) {
        toast('телефон не выбран', 'bad');
        return;
    }
    /* «Указать на экране» в конструкторе: нажатие выбирает ориентир шага и
       на телефон не уходит. */
    if (window.REC && REC.on && REC.scopePick && window.recScopeTap && recScopeTap(payload)) return;
    /* То же для цели блока «пока не найдёшь» / «если на экране» — и без записи. */
    if (window.REC && REC.blockPick != null && window.recBlockPickTap && await recBlockPickTap(payload)) return;
    try {
        const result = await (syncRoute(payload) || actSend(S.active, payload));
        /* Единственная точка перехвата: через act() идут не только жесты,
           но и launch/stop/url со вкладки «Устройство». */
        if (window.REC && REC.on) recNote(payload);
        return result;
    } catch (e) {
        toast(e.message, 'bad');
        throw e;
    }
}

/* Жесты одного телефона уходят по очереди: два параллельных запроса к
   серверу могли прийти не в том порядке (тап обгонял свайп). Сервер на долгие
   жесты отвечает сразу, так что очередь не копит задержку. Сбой одного
   жеста цепочку не рвёт. */
let actChain = Promise.resolve();
const ACT_DEBUG = /[?&]debug\b/.test(location.search);

function actSend(serial, payload) {
    const run = () => {
        const t0 = performance.now();
        return fetch(`/api/devices/${serial}/action`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
            keepalive: true,
        }).then(async response => {
            const body = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'не получилось');
            if (ACT_DEBUG) {
                console.log(`[farm] ${payload.type}: ${Math.round(performance.now() - t0)} мс туда-обратно, `
                    + `сервер ${response.headers.get('Server-Timing') || '?'}`);
            }
            return body;
        }, () => {
            throw new Error('нет связи с фермой — программа фермы запущена?');
        });
    };
    const next = actChain.then(run, run);
    actChain = next.catch(() => {});
    return next;
}

function sendKey(name) {
    return act({type: 'key', name});
}

function doUnlock() {
    return act({type: 'unlock'});
}

function sendText(clear) {
    const field = $('textInput');
    if (!field.value) return;
    act({type: 'text', value: field.value, clear: !!clear});
    field.value = '';
}

/* Пока мышь зажата, MJPEG не показывает жест — кадр придёт раз в
   FARM_STREAM_FPS, а не за движением курсора. Экран в эти секунды выглядел
   мёртвым: палец двигается, а видно только неподвижную картинку. Этот
   штрих — чисто локальная отрисовка, ни одного запроса к устройству, только
   чтобы палец на экране не казался бездействующим до самого отпускания. */
function gestureTrailStart(stage, from) {
    const el = document.createElement('div');
    el.className = 'gesture-trail';
    el.innerHTML = '<i class="gesture-dot gesture-from"></i>'
        + '<i class="gesture-line"></i><i class="gesture-dot gesture-to"></i>';
    stage.appendChild(el);
    gestureTrailMove(el, from, from);
    return el;
}

function gestureTrailMove(el, from, to) {
    if (!el) return;
    const dx = to.x - from.x, dy = to.y - from.y;
    const dist = Math.hypot(dx, dy);
    const angle = Math.atan2(dy, dx) * 180 / Math.PI;
    const line = el.querySelector('.gesture-line');
    line.style.cssText = `left:${from.x}px;top:${from.y}px;width:${dist}px;`
        + `transform:rotate(${angle}deg)`;
    const start = el.querySelector('.gesture-from');
    start.style.left = from.x + 'px';
    start.style.top = from.y + 'px';
    const end = el.querySelector('.gesture-to');
    end.style.left = to.x + 'px';
    end.style.top = to.y + 'px';
}

function gestureTrailEnd(el) {
    if (!el) return;
    el.classList.add('fade');
    setTimeout(() => el.remove(), 200);
}

/* Тап виден сразу, не дожидаясь кадра с телефона: без отклика экран
   казался зависшим на те десятые секунды, пока едет ответ. */
function tapRipple(stage, at) {
    if (!at) return;
    const el = document.createElement('i');
    el.className = 'tap-ripple';
    el.style.left = at.x + 'px';
    el.style.top = at.y + 'px';
    stage.appendChild(el);
    setTimeout(() => el.remove(), 450);
}

/* Слушаем .stage, а не сам <img>: startStream() пересоздаёт узел #screen. */
(function initGestures() {
    const stage = document.querySelector('.stage');
    let down = null, timer = null, longFired = false, trail = null, downPx = null, downPx0 = null;

    const normalize = ev => {
        const rect = $('screen').getBoundingClientRect();
        return {
            x: Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width)),
            y: Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height)),
        };
    };
    /* Тот же клик, но в пикселях самой .stage — трек ведём по ней, а не
       по нормализованным долям экрана, иначе линия рисовалась бы криво на
       любом масштабе картинки. */
    const stagePoint = ev => {
        const rect = stage.getBoundingClientRect();
        return {x: ev.clientX - rect.left, y: ev.clientY - rect.top};
    };

    stage.addEventListener('mousedown', ev => {
        if (ev.target.id !== 'screen' || !S.active) return;
        ev.preventDefault();
        if (!canInteract()) {
            offerScrcpy();
            return;
        }
        down = {...normalize(ev), t: Date.now()};
        longFired = false;
        downPx = stagePoint(ev);
        downPx0 = downPx;
        trail = gestureTrailStart(stage, downPx);
        timer = setTimeout(() => {
            longFired = true;
            act({type: 'long_tap', x: down.x, y: down.y, duration: LONG_TAP_DURATION});
        }, LONG_TAP_MS);
    });

    window.addEventListener('mousemove', ev => {
        if (!down || !trail) return;
        gestureTrailMove(trail, downPx, stagePoint(ev));
        /* Палец поехал — это прокрутка, а не долгое нажатие: без этого
           медленный скролл дольше 600 мс срабатывал как long_tap. */
        if (!longFired) {
            const at = normalize(ev);
            if (Math.hypot(at.x - down.x, at.y - down.y) > SWIPE_MIN_DISTANCE) clearTimeout(timer);
        }
    });

    window.addEventListener('mouseup', ev => {
        if (!down) return;
        clearTimeout(timer);
        gestureTrailEnd(trail);
        trail = null;
        downPx = null;
        const up = normalize(ev);
        const distance = Math.hypot(up.x - down.x, up.y - down.y);
        const elapsed = (Date.now() - down.t) / 1000;

        if (!longFired) {
            if (distance > SWIPE_MIN_DISTANCE) {
                act({
                    type: 'swipe', x1: down.x, y1: down.y, x2: up.x, y2: up.y,
                    duration: Math.min(SWIPE_MAX_DURATION, Math.max(SWIPE_MIN_DURATION, elapsed))
                });
            } else {
                tapRipple(stage, downPx0);
                act({type: 'tap', x: down.x, y: down.y});
            }
        }
        down = null;
    });
})();

/* ------------------------------------------------------------ живая клавиатура */

const LIVE_KEYS = {queue: [], timer: null, busy: false, sink: null, state: null};
const LIVE_KEYS_DELAY_MS = 60;

function liveKeysOn() {
    const box = $('kbCapture');
    return !!(box && box.checked && S.active && canInteract());
}

function liveKeysPush(op) {
    if (!op) return;
    liveKeyMerge(LIVE_KEYS.queue, op);
    if (!LIVE_KEYS.timer) LIVE_KEYS.timer = setTimeout(liveKeysFlush, LIVE_KEYS_DELAY_MS);
}

/* Одна пачка за раз и строго по порядку: следующая уходит после ответа. */
async function liveKeysFlush() {
    LIVE_KEYS.timer = null;
    if (LIVE_KEYS.busy || !LIVE_KEYS.queue.length) return;
    LIVE_KEYS.busy = true;
    const queue = LIVE_KEYS.queue;
    LIVE_KEYS.queue = [];
    try {
        for (const payload of liveKeyActions(queue)) {
            /* Запись шагов знает только одиночные нажатия. */
            const times = payload.count && window.REC && REC.on ? payload.count : 1;
            for (let i = 0; i < times; i++) {
                await act(times > 1 ? {type: 'key', name: payload.name} : payload);
            }
        }
    } catch (e) {
        LIVE_KEYS.queue = [];   // act() уже сказал об ошибке; хвост не досылаем
    }
    LIVE_KEYS.busy = false;
    if (LIVE_KEYS.queue.length) liveKeysFlush();
}

/* Скрытое поле ловит ввод, который keydown не отдаёт: кириллицу и IME,
   виртуальные клавиатуры планшетов, вставку. Фокус держим на нём, пока
   «Живая клавиатура» включена. */
function liveKeysSink() {
    if (LIVE_KEYS.sink) return LIVE_KEYS.sink;
    const sink = document.createElement('textarea');
    sink.id = 'kbSink';
    sink.className = 'kb-sink';
    sink.setAttribute('aria-label', t('device.zhivaya_klaviatura'));
    sink.autocapitalize = 'off';
    sink.autocomplete = 'off';
    sink.spellcheck = false;
    document.body.appendChild(sink);
    sink.addEventListener('keydown', ev => {
        if (!liveKeysOn()) return;
        const op = liveKeyOp(ev);
        if (op && op !== 'defer' && op.k === 'key') {
            ev.preventDefault();
            liveKeysPush(op);
        }
        /* символы — через input: так работают и IME, и раскладки */
    });
    sink.addEventListener('input', ev => {
        if (ev.isComposing) return;   // дождёмся compositionend
        const op = liveKeysOn() ? liveInputOp(ev.inputType, ev.data || sink.value) : null;
        sink.value = '';
        liveKeysPush(op);
    });
    sink.addEventListener('compositionend', ev => {
        if (liveKeysOn() && ev.data) liveKeysPush({k: 'text', v: ev.data});
        sink.value = '';
    });
    sink.addEventListener('paste', ev => {
        if (!liveKeysOn()) return;
        ev.preventDefault();
        const text = ev.clipboardData && ev.clipboardData.getData('text');
        if (text) liveKeysPush({k: 'text', v: text});
    });
    sink.addEventListener('focus', liveKeysSyncState);
    sink.addEventListener('blur', () => setTimeout(liveKeysSyncState, 0));
    LIVE_KEYS.sink = sink;
    return sink;
}

/* Подпись рядом с галочкой: видно, ловит ли страница ввод прямо сейчас. */
function liveKeysSyncState() {
    const label = $('kbLabel');
    if (!label) return;
    let badge = label.querySelector('.kb-state');
    if (!badge) {
        badge = document.createElement('span');
        badge.className = 'kb-state';
        label.appendChild(badge);
    }
    const on = $('kbCapture').checked;
    const catching = on && liveKeysOn() && document.activeElement === LIVE_KEYS.sink;
    label.dataset.state = !on ? '' : catching ? 'on' : 'idle';
    setText(badge, !on ? '' : catching ? t('device.kb_lovit_vvod') : t('device.kb_nazhmite_na_ekran'));
}

function liveKeysFocus() {
    if (liveKeysOn()) liveKeysSink().focus({preventScroll: true});
    liveKeysSyncState();
}

document.addEventListener('change', ev => {
    if (ev.target.id !== 'kbCapture') return;
    if (ev.target.checked) liveKeysFocus();
    else if (LIVE_KEYS.sink) LIVE_KEYS.sink.blur();
    liveKeysSyncState();
});
/* Клик по экрану возвращает ввод в телефон. */
document.querySelector('.stage').addEventListener('mouseup', () => setTimeout(liveKeysFocus, 0));

/* Запасной путь: фокус не на скрытом поле (клик по кнопке, вкладка). Чекбокс
   и кнопки не мешают — раньше после клика по «Живой клавиатуре» фокус
   оставался на ней, и каждое нажатие отбрасывалось как «ввод в поле». */
const LIVE_TEXT_INPUTS = new Set(['text', 'search', 'password', 'email', 'url', 'tel', 'number']);

function typingInField(el) {
    if (!el || el === LIVE_KEYS.sink) return false;
    if (el.isContentEditable || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true;
    return el.tagName === 'INPUT' && LIVE_TEXT_INPUTS.has((el.type || 'text').toLowerCase());
}

document.addEventListener('keydown', ev => {
    if (!liveKeysOn() || ev.target === LIVE_KEYS.sink) return;
    if ($('modal').classList.contains('on')) return;
    if (typingInField(ev.target)) return;
    const op = liveKeyOp(ev);
    if (!op) return;
    if (op === 'defer') {
        liveKeysFocus();   // следующий символ придёт в скрытое поле
        return;
    }
    ev.preventDefault();   // и Пробел не переключит чекбокс
    liveKeysPush(op);
});

document.addEventListener('paste', ev => {
    if (!liveKeysOn() || ev.target === LIVE_KEYS.sink || typingInField(ev.target)) return;
    const text = ev.clipboardData && ev.clipboardData.getData('text');
    if (!text) return;
    ev.preventDefault();
    liveKeysPush({k: 'text', v: text});
});

/* Экран телефона погашен или заблокирован: поток показывает старый или
   чёрный кадр, и казалось, что телефон «завис». Говорим, что с ним, и
   даём разбудить одной кнопкой. Состояние приходит с опросом телефонов. */
function syncScreenSleep() {
    const box = $('scrSleep');
    if (!box) return;
    const device = (S.devices || []).find(d => d.serial === S.active);
    const screen = device && device.online ? device.screen : null;
    const mode = !screen ? '' : !screen.on ? 'off' : screen.locked ? 'locked' : '';
    if (box.dataset.mode === mode) return;
    box.dataset.mode = mode;
    box.hidden = !mode;
    setText($('scrSleepTitle'), mode === 'off' ? t('device.ekran_vyklyuchen')
        : mode === 'locked' ? t('device.telefon_zablokirovan') : '');
    setText(box.querySelector('button'), mode === 'locked' ? t('device.razblokirovat') : t('device.razbudit'));
    const stage = document.querySelector('.stage');
    if (stage) stage.classList.toggle('asleep', mode === 'off');
}
