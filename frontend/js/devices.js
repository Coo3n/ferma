'use strict';

/* Данные об устройствах: опрос, выбор, поиск, переименование, обслуживание.

   Рисует не этот файл, а fleet.js: здесь только состояние и запросы к
   серверу. Разделение появилось, когда список слева стал плиткой фермы —
   логика выбора устройств от этого не изменилась, а разметка изменилась
   целиком. */

const BATTERY_LOW = 20;
const BATTERY_MID = 45;

async function pollDevices() {
    let list;
    try {
        list = await api('/api/devices');
    } catch (e) {
        // Ферма не отвечает: лучше показать пустой раздел, чем держать его скрытым.
        if (!S.devicesLoaded) {
            S.devicesLoaded = true;
            $('view-fleet').classList.remove('loading');
            renderFleet();
        }
        return;
    }
    S.devices = list;
    if (!S.devicesLoaded) {
        // Первый ответ: до него заглушка «ферма пуста» мелькала на каждом обновлении.
        S.devicesLoaded = true;
        S.devSig = '';
        $('view-fleet').classList.remove('loading');
        renderFleet();
    }

    // Полная перерисовка нужна, только если что-то правда изменилось:
    // плитки живые, в них крутятся превью, и трогать их зря не стоит.
    const signature = deviceSignature(list);
    if (signature !== S.devSig) {
        S.devSig = signature;
        renderFleet();
    }
    syncDeviceNav();
    autoSelectFirst();
    // Активное устройство ушло из сети или вернулось — перезапустить экран,
    // иначе заглушка «не в сети» висела бы до ручного перевыбора.
    if (S.active && window.activeOffline && activeOffline() !== !!S.streamOffline) {
        startStream();
    }
}

function matchesQuery(device) {
    return !S.query
        || device.name.toLowerCase().includes(S.query)
        || device.serial.toLowerCase().includes(S.query)
        || (device.group || '').toLowerCase().includes(S.query);
}

function deviceSignature(list) {
    return JSON.stringify([
        S.active, [...S.selected].sort(), [...S.hidden].sort(),
        S.showHidden, S.query, FLEET.filter, FLEET.group, FLEET.tag,
        list.map(d => [d.serial, d.name, d.state, d.busy_job,
            d.battery, d.temperature, d.android, d.warnings, d.group, d.tags,
            (d.accounts || []).map(a => a.platform + a.status).join()]),
    ]);
}

function statusClass(device) {
    if (!device.online) return 'off';
    if (device.busy_job) return 'busy';
    return device.warnings.length ? 'err' : 'on';
}

/* Первое устройство подставляем сами, но только один раз и только если
   пользователь ещё ничего не выбрал: иначе опрос перебивал бы выбор.

   «Один раз» — буквально: без autoPicked флаг сравнивал бы только S.active,
   а S.active снова становится null после closeDevice(). Опрос идёт каждые
   2.5 с, и на следующем же тике подстановка тихо переоткрывала бы устройство,
   которое человек только что закрыл явной кнопкой. */
let autoPicked = false;

/* Раньше первый телефон молча становился «открытым» прямо на ферме: в
   шапке появлялся чип, плитка подсвечивалась, крутился поток экрана, а
   «Настроить» без выделения била по нему. Теперь телефон открывают только
   руками; автовыбор остался лишь для прямой ссылки #device без серийника. */
function autoSelectFirst() {
    if (S.view !== 'device') return;
    if (autoPicked || S.active || S.query) return;
    const first = S.devices.find(d => d.online && !S.hidden.has(d.serial));
    if (first) {
        autoPicked = true;
        setActive(first.serial);
    }
}

function filterDevices(value) {
    S.query = value.trim().toLowerCase();
    S.devSig = '';
    renderFleet();
}

function toggleHidden() {
    S.showHidden = !S.showHidden;
    S.devSig = '';
    renderFleet();
}

function hideDevice(serial) {
    S.hidden.add(serial);
    saveHidden();
    S.selected.delete(serial);
    post(`/api/devices/${serial}/enabled`, {enabled: false}).catch(() => {
    });
    if (S.active === serial) {
        S.active = null;
        setText($('scrTitle'), 'Экран');
        startStream();
        syncDeviceNav();
    }
    S.devSig = '';
    renderFleet();
    closeModal();
    toast('телефон скрыт — вернуть можно внизу фермы');
}

function unhideDevice(serial) {
    S.hidden.delete(serial);
    saveHidden();
    post(`/api/devices/${serial}/enabled`, {enabled: true}).catch(() => {
    });
    S.devSig = '';
    renderFleet();
    closeModal();
    toast('телефон возвращён в список', 'ok');
}

/* Выбрать можно только то, что можно запустить: в сети и не скрыто. Так
   ведут себя галочка, «Выбрать все», Shift/Ctrl-клик и рамка одинаково. */
function selectable(serial) {
    const d = S.devices.find(x => x.serial === serial);
    return !!d && d.online && !S.hidden.has(serial);
}

function toggleSel(serial, on) {
    if (on && !selectable(serial)) return;
    if (on) S.selected.add(serial);
    else S.selected.delete(serial);
    S.devSig = '';
}

function selectAll(on) {
    S.selected.clear();
    if (on) {
        S.devices
            .filter(d => d.online && !S.hidden.has(d.serial) && matchesQuery(d) && passesFilter(d))
            .forEach(d => S.selected.add(d.serial));
    }
    S.devSig = '';
    renderFleet();
}

function markActive() {
    document.querySelectorAll('#fleet .tile').forEach(el =>
        el.classList.toggle('active', el.dataset.serial === S.active));
}

/* Кнопка «Устройство» в шапке — единственный след раскрытой карточки в
   навигации. Заодно догоняем заголовок рабочего места: при заходе по ссылке
   вида #device/SERIAL имя ещё неизвестно — устройств просто нет в списке,
   первый опрос не успел прийти. */
function syncDeviceNav() {
    const button = $('navDevice');
    if (!button) return;
    const device = S.devices.find(d => d.serial === S.active);
    /* На самом рабочем месте чип прячется: он существует, чтобы вернуться к
       открытому устройству из другого раздела («Вернуться к открытому
       устройству» в его title), а стоя на устройстве — повторяет имя,
       которое уже написано в панели ниже, и добивает шапку, где и так
       логотип, четыре раздела, две сводки и кнопка adb. Закрыть устройство
       можно кнопкой «← Ферма» там же в панели. */
    button.hidden = !device || S.view === 'device';
    if (device) {
        setText($('navDeviceName'), device.name);
        const title = $('scrTitle');
        setText(title, device.name);
        /* Заряд, температура и версия Android — в подсказке крошки, а не
           отдельной строкой: то же самое написано на плитке фермы, и ради
           этого держать над рабочим местом целую панель незачем. */
        if (title) title.title = fleetMeta(device);
    }

}

/* Конструктор живёт на экране телефона. Раньше без открытого телефона
   «Создать записью» и «Изменить» были серыми — человек шёл на ферму,
   открывал телефон и возвращался. Теперь телефон выбирается прямо здесь;
   если свободный в сети один — без вопросов. */
function pickPhone(title, then) {
    if (S.active) {
        const cur = S.devices.find(d => d.serial === S.active);
        if (cur && cur.online) return then(S.active);
    }
    const free = S.devices.filter(d => d.online && d.enabled !== false && !S.hidden.has(d.serial));
    if (!free.length) return toast('нет телефонов в сети', 'bad');
    const idle = free.filter(d => !d.busy_job);
    if (idle.length === 1) return then(idle[0].serial);
    $('mTitle').textContent = title;
    $('mBody').innerHTML = `<div class="phone-pick">${free.map(d => `
      <button onclick="closeModal();pickPhoneGo('${esc(d.serial)}')" ${d.busy_job ? 'title="Идёт сценарий — запись помешает"' : ''}>
        <span class="dot ${d.busy_job ? 'busy' : 'on'}"></span>
        <b>${esc(d.name)}</b><span>${esc([d.group, d.busy_job ? 'занят' : ''].filter(Boolean).join(' · '))}</span>
      </button>`).join('')}</div>`;
    $('mActs').innerHTML = '<button onclick="closeModal()">Отмена</button>';
    PICK_PHONE.then = then;
    openModal();
}

const PICK_PHONE = {then: null};

function pickPhoneGo(serial) {
    const then = PICK_PHONE.then;
    PICK_PHONE.then = null;
    if (then) then(serial);
}

function setActive(serial) {
    if (S.active === serial) return;
    if (window.liveControlOff) liveControlOff();   // «управляю» не переезжает с устройством
    if (window.stopSync && window.BULK && BULK.sync) stopSync();   // и синхронный режим тоже
    S.active = serial;
    const device = S.devices.find(d => d.serial === serial);
    setText($('scrTitle'), device ? device.name : 'Экран');
    markActive();
    syncDeviceNav();
    if (window.REC) REC.packages = null;   // список приложений у каждого свой
    startStream();
    if (window.syncInteractive) syncInteractive();
}

function renameDevice(serial) {
    const device = S.devices.find(d => d.serial === serial);
    const current = device ? (device.label || device.model) : '';
    promptModal('Название телефона', 'Название', current, 'Сохранить', async label => {
        try {
            await post(`/api/devices/${serial}/label`, {label});
        } catch (e) {
            toast('не удалось переименовать: ' + e.message, 'bad');
            return;
        }
        if (S.active === serial) {
            setText($('scrTitle'), label || (device && device.model) || serial);
        }
        S.devSig = '';
        pollDevices();
        toast(label ? 'переименовано' : 'название сброшено на модель', 'ok');
    });
}

function deviceLabel(serial) {
    const device = S.devices.find(d => d.serial === serial);
    return device ? device.name : serial;
}

async function prepareSelected() {
    const targets = [...S.selected];
    if (!targets.length) {
        toast('сначала выберите телефоны', 'bad');
        return;
    }

    const configured = [], skipped = [], failed = [];
    for (const serial of targets) {
        try {
            const result = await post(`/api/devices/${serial}/prepare`);
            (result.already ? skipped : configured).push(serial);
        } catch (e) {
            failed.push(serial);
            toast(deviceLabel(serial) + ': ' + e.message, 'bad');
        }
    }

    if (skipped.length) {
        const names = skipped.map(deviceLabel).join(', ');
        toast(skipped.length === targets.length
            ? `уже подготовлены, менять нечего: ${names}`
            : `уже были подготовлены: ${names}`, 'warn');
    }
    if (configured.length) {
        toast(`подготовлено телефонов: ${configured.length}`, 'ok');
    }
    if (!configured.length && !skipped.length && failed.length) {
        toast('не удалось подготовить ни один телефон — проверьте сеть', 'bad');
    }
}

async function recoverDevice() {
    if (!S.active) return;
    try {
        const result = await post(`/api/devices/${S.active}/recover`);
        toast(result.message, 'ok');
        startStream();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* Переподключение рвёт связь со всеми телефонами сразу — идущие прогоны
   упадут. Поэтому второе нажатие и предупреждение, сколько работы оборвётся. */
async function restartAdb(ev) {
    const btn = ev && ev.currentTarget;
    if (btn && !armConfirm(btn, btn.textContent.trim() ? 'Нажмите ещё раз' : '')) {
        const busy = S.devices.filter(d => d.busy_job).length;
        toast(busy ? `нажмите ещё раз: связь со всеми телефонами прервётся, ${busy} ${declOfNum(busy, ['запуск оборвётся', 'запуска оборвутся', 'запусков оборвутся'])}`
            : 'нажмите ещё раз: связь со всеми телефонами на секунду прервётся', busy ? 'bad' : undefined);
        return;
    }
    try {
        toast((await post('/api/adb/restart')).message, 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* Закрыть устройство — явное действие, а не побочный эффект перехода.
   Раньше выйти из рабочего места было нечем: кнопка устройства продолжала
   висеть в шапке и с фермы читалась как незакрытый раздел. */
function closeDevice() {
    const незаписано = window.REC && REC.steps && REC.steps.length;
    const уйти = () => {
        if (window.REC && REC.on) recPause();
        if (window.stopSync && window.BULK && BULK.sync) stopSync();
        S.active = null;
        syncDeviceNav();
        showView('fleet');
        // Иначе трансляция экрана продолжает крутиться на закрытом устройстве:
        // <img> с MJPEG-соединением остаётся в DOM, никто его не рвёт, а
        // захват кадров на бэкенде не видит, что зритель ушёл. Ровно то же
        // самое делает hideDevice() при скрытии активного устройства.
        startStream();
    };
    if (незаписано) {
        confirmModal('Закрыть телефон',
            `<p>Запись прервётся, шаги (${незаписано}) останутся в черновике.</p>`,
            'Закрыть', уйти, true);
        return;
    }
    уйти();
}
