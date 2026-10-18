'use strict';

/* Навигация, строка состояния, опросы. Загружается последним. */

const POLL_STATUS_MS = 3000;
const POLL_DEVICES_MS = 2500;
const POLL_JOBS_MS = 2000;
const POLL_SCENARIOS_MS = 15000;
/* Отклонения — редкий поток: значок непрочитанных едет вместе с
   /api/status, а сам список освежается пореже и нужен только на открытом
   разделе. */
const POLL_DEVIATIONS_MS = 6000;

const VIEWS = ['fleet', 'device', 'scen', 'jobs', 'deviations', 'schedule', 'accounts'];

/* ------------------------------------------------------------- навигация */

/* Верхний уровень: Ферма / Сценарии / Задачи и раскрытое устройство.

   Уход с устройства ставит запись на паузу: она держит экран замороженным,
   а вне рабочего места это читается как зависший интерфейс. */
function showView(name) {
    if (!VIEWS.includes(name)) name = 'fleet';
    if (name === 'device' && !S.active) {
        toast('сначала откройте телефон', 'bad');
        name = 'fleet';
    }
    if (name !== 'device' && window.REC && REC.on) recPause();

    S.view = name;
    document.querySelectorAll('.view').forEach(view =>
        view.classList.toggle('on', view.id === 'view-' + name));
    /* «Проблемы» живут внутри «Запусков» — подсвечиваем их пункт. */
    const navName = (name === 'deviations' || name === 'schedule') ? 'jobs' : name;
    document.querySelectorAll('.navbtn').forEach(button => {
        const on = button.dataset.view === navName;
        button.classList.toggle('on', on);
        button.setAttribute('aria-current', on ? 'page' : 'false');
    });

    const hash = name === 'device' ? `#device/${S.active}` : '#' + name;
    if (location.hash !== hash) history.replaceState(null, '', hash);

    /* Чип устройства в шапке зависит от текущего раздела (на самом
       устройстве он прячется), а не только от того, что устройство
       открыто, — иначе он обновлялся бы лишь со следующим опросом. */
    if (window.syncDeviceNav) syncDeviceNav();

    if (name === 'fleet') renderFleet();
    if (name === 'accounts') loadAccounts();
    /* Фильтр «этот запуск» подменяет S.jobs; вне «Запусков» он только
       прятал бы чужие задачи от экрана телефона и «Проблем». */
    if (name !== 'jobs' && S.runBatch) S.runBatch = '';
    /* Вне этих разделов задачи опрашиваются редко — при входе догоняем сразу. */
    if (JOBS_LIVE_VIEWS.has(name)) pollJobs();
    if (name === 'deviations') pollDeviations();
    if (name === 'schedule' && window.schShow) schShow();
    // Заход на устройство мимо recOpen() (клик по плитке фермы, а не «Создать
    // записью») иначе оставлял бы схему и список непрокрашенными: их рисует
    // recRender(), а не сам показ вкладки.
    if (name === 'device' && window.REC) recRender();
    if (name === 'device' && window.pultSync) pultSync();
}

/* Адрес страницы — часть состояния: ссылку на конкретное устройство можно
   отправить коллеге или оставить в закладке. */
function applyHash() {
    const raw = location.hash.replace(/^#/, '');
    const [name, serial] = raw.split('/');
    if (serial && name === 'device') {
        setActive(decodeURIComponent(serial));
        showView('device');
        return;
    }
    showView(name || 'fleet');
}

window.addEventListener('hashchange', applyHash);

/* --------------------------------------------------------- горячие клавиши */

document.addEventListener('keydown', ev => {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if ($('modal').classList.contains('on')) return;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(ev.target.tagName)) return;
    // Живая клавиатура забирает нажатия себе — см. screen.js.
    if (window.canInteract && canInteract() && $('kbCapture').checked) return;

    const keys = {g: 'fleet', s: 'scen', j: 'jobs', d: 'device', o: 'deviations'};
    const view = keys[ev.key.toLowerCase()];
    if (view) {
        ev.preventDefault();
        showView(view);
        return;
    }
    if (ev.key === '/') {
        ev.preventDefault();
        showView('fleet');
        $('devSearch').focus();
    }
    if (ev.key === 'Escape' && S.view === 'device') showView('fleet');
});

/* ------------------------------------------------------------ состояние */

async function pollStatus() {
    try {
        const status = await api('/api/status');
        /* Шапка молчит, пока всё штатно: «сколько в сети» уже на карточках
           фермы, итоги ok/сбой — в «Задачах» и «Отклонениях». Здесь только то,
           что нужно знать с любой страницы: идёт работа или что-то сломалось. */
        /* Нет scrcpy — гасим саму кнопку «В окне» с причиной, а не держим
           вечное оранжевое предупреждение в шапке на каждом экране. */
        setHTML($('stStatus'), '');
        const scr = $('btnScrcpy');
        if (scr && window.disableWithReason) disableWithReason(scr, !status.scrcpy, 'Установите scrcpy на компьютер фермы');

        const jobs = status.jobs || {};
        const held = jobs.held || 0;
        if (window.notifyHeld) notifyHeld(held);
        /* Отменяемая задача ещё держит устройство, пока шаг не дошёл до
           проверки отмены, — значок в полёте её обязан учитывать. */
        const active = (jobs.queued || 0) + (jobs.running || 0) + held
            + (jobs.cancelling || 0);
        setHTML($('stJobs'), active
            ? `работает <b>${jobs.running || 0}</b>`
              + (jobs.queued ? ` · в очереди <b>${jobs.queued}</b>` : '')
              + (held ? ` · <b style="color:var(--warn)">ждёт ${held}</b>` : '')
            : '');

        // Значок на «Задачах»: сколько работ в полёте прямо сейчас.
        const badge = $('navJobs');
        badge.hidden = !active;
        setText(badge, active);

        // Значок на «Отклонениях»: сколько из них ещё никто не смотрел.
        const deviated = status.deviations_unseen || 0;
        const dvnBadge = $('navDeviations');
        dvnBadge.hidden = !deviated;
        setText(dvnBadge, deviated);
        document.querySelectorAll('[data-dvn-count]').forEach(el => setText(el, deviated || ''));
    } catch (e) {
        setHTML($('stStatus'), '<span style="color:var(--bad)">сервер недоступен</span>');
    }
}

/* ------------------------------------------------------------ опросы */

/* Скрытая вкладка ничего не показывает, а опросы продолжают дёргать adb на
   всех телефонах. Гасим их до возвращения — и сразу освежаем при возврате,
   чтобы не смотреть на устаревшую ферму лишние секунды. */
const timers = [];
const JOBS_LIVE_VIEWS = new Set(['jobs', 'deviations', 'device']);
const JOBS_IDLE_EVERY = 5;   // 5 × POLL_JOBS_MS = раз в 10 с вне этих разделов
let jobsTick = 0;

function startPolling() {
    if (timers.length) return;
    timers.push(
        setInterval(pollStatus, POLL_STATUS_MS),
        setInterval(pollDevices, POLL_DEVICES_MS),
        /* Задачи нужны целиком только там, где их читают: «Запуски»,
           «Проблемы» и экран телефона (остановленная задача держит его).
           На остальных разделах значок «Запуски» живёт на /api/status, а
           список подтягиваем реже — раз в JOBS_IDLE_EVERY тиков. */
        setInterval(() => {
            jobsTick = (jobsTick + 1) % JOBS_IDLE_EVERY;
            if (JOBS_LIVE_VIEWS.has(S.view) || !jobsTick) pollJobs();
        }, POLL_JOBS_MS),
        setInterval(loadScenarios, POLL_SCENARIOS_MS),
        /* Список отклонений дёргаем только на открытом разделе: значок в
           навигации и так приходит со статусом, а строки в закрытой вкладке
           никто не читает. */
        setInterval(() => {
            if (S.view === 'deviations') pollDeviations();
        }, POLL_DEVIATIONS_MS),
    );
}

function stopPolling() {
    timers.forEach(clearInterval);
    timers.length = 0;
}

/* В скрытой вкладке остаётся один дешёвый опрос статуса: телефоны он не
   трогает, а без него «ферма ждёт вас» не дошло бы до человека. */
let hiddenTimer = null;

document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopPolling();
        hiddenTimer = hiddenTimer || setInterval(pollStatus, 10000);
        return;
    }
    clearInterval(hiddenTimer);
    hiddenTimer = null;
    pollStatus();
    pollDevices();
    pollJobs();
    if (S.view === 'deviations') pollDeviations();
    startPolling();
});

/* ------------------------------------------------------------ запуск */

syncInteractive();   // до первого опроса экран уже обязан быть витриной
$('recAutoAnchor').checked = recAutoAnchorOn();
applyHash();
document.documentElement.classList.remove('boot');
setTimeout(() => document.documentElement.classList.remove('nofx'), 900);
pollStatus();
pollDevices();
loadScenarios();
pollJobs();
startPolling();
