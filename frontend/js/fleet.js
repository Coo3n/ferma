'use strict';

/* Плитка фермы: все устройства разом, с живым превью экрана.

   Плитки обновляются поштучно, а не переписыванием innerHTML. Это не
   украшательство: в каждой плитке живёт <img>, который сам себя перезагружает
   по кругу. Полная перерисовка раз в 2.5 с убивала бы эти картинки на
   полпути, и превью не успевало бы появиться ни разу.

   Превью тактируются сами от себя: следующий кадр заказывается только после
   того, как приехал предыдущий. Поэтому медленное устройство тормозит лишь
   свою плитку, а не копит очередь запросов, и двадцать телефонов не уходят
   в сеть одной пачкой. */

/* Период обновления превью зависит от того, сколько плиток видно: 10 на
   экране — раз в ~1.5 с, 40 на мелких плитках — раз в ~4 с. Жёсткие 4 с
   были медленно на крупных плитках и всё равно не спасали на мелких. */
const THUMB_PERIOD_MIN_MS = 1500;
const THUMB_PERIOD_MAX_MS = 5000;
const THUMB_MS_PER_VISIBLE = 100;
const THUMB_JITTER_MS = 600;

function thumbPeriod() {
    const visible = [...FLEET.tiles.values()].filter(el => {
        const img = el.querySelector('img');
        return img && img._visible !== false;
    }).length;
    return Math.min(THUMB_PERIOD_MAX_MS, Math.max(THUMB_PERIOD_MIN_MS, visible * THUMB_MS_PER_VISIBLE));
}
const THUMB_BACKOFF_MS = 15000;
/* Живой adb на настоящих телефонах по USB время от времени пропускает
   устройство в одном опросе — registry сам это логирует как «устройство
   пропало» и чаще всего видит его обратно на следующем цикле. Без запаса
   превью гасло бы от каждого такого разового пропуска, хотя телефон никуда
   не делся. Терпим 2 подряд неудачи — офлайн, увиденный дважды, а не мигнувший. */
const OFFLINE_GRACE_POLLS = 2;
const THUMB_ERROR_GRACE = 2;

const DENSITY_KEY = 'farm.density';

window.FLEET = {
    tiles: new Map(),   // serial -> элемент плитки
    filter: 'all',
    group: '',          // фильтр по группе, '' — все
    tag: '',            // фильтр по тегу, '' — все
    density: ['l', 'm', 's'].includes(store.get(DENSITY_KEY, 'l')) ? store.get(DENSITY_KEY, 'l') : 'l',
};

/* Размер плиток: крупно — разглядеть экран, мелко — 40 телефонов без
   прокрутки. Помним в браузере: это привычка человека, а не данные фермы. */
function setDensity(value) {
    FLEET.density = value;
    store.set(DENSITY_KEY, value);
    applyDensity();
}

function applyDensity() {
    const box = $('fleet');
    if (box) box.dataset.density = FLEET.density;
    document.querySelectorAll('[data-density-btn]').forEach(b => {
        const on = b.dataset.densityBtn === FLEET.density;
        b.classList.toggle('on', on);
        b.setAttribute('aria-pressed', String(on));
    });
}

const FLEET = window.FLEET;

/* Кнопки размера подсвечиваем сразу, не дожидаясь первого ответа фермы:
   applyDensity раньше звали только из renderFleet, и пока телефоны
   загружались (или сеть тормозила), ни один из L/M/S не был выбран. */
applyDensity();

/* ------------------------------------------------------------------ превью */

function thumbAllowed(img) {
    return (S.view === 'fleet' || S.view === 'jobs') && !document.hidden
        && img._visible !== false;
}

/* На 40 телефонах снимать экран всем подряд — это ~10 screencap в секунду
   на ферму, и половина кадров уходит в плитки за краем прокрутки. Снимаем
   только видимые; плитка, вернувшаяся в кадр, обновляется сразу. */
const thumbSeen = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    entries.forEach(e => {
        const img = e.target;
        const was = img._visible;
        img._visible = e.isIntersecting;
        if (e.isIntersecting && was === false && img.onload) thumbSchedule(img, 0);
    });
}, {rootMargin: '200px'}) : null;

function thumbSchedule(img, delay) {
    clearTimeout(img._timer);
    img._timer = setTimeout(() => thumbTick(img), delay);
}

/* Очередной кадр по таймеру. Уход с фермы и сворачивание вкладки съёмку
   останавливают: иначе ферма дёргала бы screencap на всех телефонах в фоне.
   Проверка стоит именно здесь, а не в thumbLoad(), — см. thumbArm(). */
function thumbTick(img) {
    if (!img.isConnected) return;
    if (!thumbAllowed(img)) {
        thumbSchedule(img, 1000);   // ждём возвращения, не снимая кадр
        return;
    }
    thumbLoad(img);
}

/* Кадр грузим в стороне и ставим, только когда он приехал. Сбой загрузки
   прямо в <img> ломает картинку — старый кадр пропадает, и плитка стояла
   пустой до следующей попытки (15 с), хотя THUMB_ERROR_GRACE обещал
   переждать одиночную заминку. Удачный кадр отдаётся из кэша
   (max-age), поэтому подстановка мгновенная и сама зовёт img.onload. */
function thumbLoad(img) {
    const url = `/api/devices/${img.dataset.serial}/thumb?t=${Date.now()}`;
    const next = new Image();
    next.onload = () => {
        if (img.isConnected && img.onload) img.src = url;
    };
    next.onerror = () => {
        if (img.isConnected && img.onerror) img.onerror();
    };
    next.src = url;
}

/* Последний показанный кадр каждого телефона. При перезагрузке страницы
   плитка сразу ставит его (браузер отдаёт из кэша) — без него все 40 экранов
   гасли бы до первого свежего screencap и загорались вразнобой. */
const THUMB_LAST_KEY = 'fleet.lastThumbs';
const thumbLast = (() => {
    try { return JSON.parse(sessionStorage.getItem(THUMB_LAST_KEY)) || {}; }
    catch { return {}; }
})();
window.addEventListener('pagehide', () => {
    try { sessionStorage.setItem(THUMB_LAST_KEY, JSON.stringify(thumbLast)); } catch {}
});

/* Первый кадр грузим безусловно, не спрашивая про видимость.

   Страница, открытая в фоновой вкладке, стартует с document.hidden === true,
   и проверка на этом месте оставила бы всю ферму с пустыми заглушками до
   первого переключения на вкладку. Кадр стоит одного screencap — дешевле,
   чем показать пользователю ферму без единого экрана. */
function thumbArm(img, serial) {
    img.dataset.serial = serial;
    img._errStreak = 0;
    if (thumbSeen) thumbSeen.observe(img);
    img.onload = () => {
        img._errStreak = 0;
        img.classList.add('ready');
        if (img.src.includes('/thumb?')) thumbLast[serial] = img.src;
        thumbSchedule(img, thumbPeriod() + Math.random() * THUMB_JITTER_MS);
    };
    img.onerror = () => {
        img._errStreak++;
        // Одиночный сбой кадра не гасит превью — иначе плитка мигала бы
        // placeholder'ом от любой заминки adb. Прячем картинку, только если
        // сбой повторился: тогда это не заминка, а действительно нет кадра.
        if (img._errStreak >= THUMB_ERROR_GRACE) img.classList.remove('ready');
        thumbSchedule(img, THUMB_BACKOFF_MS);
    };
    const cached = thumbLast[serial];
    if (cached) {
        // Класс ставим до первой отрисовки — плитка не проходит через
        // прозрачность и не мигает. Свежий кадр придёт по обычному таймеру.
        img.classList.add('ready');
        img.src = cached;
        return;
    }
    /* Первый кадр — с разбросом: 40 плиток при открытии фермы не должны
       дёрнуть screencap одной пачкой. */
    thumbSchedule(img, Math.random() * THUMB_JITTER_MS);
}

function thumbStop(img) {
    clearTimeout(img._timer);
    if (thumbSeen) thumbSeen.unobserve(img);
    img.onload = img.onerror = null;
    img.removeAttribute('src');
}

/* Аккаунт телефона в бане или просит вход — видно на ферме сразу, а не
   по упавшему сценарию. Отсутствие аккаунта не показываем: нужен он или
   нет, зависит от сценария — это скажет окно запуска. */
function tileAccountFlag(node, accounts) {
    if (!node) return;
    const banned = accounts.filter(a => a.status === 'banned');
    const login = accounts.filter(a => a.status === 'login');
    const bad = banned.length ? banned : login;
    node.hidden = !bad.length;
    if (!bad.length) return;
    const names = bad.map(a => PLATFORM_NAMES[a.platform] || a.platform).join(', ');
    const text = banned.length ? `бан ${names}` : `вход ${names}`;
    node.className = 'accflag ' + (banned.length ? 'bad' : 'warn');
    setText(node, text);
    node.title = banned.length ? `Аккаунт в бане: ${names}` : `Аккаунт просит войти заново: ${names}`;
}

/* --------------------------------------------------------------- плитка */

function tileCreate(serial) {
    const el = document.createElement('article');
    el.className = 'tile';
    el.dataset.serial = serial;
    el.tabIndex = -1;   // остановку Tab раздаёт fleetRove — одна на всю сетку
    el.setAttribute('aria-keyshortcuts', 'Enter Space I F2 Escape');
    el.innerHTML = `
    <div class="shot">
      <div class="phone">
        <span class="notch"></span>
        <div class="glass">
          <div class="noshot"><svg class="ic"><use href="#i-moon"/></svg><span></span></div>
          <div class="sleepy" hidden><svg class="ic"><use href="#i-moon"/></svg><span></span></div>
        </div>
      </div>
      <span class="flag" hidden></span>
      <button class="pick" tabindex="-1" aria-pressed="false"><svg class="ic"><use href="#i-check"/></svg></button>
      <div class="acts">
        <button class="js-info" tabindex="-1" title="Подробнее"><svg class="ic"><use href="#i-info"/></svg></button>
        <button class="js-edit" tabindex="-1"><svg class="ic"><use href="#i-pencil"/></svg></button>
      </div>
      <span class="open"><svg class="ic"><use href="#i-expand"/></svg>Открыть</span>
    </div>
    <div class="cap">
      <div class="top"><span class="dot"></span><span class="nm"></span><span class="accflag" hidden></span><span class="os" hidden></span></div>
      <div class="metrics tnum"></div>
      <div class="alert" hidden><svg class="ic"><use href="#i-alert"/></svg><span></span></div>
    </div>`;

    el.addEventListener('click', ev => {
        /* Клик сразу после рамки — это конец выделения, а не «открыть». */
        if (MARQUEE.justDone) return;
        if (ev.metaKey || ev.ctrlKey) {
            toggleSel(serial, !S.selected.has(serial));
            FLEET.anchor = serial;
            return renderFleet();
        }
        if (ev.shiftKey && FLEET.anchor) return selectRange(FLEET.anchor, serial);
        openDevice(serial);
    });
    /* Клавиши плитки — в fleetKeys, одним обработчиком на сетку. */
    el.querySelector('.pick').addEventListener('click', ev => {
        ev.stopPropagation();
        if (ev.shiftKey && FLEET.anchor) return selectRange(FLEET.anchor, serial);
        toggleSel(serial, !S.selected.has(serial));
        FLEET.anchor = serial;
        renderFleet();
    });
    el.querySelector('.js-info').addEventListener('click', ev => {
        ev.stopPropagation();
        deviceInfo(serial);
    });
    el.querySelector('.js-edit').addEventListener('click', ev => {
        ev.stopPropagation();
        tileEdit(serial);
    });
    return el;
}

function tileEdit(serial) {
    if (S.hidden.has(serial)) unhideDevice(serial);
    else renameDevice(serial);
}

/* Точечное обновление: трогаем только то, что изменилось. Сравнение с
   прошлым состоянием держим на самом узле — так плитка сама помнит, что
   уже нарисовано, и не приходится вести отдельный реестр. */
function tileUpdate(el, device, ghost) {
    const status = statusClass(device);
    const selected = S.selected.has(device.serial);

    el.classList.toggle('sel', selected);
    el.classList.toggle('active', S.active === device.serial);
    el.classList.toggle('off', !device.online);
    el.classList.toggle('ghost', !!ghost);

    const pick = el.querySelector('.pick');
    pick.setAttribute('aria-pressed', String(selected));
    pick.setAttribute('aria-label',
        (selected ? 'Снять выбор: ' : 'Выбрать: ') + device.name);
    pick.disabled = !device.online;

    const edit = el.querySelector('.js-edit');
    edit.title = ghost ? 'Вернуть в список' : 'Переименовать';
    edit.setAttribute('aria-label', edit.title + ': ' + device.name);
    setHref(edit.querySelector('use'), ghost ? '#i-undo' : '#i-pencil');
    el.querySelector('.js-info').setAttribute('aria-label', 'Подробнее: ' + device.name);

    el.querySelector('.dot').className = 'dot ' + status;
    el.dataset.st = status;   // рамка и полоса состояния: норма тихая, исключения громкие
    setText(el.querySelector('.nm'), device.name);
    el.querySelector('.nm').title = device.name;
    /* На мелких плитках имя обрезается — полное имя и состояние в подсказке. */
    el.title = `${device.name} — ${statusWord(device)}`;
    tileAccountFlag(el.querySelector('.accflag'), device.accounts || []);

    const os = el.querySelector('.os');
    os.hidden = !device.android;
    if (device.android) setText(os, 'A' + device.android);

    tileMetrics(el.querySelector('.metrics'), device);

    // Флаг поверх превью: занятость и ошибку видно, даже если экран чёрный.
    const flag = el.querySelector('.flag');
    if (deviceHeld(device)) {
        flag.hidden = false;
        flag.className = 'flag held';
        setText(flag, 'ждёт решения');
    } else if (device.busy_job) {
        flag.hidden = false;
        flag.className = 'flag busy';
        setText(flag, 'занято');
    } else if (device.warnings.length && device.online) {
        flag.hidden = false;
        flag.className = 'flag err';
        setText(flag, 'тревога');
    } else {
        flag.hidden = true;
    }

    const alert = el.querySelector('.alert');
    const text = device.warnings.join('; ');
    alert.hidden = !text;
    if (text) setText(alert.querySelector('span'), text);

    // Превью заводим только у устройств в сети — у остальных кадра нет.
    const shot = el.querySelector('.shot');
    const glass = shot.querySelector('.glass');

    // Корпус повторяет пропорцию настоящего экрана — кадр ложится в рамку без
    // чёрных полей. Размеры приходят не сразу, до них держим обычные 9:19.
    const phone = shot.querySelector('.phone');
    const ratio = device.width && device.height ? `${device.width} / ${device.height}` : '';
    if (phone.dataset.ar !== ratio) {
        phone.dataset.ar = ratio;
        phone.style.setProperty('--ar', ratio || '9 / 19');
    }
    let img = shot.querySelector('img');
    if (device.online && !ghost) {
        el._offlineStreak = 0;
        if (!img) {
            img = document.createElement('img');
            img.alt = '';
            glass.prepend(img);
            thumbArm(img, device.serial);
        }
        setText(shot.querySelector('.noshot span'), '');
        tileScreenState(shot, device.screen);
    } else {
        tileScreenState(shot, null);
        // Скрытое явным действием рвём сразу; пропажу из опроса — только если
        // повторилась: настоящий USB-телефон мелькает офлайном сам по себе,
        // и рвать живое превью от каждого такого мига — источник «мигнуло и
        // пропало», с которым эта отсрочка и борется.
        el._offlineStreak = ghost ? OFFLINE_GRACE_POLLS : (el._offlineStreak || 0) + 1;
        if (img && el._offlineStreak >= OFFLINE_GRACE_POLLS) {
            thumbStop(img);
            img.remove();
        }
        const unauth = device.state === 'unauthorized';
        setText(shot.querySelector('.noshot span'), unauth ? 'не авторизовано' : 'офлайн');
        // Погасший экран и запертый — разные беды: у первой ждут, у второй
        // идут подтверждать ключ на телефоне.
        setHref(shot.querySelector('.noshot use'), unauth ? '#i-unlock' : '#i-moon');
    }
    el.setAttribute('aria-label',
        `${device.name}, ${statusWord(device)}. Открыть рабочее место`);
}

/* Погасший экран отдаёт последний кадр — без плашки плитка выглядела так,
   будто телефон включён. Выключен: кадр приглушаем и пишем словами.
   Заблокирован при горящем экране: кадр честный (виден экран блокировки),
   хватает метки. */
function tileScreenState(shot, screen) {
    const box = shot.querySelector('.sleepy');
    if (!box) return;
    const mode = !screen ? '' : !screen.on ? 'off' : screen.locked ? 'locked' : '';
    if (box.dataset.mode === mode) return;
    box.dataset.mode = mode;
    box.hidden = !mode;
    shot.classList.toggle('asleep', mode === 'off');
    setText(box.querySelector('span'), mode === 'off' ? t('fleet.ekran_vyklyuchen')
        : mode === 'locked' ? t('fleet.zablokirovan') : '');
    setHref(box.querySelector('use'), mode === 'locked' ? '#i-unlock' : '#i-moon');
}

/* Тот же href у <use> не переписываем: Chrome на любую запись атрибута
   пересобирает клон иконки, и на перерисовке фермы значки подмигивали. */
function setHref(use, href) {
    if (use && use.getAttribute('href') !== href) use.setAttribute('href', href);
}

function statusWord(device) {
    if (!device.online) return device.state === 'unauthorized' ? 'не авторизовано' : 'офлайн';
    if (deviceHeld(device)) return 'ждёт вашего решения';
    if (device.busy_job) return 'занято запуском';
    return device.warnings.length ? 'есть тревоги' : 'в сети';
}

/* Строка метаданных в виде значков: заряд, температура, способ подключения.

   Раньше это была строчка «100% · 25° · A17» — одинаковая серая каша, в
   которой низкий заряд ничем не выделялся. Теперь у каждого числа свой знак,
   а порог заряда и перегрев красят сами себя. Версия Android уехала в ярлык
   рядом с именем: её ищут отдельно. */
function tileMetrics(box, device) {
    if (!device.online) {
        const key = 'sn:' + device.serial;
        if (box.dataset.key !== key) {
            box.dataset.key = key;
            /* Серийный номер человеку ничего не говорит — только в подсказке. */
            box.innerHTML = `<span class="m sn" title="${esc(device.serial)}">${esc(statusWord(device))}</span>`;
        }
        return;
    }

    const bits = [];
    if (device.group) bits.push(esc(device.group));
    const tags = device.tags || [];
    if (tags.length) {
        bits.push(`<span class="m tags" title="Теги: ${esc(tags.join(', '))}">${
            tags.slice(0, 2).map(tg => `<span class="tagchip" role="button" tabindex="-1"
                title="${esc(t('fleet.pokazat_tolko_teg', {teg: tg}))}"
                onclick="event.stopPropagation();fleetShowTag(this.textContent)">${esc(tg)}</span>`).join('')}${
            tags.length > 2 ? `<span class="tagmore">+${tags.length - 2}</span>` : ''}</span>`);
    }
    if (device.battery != null) {
        const charging = !!device.charging;
        const tone = charging ? 'chg'
            : device.battery <= BATTERY_LOW ? 'low'
                : device.battery <= BATTERY_MID ? 'mid' : '';
        bits.push(`<span class="m ${tone}" title="Заряд${charging ? ', на зарядке' : ''}">
      <svg class="ic"><use href="#i-${charging ? 'zap' : 'battery'}"/></svg>${device.battery}%</span>`);
    }
    /* Температура — только когда это повод посмотреть: на каждой плитке она
       обрезалась на полуцифре и спорила с зарядом. */
    if (device.temperature != null && device.temperature >= 40) {
        const hot = device.temperature >= 42 ? 'hot' : '';
        bits.push(`<span class="m ${hot}" title="Температура батареи">
      <svg class="ic"><use href="#i-thermo"/></svg>${device.temperature.toFixed(0)}°</span>`);
    }
    // Способ подключения пишем словом: значок кабеля в 12 пикселей
    // превращался в закорючку, которую всё равно приходилось разгадывать.
    const wifi = device.network || device.transport === 'tcp' || /:\d+$/.test(device.serial);
    bits.push(`<span class="m link" title="${wifi ? 'Подключено по сети' : 'Подключено кабелем'}"
    >${wifi ? 'NET' : 'USB'}</span>`);

    // Разметку пересобираем только при изменении — иначе каждые 2.5 с
    // переписывали бы узлы под курсором и гасили подсказки.
    const key = bits.join('');
    if (box.dataset.key === key) return;
    box.dataset.key = key;
    box.innerHTML = key;
}

function fleetMeta(device) {
    const bits = [];
    if (device.battery != null) bits.push(device.battery + '%');
    if (device.temperature != null) bits.push(device.temperature.toFixed(0) + '°');
    if (device.android) bits.push('A' + device.android);
    return bits.join(' · ') || device.serial;
}

/* ------------------------------------------------------------------ список */

function passesFilter(device) {
    if (FLEET.group && device.group !== FLEET.group) return false;
    if (FLEET.tag && !(device.tags || []).includes(FLEET.tag)) return false;
    switch (FLEET.filter) {
        case 'online':
            return device.online;
        case 'busy':
            return !!device.busy_job;
        case 'warn':
            return !!attentionReason(device);   // как в счётчике «Требуют внимания»
        default:
            return true;
    }
}

function setFleetFilter(name) {
    FLEET.filter = name;
    renderFleet();
}

function renderFleet() {
    if (window.syncScreenSleep) syncScreenSleep();
    const box = $('fleet');
    if (!box) return;
    if (!S.devicesLoaded) return;   // ждём первый ответ фермы — см. pollDevices

    /* Фокус внутри сетки переживает опрос: перестановка плитки
       (insertBefore) и пропажа телефона роняют фокус на body, и человек
       со стрелками терял место каждые 2.5 с. */
    const hadFocus = box.contains(document.activeElement) ? document.activeElement : null;

    const found = S.devices.filter(d => matchesQuery(d) && passesFilter(d));
    const visible = found.filter(d => !S.hidden.has(d.serial));
    const hidden = found.filter(d => S.hidden.has(d.serial));
    const shown = visible.concat(S.showHidden ? hidden : []);

    // Убрать плитки исчезнувших устройств — вместе с их таймерами превью.
    for (const [serial, el] of FLEET.tiles) {
        if (shown.some(d => d.serial === serial)) continue;
        const img = el.querySelector('img');
        if (img) thumbStop(img);
        el.remove();
        FLEET.tiles.delete(serial);
    }

    shown.forEach((device, index) => {
        let el = FLEET.tiles.get(device.serial);
        if (!el) {
            el = tileCreate(device.serial);
            FLEET.tiles.set(device.serial, el);
            /* Каскад появления. Задержка только для первых восьми: дальше
               человек уже понял, что ферма наполняется, и ждать девятую
               плитку полсекунды — это не эффект, а тормоз. Класс снимаем
               по окончании, иначе повторный показ раздела проиграл бы
               анимацию заново на тех же узлах. */
            el.classList.add('fresh');
            el.style.animationDelay = Math.min(index, 8) * 40 + 'ms';
            el.addEventListener('animationend', () => {
                el.classList.remove('fresh');
                el.style.animationDelay = '';
            }, {once: true});
        }
        tileUpdate(el, device, S.hidden.has(device.serial));
        // Порядок держим сами: adb возвращает устройства отсортированными,
        // и плитка не должна прыгать мимо своего места.
        if (box.children[index] !== el) box.insertBefore(el, box.children[index] || null);
    });

    const rove = fleetRove();
    if (hadFocus && document.activeElement !== hadFocus) {
        const back = hadFocus.isConnected ? hadFocus : rove;
        if (back) back.focus({preventScroll: true});
    }

    renderFleetStats();
    setText($('fleetShown'), shown.length ? `${shown.length}` : '');
    renderFleetEmpty(box, shown.length);
    renderHiddenBar(hidden.length);
    renderRunbar();
    renderGroupFilter();
    renderTagFilter();
    applyDensity();
    renderSyncBar();
}

/* ------------------------------------------------------------------ обзор */

/* Четыре числа над сеткой. Считаем по всем устройствам, а не по отфильтрованным:
   обзор обязан оставаться неподвижной точкой отсчёта, иначе фильтр «Тревоги»
   показывал бы «тревог: 0» ровно там, где их только что нашли. */
/* Почему телефону нужен человек, или "" — всё в порядке. Не только заряд и
   перегрев: телефон без разрешения отладки и аккаунт в бане тоже ждут
   человека, а раньше в «Требуют внимания» их не было. */
/* Разряд/перегрев (power.py): словами, что будет и когда. */
function powerReason(device) {
    const p = device.online && device.power;
    if (!p) return '';
    if (p.state === 'rest') return t('power.otdyhaet', {n: p.resume});
    if (p.state === 'critical') {
        if (p.acked) return t('power.batareya', {n: p.level});
        const m = Math.ceil((p.grace_left || 0) / 60);
        return m > 0 ? t('power.sadits', {n: p.level, m}) : t('power.sadits_seychas', {n: p.level});
    }
    return '';
}

function powerAck(serial) {
    post(`/api/devices/${serial}/power/ack`).then(pollDevices).catch(e => toast(e.message, 'bad'));
}

function attentionReason(device) {
    if (deviceHeld(device)) return 'запуск ждёт вашего решения';
    if (device.state === 'unauthorized') return 'нажмите «Разрешить» на телефоне';
    const acc = device.accounts || [];
    const banned = acc.find(a => a.status === 'banned');
    if (banned) return `бан ${PLATFORM_NAMES[banned.platform] || banned.platform}`;
    const power = powerReason(device);
    if (power) return power;
    if (device.online && device.warnings.length) return device.warnings[0];
    const login = acc.find(a => a.status === 'login');
    if (login) return `вход ${PLATFORM_NAMES[login.platform] || login.platform}`;
    return '';
}

function fleetStats() {
    const all = S.devices.filter(d => !S.hidden.has(d.serial));
    const online = all.filter(d => d.online);
    const busy = all.filter(d => d.busy_job);
    const warn = all.filter(d => attentionReason(d));
    const batts = online.map(d => d.battery).filter(v => v != null);
    const avg = batts.length ? Math.round(batts.reduce((a, b) => a + b, 0) / batts.length) : null;
    const low = online.filter(d => d.battery != null && d.battery <= BATTERY_LOW).length;

    return [
        {
            key: 'all', icon: 'grid', label: 'Все', num: all.length,
            sub: all.length ? `${all.length - online.length} офлайн` : 'ни одного',
        },
        {
            key: 'online', icon: 'phone', label: 'В сети', num: online.length,
            sub: avg == null ? 'нет данных'
                : low ? `заряд ~${avg}% · ${low} садится` : `заряд ~${avg}%`,
        },
        {
            key: 'busy', icon: 'play', label: 'Заняты', num: busy.length,
            sub: busy.length ? 'идёт сценарий' : 'свободны',
        },
        {
            key: 'warn', icon: 'alert', label: 'Требуют внимания', num: warn.length,
            sub: warn.length ? 'см. ниже' : 'всё спокойно',
        },
    ];
}

/* Обзор фермы: четыре фильтра словами и — если есть — список тех, кому
   нужно внимание, по именам и с причиной. Полоса из сорока цветных клеток
   была непонятна без подписи: «что за зелёные квадраты». Человеку нужно не
   распределение, а «кто сломался и почему» — это и показываем. */
function renderFleetStats() {
    const box = $('fleetStats');
    if (!box) return;

    const cards = fleetStats();
    const trouble = S.devices.filter(d => !S.hidden.has(d.serial) && attentionReason(d));
    const key = cards.map(c => `${c.num}|${c.sub}`).join(';') + '#' + FLEET.filter + '#'
        + trouble.map(d => d.serial + attentionReason(d)).join(',');
    if (box.dataset.key === key) return;
    box.dataset.key = key;

    box.innerHTML = `<div class="hs-legend" role="group" aria-label="Показать">${cards.map(c => `
      <button class="hs-f hs-f--${c.key}${FLEET.filter === c.key ? ' on' : ''}${c.num ? '' : ' zero'}"
              aria-pressed="${FLEET.filter === c.key}" onclick="setFleetFilter('${c.key}')"
              title="${esc(c.sub)}"><i aria-hidden="true"></i>${esc(c.label)} <b>${c.num}</b></button>`).join('')}
    </div>
    ${trouble.length ? `<div class="hs-trouble" role="list" aria-label="Требуют внимания">${trouble.slice(0, 8).map(d => `
      <button class="hs-t" role="listitem" onclick="fleetJump('${esc(d.serial)}')"
              title="Показать плитку"><b>${esc(d.name)}</b> ${esc(attentionReason(d))}</button>${
          d.power && d.power.state === 'critical' && !d.power.acked ? `<button class="hs-t" onclick="powerAck('${esc(d.serial)}')"
              title="${esc(t('power.vizhu_title'))}">${esc(t('power.vizhu'))}</button>` : ''}`).join('')}
      ${trouble.length > 8 ? `<button class="hs-t more" onclick="setFleetFilter('warn')">ещё ${trouble.length - 8}</button>` : ''}
    </div>` : ''}`;
}

/* Клик по имени в списке внимания — к плитке: прокрутить и коротко подсветить. */
function fleetJump(serial) {
    if (FLEET.filter !== 'all') setFleetFilter('all');
    const el = FLEET.tiles.get(serial);
    if (!el) return;
    el.scrollIntoView({block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    el.classList.remove('flash');
    void el.offsetWidth;
    el.classList.add('flash');
    el.focus({preventScroll: true});
}

function renderFleetEmpty(box, count) {
    let empty = $('fleetEmpty');
    if (count) {
        if (empty) empty.remove();
        return;
    }
    if (!empty) {
        /* Без класса: .emptybig теперь на внутреннем div (его ставит
           emptyNoDevices/emptyFiltered), а этому узлу нужен только
           grid-column на всю строку — он висит на #fleetEmpty в CSS. */
        empty = document.createElement('div');
        empty.id = 'fleetEmpty';
        box.appendChild(empty);
    }

    // Перерисовываем только при смене текста: блок живёт под курсором, а
    // renderFleet зовут каждые 2.5 с.
    const html = S.devices.length ? emptyFiltered() : emptyNoDevices();
    if (empty._html === html) return;
    empty._html = html;
    empty.innerHTML = html;
}

/* Рисунок с кабелем — свой, не общий EMPTY_ART.device: там телефон просто
   не выбран, здесь его физически не воткнули, и кабель на картинке и есть
   ответ на вопрос «что делать». */
function emptyArt() {
    return `
  <svg class="art" viewBox="0 0 150 120" fill="none" aria-hidden="true">
    <rect x="49" y="9" width="52" height="86" rx="9"
          stroke="currentColor" stroke-width="2" opacity=".9"/>
    <rect x="55" y="16" width="40" height="66" rx="4"
          fill="currentColor" opacity=".08"/>
    <path d="M67 13h16" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity=".7"/>
    <circle cx="75" cy="88" r="2.4" fill="currentColor" opacity=".7"/>
    <path d="M75 95v9c0 6-5 8-11 8H30a8 8 0 0 1-8-8v-5"
          stroke="currentColor" stroke-width="2" stroke-linecap="round"
          stroke-dasharray="5 5" opacity=".55"/>
    <rect x="16" y="77" width="12" height="10" rx="2.5"
          stroke="currentColor" stroke-width="2" opacity=".8"/>
    <path d="M19 77v-4M25 77v-4" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" opacity=".8"/>
    <path d="M112 36h10M117 31v10" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" opacity=".45"/>
    <circle cx="128" cy="66" r="3" stroke="currentColor" stroke-width="2" opacity=".3"/>
  </svg>`;
}

/* Разметка та же, что у emptyBig() в core.js, но рисунок свой — поэтому
   собирается здесь, а не через общий помощник. */
function emptyNoDevices() {
    return `<div class="emptywrap"><div class="emptybig">${emptyArt()}
  <h3>Ферма пуста — ни одного телефона</h3>
  <p>Карточка появится сама, когда телефон подключится.</p>
  <ol>
    <li><b>1</b> Подключите телефон кабелем</li>
    <li><b>2</b> Включите «Отладка по USB»</li>
    <li><b>3</b> На телефоне нажмите «Разрешить»</li>
  </ol>
  <button class="sm" onclick="restartAdb(event)">
    <svg class="ic"><use href="#i-refresh"/></svg><span>Переподключить телефоны</span></button></div></div>`;
}

function emptyFiltered() {
    const hiddenOnly = !S.query && FLEET.filter === 'all';
    return `<div class="emptywrap"><div class="emptybig">${emptyArt()}
  <h3>${hiddenOnly ? 'Все телефоны скрыты' : 'Под фильтр ничего не подошло'}</h3>
  <p>${hiddenOnly
        ? 'Вернуть их можно в разделе ниже.'
        : 'Смените фильтр или очистите поиск.'}</p>
  ${hiddenOnly ? '' : `<button class="sm" onclick="resetFleetFilters()">
    <svg class="ic"><use href="#i-x"/></svg>Сбросить фильтры</button>`}</div></div>`;
}

function resetFleetFilters() {
    const search = $('devSearch');
    if (search) search.value = '';
    filterDevices('');
    setFleetFilter('all');
}

function renderHiddenBar(count) {
    const zone = $('fleetHidden');
    if (!zone) return;
    if (!count) {
        zone.innerHTML = '';
        /* Иначе тот же счётчик, вернувшись, упёрся бы в старую подпись и
           кнопка «Показать скрытые» не появилась бы вовсе. */
        delete zone.dataset.label;
        return;
    }
    const label = `${S.showHidden ? 'Скрыть' : 'Показать'} скрытые телефоны (${count})`;
    if (zone.dataset.label === label) return;
    zone.dataset.label = label;
    zone.innerHTML = `<button class="hiddenbar" onclick="toggleHidden()">
    <svg class="ic"><use href="#i-${S.showHidden ? 'down' : 'right'}"/></svg>${label}</button>`;
}

/* --------------------------------------------------------- панель запуска */

function renderRunbar() {
    const bar = $('runbar');
    if (!bar) return;
    const count = S.selected.size;
    setText($('selAllLabel'), count ? 'Снять выбор'
        : FLEET.group ? `Выбрать группу «${FLEET.group}»`
            : FLEET.tag ? `Выбрать с тегом «${FLEET.tag}»` : 'Выбрать все');
    bar.hidden = !count;
    if (!count) return;
    setText($('runCount'), `Выбрано телефонов: ${count}`);
    disableWithReason($('runSync'), bulkTargets().length < 2, 'Нужно 2+ свободных телефона в сети');
}


/* ---------------------------------------------------- выделение мышью

   Как в проводнике: тянешь рамку по ферме — выбираются задетые плитки.
   С Shift/Cmd/Ctrl рамка добавляет к уже выбранному, без — заменяет.
   Cmd/Ctrl+клик — переключить одну плитку, Shift+клик — диапазон. */

const MARQUEE = {start: null, box: null, base: null, justDone: false};
const MARQUEE_THRESHOLD = 6;

function shownTiles() {
    return [...$('fleet').querySelectorAll('.tile')];
}

function selectRange(from, to) {
    const serials = shownTiles().map(el => el.dataset.serial);
    let i = serials.indexOf(from), j = serials.indexOf(to);
    if (i < 0 || j < 0) return;
    if (i > j) [i, j] = [j, i];
    serials.slice(i, j + 1).forEach(s => toggleSel(s, true));
    renderFleet();
}

function marqueeRect(a, b) {
    return {
        left: Math.min(a.x, b.x), top: Math.min(a.y, b.y),
        right: Math.max(a.x, b.x), bottom: Math.max(a.y, b.y),
    };
}

(function initMarquee() {
    const area = $('fleetScroll');
    if (!area) return;

    /* Иначе браузер начинает тащить картинку превью вместо рамки. */
    area.addEventListener('dragstart', ev => ev.preventDefault());

    area.addEventListener('pointerdown', ev => {
        if (ev.button !== 0 || ev.target.closest('button, input, select, a')) return;
        MARQUEE.start = {x: ev.clientX, y: ev.clientY};
        MARQUEE.additive = ev.shiftKey || ev.metaKey || ev.ctrlKey;
    });

    /* Рамку до края — список едет сам, иначе 40 телефонов не обвести.
       Начало рамки сдвигаем вместе с прокруткой, чтобы она росла, а не плыла. */
    function edgeScroll() {
        if (!MARQUEE.box || !MARQUEE.last) return;
        const r = area.getBoundingClientRect();
        const y = MARQUEE.last.y;
        const dy = y > r.bottom - 40 ? 14 : y < r.top + 40 ? -14 : 0;
        if (dy) {
            const before = area.scrollTop;
            area.scrollTop += dy;
            MARQUEE.start.y -= area.scrollTop - before;
            marqueeMove(MARQUEE.last);
        }
        requestAnimationFrame(edgeScroll);
    }

    window.addEventListener('pointermove', ev => {
        if (!MARQUEE.start) return;
        const wasBox = !!MARQUEE.box;
        marqueeMove({x: ev.clientX, y: ev.clientY});
        if (!wasBox && MARQUEE.box) requestAnimationFrame(edgeScroll);
    });

    function marqueeMove(now) {
        MARQUEE.last = now;
        if (!MARQUEE.box) {
            if (Math.hypot(now.x - MARQUEE.start.x, now.y - MARQUEE.start.y) < MARQUEE_THRESHOLD) return;
            MARQUEE.box = document.createElement('div');
            MARQUEE.box.className = 'marquee';
            document.body.appendChild(MARQUEE.box);
            MARQUEE.base = MARQUEE.additive ? new Set(S.selected) : new Set();
            document.body.classList.add('marqueeing');
        }
        const r = marqueeRect(MARQUEE.start, now);
        Object.assign(MARQUEE.box.style, {
            left: r.left + 'px', top: r.top + 'px',
            width: r.right - r.left + 'px', height: r.bottom - r.top + 'px',
        });
        /* Подсветку считаем на лету, но S.selected трогаем только в конце:
           иначе на каждое движение мыши перерисовывалась бы вся ферма. */
        shownTiles().forEach(el => {
            const t = el.getBoundingClientRect();
            const hit = t.left < r.right && t.right > r.left && t.top < r.bottom && t.bottom > r.top;
            el.classList.toggle('sel', hit || MARQUEE.base.has(el.dataset.serial));
            el.dataset.hit = hit ? '1' : '';
        });
    }

    window.addEventListener('pointerup', () => {
        if (!MARQUEE.start) return;
        MARQUEE.start = null;
        if (!MARQUEE.box) return;
        MARQUEE.box.remove();
        MARQUEE.box = null;
        document.body.classList.remove('marqueeing');
        S.selected = MARQUEE.base;
        shownTiles().forEach(el => {
            if (el.dataset.hit && selectable(el.dataset.serial)) S.selected.add(el.dataset.serial);
            delete el.dataset.hit;
        });
        S.devSig = '';
        renderFleet();
        MARQUEE.justDone = true;
        setTimeout(() => { MARQUEE.justDone = false; }, 0);
    });
})();

/* ------------------------------------------------------------ клавиатура

   Сетка — одна остановка Tab, а не четыре на плитку (плитка, галочка,
   «подробнее», «переименовать»): на 40 телефонах до панели запуска было
   173 нажатия. Внутри сетки фокус ходит стрелками — tabindex=0 только у
   текущей плитки, у остальных и у кнопок в плитках -1. Кнопки остаются
   для мыши, с клавиатуры то же делают клавиши: пробел — выбрать, Enter —
   открыть, i — подробнее, F2 — имя, Esc — снять выбор. */

/* Раздать остановку Tab: текущей плитке (последней, где был фокус), а
   если её больше нет — соседке на том же месте. Возвращает эту плитку. */
function fleetRove(serial) {
    const tiles = shownTiles();
    if (!tiles.length) return null;
    let el = FLEET.tiles.get(serial || FLEET.focus);
    if (!el || !el.isConnected) el = tiles[Math.min(FLEET.focusIndex || 0, tiles.length - 1)];
    FLEET.focus = el.dataset.serial;
    FLEET.focusIndex = tiles.indexOf(el);
    tiles.forEach(tile => {
        const v = tile === el ? 0 : -1;
        if (tile.tabIndex !== v) tile.tabIndex = v;
    });
    return el;
}

/* Сколько плиток в ряду — у самой сетки: auto-fill меняет число колонок
   с шириной окна и размером плиток L/M/S. */
function fleetCols(box) {
    return Math.max(1, getComputedStyle(box).gridTemplateColumns.split(' ').filter(Boolean).length);
}

/* Куда шагнуть со стрелкой. Вниз с предпоследнего ряда, где под плиткой
   пусто, — на последнюю плитку: иначе до неё стрелками не дойти. */
function fleetStep(key, i, count, cols) {
    switch (key) {
        case 'ArrowRight': return Math.min(count - 1, i + 1);
        case 'ArrowLeft': return Math.max(0, i - 1);
        case 'ArrowDown':
            if (i + cols < count) return i + cols;
            return Math.floor(i / cols) < Math.floor((count - 1) / cols) ? count - 1 : i;
        case 'ArrowUp': return i - cols >= 0 ? i - cols : i;
        case 'Home': return 0;
        case 'End': return count - 1;
        default: return null;
    }
}

(function fleetKeys() {
    const box = $('fleet');
    if (!box) return;

    box.addEventListener('focusin', ev => {
        const tile = ev.target.closest('.tile[data-serial]');
        if (tile) fleetRove(tile.dataset.serial);
    });

    box.addEventListener('keydown', ev => {
        const tile = ev.target.closest('.tile[data-serial]');
        if (!tile || ev.target !== tile || ev.altKey || ev.metaKey || ev.ctrlKey) return;
        const serial = tile.dataset.serial;
        if (ev.key === 'Enter') {
            ev.preventDefault();
            return openDevice(serial);
        }
        if (ev.key === ' ') {   // пробел — выбрать, как у флажка
            ev.preventDefault();
            toggleSel(serial, !S.selected.has(serial));
            FLEET.anchor = serial;
            return renderFleet();
        }
        // По коду клавиши, а не по букве: в русской раскладке «i» — это «ш».
        if (ev.code === 'KeyI' && !ev.shiftKey) {
            ev.preventDefault();
            return deviceInfo(serial);
        }
        if (ev.key === 'F2') {
            ev.preventDefault();
            return tileEdit(serial);
        }
        const tiles = shownTiles();
        const to = fleetStep(ev.key, tiles.indexOf(tile), tiles.length, fleetCols(box));
        if (to == null) return;
        ev.preventDefault();
        tiles[to].focus({preventScroll: true});
        tiles[to].scrollIntoView({block: 'nearest'});
    });
})();

/* Esc на ферме снимает выбор — с плитки и с любого места раздела, кроме
   полей ввода (там Esc очищает поиск). Окно ловит Esc раньше (core.js). */
document.addEventListener('keydown', ev => {
    if (ev.key !== 'Escape' || S.view !== 'fleet' || !S.selected.size) return;
    if ($('modal').classList.contains('on')) return;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(ev.target.tagName)) return;
    ev.preventDefault();
    S.selected.clear();
    S.devSig = '';
    renderFleet();
});

/* ------------------------------------------------------------- навигация */

function openDevice(serial) {
    setActive(serial);
    if (window.REC) REC.builder = false;   // с фермы — пульт, конструктор по «Записать сценарий»
    showView('device');
}

/* Файл, брошенный на плитку: APK ставится, остальное — в «Загрузки». Брошен
   на выбранную плитку — уходит на все выбранные; на невыбранную — только ей. */
(function fleetDrop() {
    const area = $('fleetScroll');
    if (!area) return;
    const files = ev => ev.dataTransfer && [...ev.dataTransfer.types].includes('Files');
    let over = null;
    const mark = el => {
        if (over === el) return;
        if (over) over.classList.remove('drop');
        over = el;
        if (over) over.classList.add('drop');
    };
    area.addEventListener('dragover', ev => {
        const tile = ev.target.closest('.tile[data-serial]');
        if (!files(ev) || !tile) return mark(null);
        ev.preventDefault();
        mark(tile);
    });
    area.addEventListener('dragleave', ev => {
        if (!area.contains(ev.relatedTarget)) mark(null);
    });
    area.addEventListener('drop', ev => {
        const tile = ev.target.closest('.tile[data-serial]');
        mark(null);
        if (!files(ev) || !tile) return;
        ev.preventDefault();
        uploadFiles(S.selected.has(tile.dataset.serial) ? bulkTargets() : [tile.dataset.serial],
            [...ev.dataTransfer.files]);
    });
})();


/* Клик по тегу на плитке — показать на ферме только телефоны с этим тегом. */
function fleetShowTag(tag) {
    setTagFilter(tag);
    const sel = $('tagFilter');
    if (sel) sel.value = tag;
}
