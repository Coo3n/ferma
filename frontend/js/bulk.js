/* Массовые действия и синхронное управление.

   Синхронно: жест на открытом телефоне повторяется на всех выбранных на
   ферме. Повтор идёт одним запросом /api/bulk/action — телефоны получают
   тап почти одновременно, а не по очереди из браузера. */

const BULK_KEY = 'farm.bulk';
const PHRASES_KEY = 'farm.phrases';

/* Разброс по умолчанию включён и короткий: синхронные клики без него —
   самый заметный для соцсети признак фермы, а длинный разброс делает
   групповое управление вязким. «Осторожно» — для аккаунтов под риском. */
const JITTER_MODES = {
    off: {range: null, label: 'без разброса'},
    fast: {range: [0.2, 1], label: 'разброс 0.2–1 с'},
    safe: {range: [0.5, 3], label: 'разброс 0.5–3 с (осторожно)'},
};

const BULK = window.BULK = (() => {
    const saved = store.get(BULK_KEY, {});
    // старый формат {jitter: false} — это «без разброса»
    const mode = JITTER_MODES[saved.mode] ? saved.mode : (saved.jitter === false ? 'off' : 'fast');
    return {sync: false, mode};
})();

function bulkJitter() {
    return JITTER_MODES[BULK.mode].range;
}

function setJitter(mode) {
    BULK.mode = JITTER_MODES[mode] ? mode : 'fast';
    store.set(BULK_KEY, {mode: BULK.mode});
    renderSyncBar();
}

function jitterSelectHtml(id) {
    return `<select ${id ? `id="${id}"` : ''} onchange="setJitter(this.value)" aria-label="Разброс между телефонами">${
        Object.entries(JITTER_MODES).map(([k, m]) =>
            `<option value="${k}"${k === BULK.mode ? ' selected' : ''}>${m.label}</option>`).join('')}</select>`;
}

/* Занятые сценарием телефоны в массовые действия не попадают: «Домой»,
   перезагрузка или очистка данных сломали бы идущий прогон. */
function bulkTargets() {
    return [...S.selected].filter(s => {
        const d = S.devices.find(x => x.serial === s);
        return d && d.online && !d.busy_job;
    });
}

function bulkBusyCount() {
    return [...S.selected].filter(s => (S.devices.find(x => x.serial === s) || {}).busy_job).length;
}

/* ------------------------------------------------- итог по телефонам

   Раньше итог был тостом «36 ок, 2 с ошибкой — device offline»: исчезал,
   говорил по-английски и не называл телефоны. Теперь итог — панель в окне
   «Действия» (или своё маленькое окно): сколько готово, кто не смог и
   почему словами, и «Повторить на 2» — то же действие только на них.
   Пока действие идёт, кнопки окна выключены: второй раз его не запустить. */

const BULK_RUN = window.BULK_RUN = {busy: false, last: null, timer: 0};

function bulkTel(n) {
    return declOfNum(n, [t('bulk.tel_1'), t('bulk.tel_2'), t('bulk.tel_5')]);
}

/* Коды причин приходят с фермы (bulk.py: failure) — здесь только слова. */
const BULK_REASONS = {
    offline: () => t('bulk.prichina_offline'),
    not_found: () => t('bulk.prichina_not_found'),
    unauthorized: () => t('bulk.prichina_unauthorized'),
    timeout: () => t('bulk.prichina_timeout'),
    no_space: () => t('bulk.prichina_no_space'),
    old_android: () => t('bulk.prichina_old_android'),
    downgrade: () => t('bulk.prichina_downgrade'),
    signature: () => t('bulk.prichina_signature'),
    abi: () => t('bulk.prichina_abi'),
    blocked: () => t('bulk.prichina_blocked'),
    bad_apk: () => t('bulk.prichina_bad_apk'),
    install_other: () => t('bulk.prichina_install_other'),
    no_access: () => t('bulk.prichina_no_access'),
    no_input: () => t('bulk.prichina_no_input'),
    stopped: () => t('bulk.prichina_stopped'),
};

function bulkReason(r) {
    const word = BULK_REASONS[r.reason];
    if (word) return word();
    // Ошибка самой фермы уже по-русски — её и показываем; adb — нет.
    if (r.error && /[а-яё]/i.test(r.error) && !/\badb\b/i.test(r.error)) return r.error;
    return t('bulk.prichina_other');
}

function bulkFailed(res) {
    return Object.entries((res && res.results) || {}).filter(([, r]) => !r.ok);
}

function bulkRetryable(res) {
    return bulkFailed(res).filter(([, r]) => r.retryable !== false);
}

/* Тост — только короткий итог; подробности в панели. Без панели (один
   телефон, синхронный режим) называем первый сбой. */
function bulkReport(what, res, withPanel) {
    const failed = bulkFailed(res);
    if (res.queued && !res.done && !failed.length) {
        return toast(t('bulk.zaplanirovano', {what, n: res.queued, jitter: JITTER_MODES[BULK.mode].label}), 'ok');
    }
    if (!failed.length) return toast(t('bulk.toast_ok', {what, n: res.done}), 'ok');
    let text = t('bulk.toast_fail', {what, done: res.done, failed: failed.length});
    if (!withPanel) text += ` — ${deviceLabel(failed[0][0])}: ${bulkReason(failed[0][1])}`;
    /* Окно закрыли, пока шло, — итог можно открыть из тоста. */
    const more = withPanel === false && failed.length > 1 && BULK_RUN.last && BULK_RUN.last.res === res;
    toast(text, 'bad', more ? {label: t('bulk.podrobnee'), onClick: bulkResultModal} : undefined);
}

/* Одна дорога для всех массовых действий: call(serials) — сам запрос,
   progress(n) — строка «устанавливаю на 37 телефонов…». Тот же call
   повторяет действие на упавших. */
async function bulkRun(what, serials, call, progress) {
    if (BULK_RUN.busy) {
        toast(t('bulk.uzhe_idet'), 'bad');
        return null;
    }
    const last = BULK_RUN.last = {
        what, serials, call, res: null, error: '', started: Date.now(),
        progress: progress || (n => t('bulk.vypolnyayu', {what, n, tel: bulkTel(n)})),
    };
    BULK_RUN.busy = true;
    /* Окно «Действия» открыто — итог в нём; иначе на несколько телефонов
       своё маленькое окно. Один телефон (пульт) — хватит тоста. */
    if (!bulkBox() && serials.length > 1) bulkResultModal();
    last.focus = document.activeElement;   // кнопку выключим — фокус вернём после
    bulkPaint();
    BULK_RUN.timer = setInterval(bulkTick, 1000);
    try {
        last.res = await call(serials);
    } catch (e) {
        last.error = e.message;
    } finally {
        clearInterval(BULK_RUN.timer);
        BULK_RUN.busy = false;
    }
    const panel = bulkPaint();
    if (last.error) toast(t('bulk.oshibka', {what, err: last.error}), 'bad');
    else bulkReport(what, last.res, panel);
    return last.res;
}

function bulkResultModal() {
    const last = BULK_RUN.last;
    if (!last) return;
    $('mTitle').textContent = last.what;
    $('mBody').innerHTML = '<div class="bulk-result" id="bulkResult" hidden></div>';
    $('mActs').innerHTML = `<span class="sp"></span><button onclick="closeModal()">${esc(t('bulk.zakryt'))}</button>`;
    openModal();
    if (!BULK_RUN.busy) bulkPaint();
}

function bulkElapsed() {
    const sec = Math.floor((Date.now() - BULK_RUN.last.started) / 1000);
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

/* Раз в секунду — только счётчик времени: строку состояния не
   переписываем, иначе экранный диктор читал бы её заново каждую секунду. */
function bulkTick() {
    const el = document.querySelector('#bulkResult .bulk-elapsed');
    if (el) el.textContent = bulkElapsed();
}

/* Кнопки окна выключены, пока действие идёт: двойной запуск установки на
   40 телефонов — это 80 установок и вдвое дольше. */
function bulkLock() {
    document.querySelectorAll('#mBody .bulk-grid button, #bulkPanel button').forEach(b =>
        disableWithReason(b, BULK_RUN.busy, t('bulk.uzhe_idet')));
}

/* Панель итога — только в открытом окне: закрытое окно хранит старую
   разметку, и итог ушёл бы в невидимый узел. */
function bulkBox() {
    return $('modal').classList.contains('on') ? $('bulkResult') : null;
}

/* Нарисовать состояние в панели, если она на экране. true — панель есть. */
function bulkPaint() {
    bulkLock();
    const box = bulkBox();
    const last = BULK_RUN.last;
    if (!box || !last) return false;
    box.hidden = false;
    if (BULK_RUN.busy) {
        box.dataset.st = 'busy';
        box.innerHTML = `<div class="bulk-progress"><i aria-hidden="true"></i>
            <b role="status">${esc(last.progress(last.serials.length))}</b>
            <span class="bulk-elapsed tnum" aria-hidden="true">${bulkElapsed()}</span></div>`;
        box.scrollIntoView({block: 'nearest'});
        return true;
    }
    const retry = n => `<button class="sm primary" onclick="bulkRetry()" title="${esc(t('bulk.povtorit_podskazka'))}">${
        esc(t('bulk.povtorit', {n}))}</button>`;
    if (last.error) {
        box.dataset.st = 'bad';
        box.innerHTML = `<div class="bulk-res-head"><b>${esc(last.what)}</b>
            <span role="status">${esc(t('bulk.ne_vyshlo_sovsem', {err: last.error}))}</span>
            <span class="sp"></span>${retry(last.serials.length)}</div>`;
    } else {
        const results = last.res.results || {};
        const failed = bulkFailed(last.res)
            .map(([s, r]) => ({name: deviceLabel(s), why: bulkReason(r), raw: r.code || r.error || ''}))
            .sort((a, b) => a.why.localeCompare(b.why, 'ru') || a.name.localeCompare(b.name, 'ru', {numeric: true}));
        const ok = Object.keys(results).filter(s => results[s].ok).map(deviceLabel)
            .sort((a, b) => a.localeCompare(b, 'ru', {numeric: true}));
        const total = Object.keys(results).length || last.serials.length;
        const retryCount = bulkRetryable(last.res).length;
        box.dataset.st = failed.length ? 'bad' : 'ok';
        box.innerHTML = `<div class="bulk-res-head"><b>${esc(last.what)}</b>
            <span role="status">${esc(t('bulk.gotovo_iz', {done: total - failed.length, total}))}</span>
            <span class="sp"></span>${retryCount ? retry(retryCount) : ''}</div>
          ${failed.length ? `<ul class="bulk-fails" aria-label="${esc(t('bulk.ne_vyshlo'))}">${failed.map(f => `
            <li title="${esc(f.raw)}"><b>${esc(f.name)}</b><span>${esc(f.why)}</span></li>`).join('')}</ul>` : ''}
          ${ok.length && failed.length ? `<details class="bulk-oks"><summary>${esc(t('bulk.gde_gotovo', {n: ok.length}))}</summary>
            <p>${ok.map(esc).join(', ')}</p></details>` : ''}`;
        const again = box.querySelector('button');
        if (again) again.focus({preventScroll: true});
        else if (last.focus && last.focus.isConnected && !last.focus.disabled) last.focus.focus({preventScroll: true});
    }
    box.scrollIntoView({block: 'nearest'});
    return true;
}

/* То же действие — только на тех, где не вышло. Занятых запуском за это
   время не трогаем, как и bulkTargets. */
function bulkRetry() {
    const last = BULK_RUN.last;
    if (!last || BULK_RUN.busy) return;
    const failed = last.error ? last.serials : bulkRetryable(last.res).map(([s]) => s);
    if (!failed.length) return;
    const serials = failed.filter(s => !(S.devices.find(d => d.serial === s) || {}).busy_job);
    if (!serials.length) return toast(t('bulk.vse_zanyaty'), 'bad');
    bulkRun(last.what, serials, last.call, last.progress);
}

async function bulkAction(action, what) {
    const serials = bulkTargets();
    if (!serials.length) return toast('выберите телефоны в сети', 'bad');
    const jitter = bulkJitter();
    return bulkRun(what, serials, list => post('/api/bulk/action', {serials: list, action, jitter}));
}

/* ---------------------------------------------------------- синхронно */

function syncFollowers() {
    return bulkTargets().filter(s => s !== S.active);
}

function startSync() {
    const serials = bulkTargets();
    if (serials.length < 2) return toast('нужно 2+ свободных телефона в сети', 'bad');
    /* Ведущий — открытый телефон, если он среди выбранных, иначе первый.
       sync включаем ПОСЛЕ openDevice: смена телефона выключает режим. */
    openDevice(serials.includes(S.active) ? S.active : serials[0]);
    BULK.sync = true;
    post('/api/bulk/warm', {serials}).catch(() => {});   // быстрые соединения заранее
    if (!S.liveControl) toggleLiveControl();
    renderSyncBar();
}

function stopSync() {
    BULK.sync = false;
    renderSyncBar();
}

function renderSyncBar() {
    const bar = $('syncBar');
    if (!bar) return;
    const n = BULK.sync ? syncFollowers().length : 0;
    bar.hidden = !n;
    if (n) setText($('syncCount'), `Синхронно: повтор ещё на ${n} тел.`);
    const j = $('syncJitter');
    if (j) j.value = BULK.mode;
}

/* Вызывается из act(): если синхронный режим включён, тот же жест уходит
   на ведущий и всех ведомых одним запросом. */
/* Транслируются только жесты, текст и кнопки — то, что делают руками на
   экране. Запуск, ссылка и adb shell из «Управления» — точечные команды,
   на 40 телефонов их случайно отправлять нельзя. */
const SYNC_TYPES = new Set(['tap', 'long_tap', 'swipe', 'text', 'key', 'unlock']);

function syncRoute(payload) {
    if (!BULK.sync || !SYNC_TYPES.has(payload.type)) return null;
    const followers = syncFollowers();
    if (!followers.length) return null;
    return post('/api/bulk/action', {
        serials: [S.active, ...followers], action: payload, jitter: bulkJitter(), lead: S.active,
    })
        .then(res => {
            if (res.failed) bulkReport('Синхронно', res);
            return {ok: true};
        });
}

/* ------------------------------------------------------------- диалог */

/* разрешение: начало */
/* Разрешение и плотность: у всех выбранных одинаковые, чтобы записанные
   клики попадали в одни и те же места. */
function bulkResSummary(results) {
    const groups = new Map();
    for (const r of Object.values(results || {})) {
        if (!r || !r.ok || !r.size) continue;
        const key = `${r.size[0]}×${r.size[1]}`;
        const g = groups.get(key) || {size: key, count: 0, w: r.size[0], h: r.size[1]};
        g.count += 1;
        groups.set(key, g);
    }
    return [...groups.values()].sort((a, b) => b.count - a.count);
}

function bulkResFit(w, h, newW) {
    return Math.round(newW * h / w / 2) * 2;
}
/* разрешение: конец */

const BULK_RES = {base: null};

async function bulkResLoad() {
    const info = $('bulkResInfo');
    try {
        const res = await post('/api/bulk/display', {serials: bulkTargets()});
        const groups = bulkResSummary(res.results);
        BULK_RES.base = groups[0] || null;
        info.textContent = groups.length
            ? 'Сейчас: ' + groups.map(g => `${g.size} — ${g.count}`).join(', ')
                + (groups.length > 1 ? ` · у вас ${groups.length} разных размера` : '')
            : 'Размер телефонов узнать не удалось';
        if (BULK_RES.base) {
            $('bulkResW').value = BULK_RES.base.w;
            $('bulkResH').value = BULK_RES.base.h;
        }
    } catch (e) {
        info.textContent = e.message;
    }
}

function bulkResWidthChanged() {
    const base = BULK_RES.base;
    if (!base || !$('bulkResKeep').checked) return;
    const w = Number($('bulkResW').value);
    if (w > 0) $('bulkResH').value = bulkResFit(base.w, base.h, w);
}

function bulkResApply() {
    const width = Number($('bulkResW').value), height = Number($('bulkResH').value);
    const density = $('bulkResD').value.trim();
    if (!width || !height) return toast('впишите ширину и высоту', 'bad');
    bulkAction({type: 'resolution_set', width, height, density}, 'Разрешение');
}

function bulkResReset() {
    bulkAction({type: 'resolution_reset'}, 'Вернуть разрешение');
}

/* строки: начало */
/* «Каждому своё»: строка файла — на свой телефон. */
function bulkLinesRows(text) {
    return String(text || '').split(/\r?\n/).map(s => s.trim()).filter(Boolean).slice(0, 5000);
}

function bulkLinesPlan(names, rows, mode) {
    return names.map((name, i) => {
        let text = null;
        if (rows.length) {
            if (mode === 'cycle') text = rows[i % rows.length];
            else if (mode === 'random') text = rows[Math.floor(Math.random() * rows.length)];
            else text = i < rows.length ? rows[i] : null;
        }
        return {name, text};
    });
}
/* строки: конец */

/* Файл в UTF-8, а Excel на русском сохраняет в Windows-1251: пробуем
   строго UTF-8 и, если не вышло, читаем как 1251. */
async function bulkLinesLoad(file) {
    if (!file) return;
    const buf = await file.arrayBuffer();
    let text;
    try {
        text = new TextDecoder('utf-8', {fatal: true}).decode(buf);
    } catch (e) {
        text = new TextDecoder('windows-1251').decode(buf);
    }
    $('bulkLines').value = text.replace(/^﻿/, '');
    bulkLinesPreview();
}

function bulkLinesPreview() {
    const rows = bulkLinesRows($('bulkLines').value);
    const names = bulkTargets().map(serial => {
        const d = S.devices.find(x => x.serial === serial);
        return d ? d.name : serial;
    });
    const plan = bulkLinesPlan(names, rows, $('bulkLinesMode').value);
    const missing = plan.filter(p => p.text === null).length;
    $('bulkLinesInfo').textContent = rows.length
        ? `Строк: ${rows.length}, телефонов: ${names.length}`
            + (missing ? ` · без строки останутся ${missing}` : '')
            + ' · ' + plan.slice(0, 3).map(p => `${p.name} → ${p.text === null ? '—' : p.text}`).join('; ')
        : 'Вставьте строки или выберите файл .txt / .csv';
}

function bulkSendLines() {
    const rows = bulkLinesRows($('bulkLines').value);
    if (!rows.length) return toast('нет строк', 'bad');
    const serials = bulkTargets();
    if (!serials.length) return toast('выберите телефоны в сети', 'bad');
    return bulkRun('Каждому своё', serials, list => post('/api/bulk/text_lines', {
        serials: list, lines: rows, mode: $('bulkLinesMode').value,
        separator: $('bulkLinesSep').value, template: $('bulkLinesTpl').value,
        clear: $('bulkLinesClear').checked}));
}

function bulkContactsGenerate() {
    const prefix = $('bulkCtPrefix').value.trim();
    if (!prefix) return toast('впишите начало номера', 'bad');
    bulkAction({type: 'contacts_add', generate: {
        prefix, length: Number($('bulkCtLen').value), count: Number($('bulkCtCount').value)}}, 'Контакты');
}

/* Файл только читается и считается; добавление — по кнопке, чтобы случайно
   выбранный файл не ушёл сразу на все телефоны. */
let BULK_CT_ITEMS = [];

async function bulkContactsFile(file) {
    BULK_CT_ITEMS = [];
    const btn = $('bulkCtAddBtn');
    if (btn) btn.style.display = 'none';
    if (!file) return;
    const buf = await file.arrayBuffer();
    let text;
    try {
        text = new TextDecoder('utf-8', {fatal: true}).decode(buf);
    } catch (e) {
        text = new TextDecoder('windows-1251').decode(buf);
    }
    const items = bulkContactsParse(text);
    $('bulkCtInfo').textContent = items.length ? `Из файла: ${items.length} контактов` : 'В файле нет номеров';
    if (items.length && btn) {
        BULK_CT_ITEMS = items;
        btn.textContent = `Добавить ${items.length} ${declOfNum(items.length, ['контакт', 'контакта', 'контактов'])}`;
        btn.style.display = '';
    }
}

function bulkContactsAddFromFile() {
    if (BULK_CT_ITEMS.length) bulkAction({type: 'contacts_add', items: BULK_CT_ITEMS}, 'Контакты');
}

function bulkContactsParse(text) {
    const out = [];
    for (const line of String(text || '').split(/\r?\n/)) {
        const parts = line.trim().split(/[;,\t]/);
        const number = (parts[parts.length - 1] || '').replace(/[^\d+]/g, '');
        if (!/^\+?\d{7,15}$/.test(number)) continue;
        out.push({name: parts.length > 1 ? parts[0].trim() : number, number});
        if (out.length >= 2000) break;
    }
    return out;
}

function bulkContactsClear(ev) {
    const n = bulkTargets().length;
    if (!armConfirm(ev.currentTarget, `Стереть ВСЕ контакты на ${n} ${declOfNum(n, ['телефоне', 'телефонах', 'телефонах'])}?`)) return;
    bulkAction({type: 'contacts_clear'}, 'Очистка контактов');
}

function bulkMenu() {
    const n = bulkTargets().length;
    const busy = bulkBusyCount();
    if (!n) return toast(busy ? 'все выбранные заняты сценарием' : 'выберите телефоны в сети', 'bad');
    $('mTitle').textContent = `Действие на ${n} тел.` + (busy ? ` · ${busy} заняты, пропустим` : '');
    const groups = [...new Set(S.devices.map(d => d.group).filter(Boolean))];
    /* Плитки — сами действия. Тем, кому нужно уточнение (какое приложение,
       какой текст), плитка открывает маленькую панель под сеткой — одну за
       раз. Раньше все поля висели разом, хотя обычно нужно одно. */
    const tile = (onclick, icon, title, sub, more) => `<button onclick="${onclick}"${more ? ' aria-expanded="false"' : ''}
        data-tile="${more || ''}"><svg class="ic"><use href="#i-${icon}"/></svg>
        <b>${title}</b><span>${sub}</span></button>`;
    $('mBody').innerHTML = `
    <div class="bulk-result" id="bulkResult" hidden></div>
    <div class="bulk-sect">Управление</div>
    <div class="bulk-grid">
      ${tile('startSync();closeModal()', 'crosshair', 'Управлять синхронно', 'клик на одном — повтор на всех')}
      ${tile("bulkAction({type:'key',name:'HOME'},'Домой')", 'home', 'Домой', 'свернуть всё')}
      ${tile("bulkAction({type:'unlock'},'Разбудить')", 'unlock', 'Разбудить', 'включить и разблокировать')}
      ${tile('bulkReboot(event)', 'power', 'Перезагрузить', 'телефоны выпадут на минуту')}
      ${tile("bulkAction({type:'screen_off'},'Погасить экран')", 'moon', 'Погасить экран', 'телефон останется в сети')}
      ${tile('bulkShots()', 'image', 'Скриншоты', 'что сейчас на экранах')}
      ${tile('prepareSelected()', 'sliders', 'Подготовить', 'без анимаций, экран не гаснет')}
      ${tile("bulkPanel('res')", 'grid', 'Разрешение', 'одинаковое на всех, чтобы клики попадали', 'res')}
    </div>
    <div class="bulk-sect">Приложения и файлы</div>
    <div class="bulk-grid">
      ${tile("bulkPanel('app')", 'grid', 'Приложение', 'открыть, закрыть, очистить данные', 'app')}
      ${tile("bulkFilePick('install')", 'plus', 'Установить приложение', 'файл .apk с компьютера')}
      ${tile("bulkFilePick('push')", 'external', 'Отправить файл', 'фото или видео в «Загрузки»')}
      ${tile("bulkPanel('url')", 'external', 'Открыть ссылку', 'в браузере телефона', 'url')}
    </div>
    <div class="bulk-sect">Текст, группа и теги</div>
    <div class="bulk-grid">
      ${tile("bulkPanel('text')", 'keyboard', 'Ввести текст', 'в поле, где стоит курсор', 'text')}
      ${tile("bulkPanel('lines')", 'keyboard', 'Каждому своё', 'строка файла — на свой телефон', 'lines')}
      ${tile("bulkPanel('contacts')", 'layers', 'Контакты', 'добавить пачкой или очистить', 'contacts')}
      ${tile("bulkPanel('group')", 'layers', 'Группа', groups.length ? 'назначить или убрать' : 'например, «VK-10»', 'group')}
      ${tile("bulkPanel('tags')", 'layers', 'Теги', 'добавить или снять, например «прогрет»', 'tags')}
    </div>
    <div class="bulk-panel" id="bulkPanel" hidden></div>
    <input type="file" id="bulkFile" hidden>`;
    $('mActs').innerHTML = `<label class="bulk-jitter" title="Соцсети не видят одинаковых действий в одну секунду">
        Разброс ${jitterSelectHtml()}</label>
      <span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
    if (BULK_RUN.busy) bulkPaint();   // окно открыли заново, пока действие идёт
}

/* Галерея текущих экранов выбранных телефонов. Снимок не трогает телефон,
   поэтому занятые сценарием тоже показываем. Картинки грузятся с шагом,
   чтобы 40 телефонов не снимали экран в одну секунду. */
function bulkShots() {
    const list = [...S.selected].map(s => S.devices.find(d => d.serial === s)).filter(d => d && d.online);
    if (!list.length) return toast('выберите телефоны в сети', 'bad');
    const t = Date.now();
    $('mTitle').textContent = `Скриншоты · ${list.length} тел.`;
    $('mBody').innerHTML = `<div class="shots">${list.map(d => {
        const url = `/api/devices/${encodeURIComponent(d.serial)}/frame?t=${t}`;
        return `<figure><a href="${url}" target="_blank" rel="noopener" title="Открыть в полный размер">
            <img alt="" data-src="${url}"></a><figcaption>${esc(d.name || d.serial)}</figcaption></figure>`;
    }).join('')}</div>`;
    $('mActs').innerHTML = `<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
    $('mBody').querySelectorAll('.shots img').forEach((img, i) => {
        img.onerror = () => img.closest('figure').classList.add('fail');
        setTimeout(() => { if (img.isConnected) img.src = img.dataset.src; }, i * 150);
    });
}

/* Одна панель уточнения за раз; повторный клик по плитке её закрывает. */
function bulkPanel(kind) {
    const box = $('bulkPanel');
    const tiles = document.querySelectorAll('#mBody [data-tile]');
    const same = box.dataset.kind === kind && !box.hidden;
    tiles.forEach(t => {
        const on = !same && t.dataset.tile === kind;
        t.classList.toggle('on', on);
        if (t.dataset.tile) t.setAttribute('aria-expanded', String(on));
    });
    if (same) {
        box.hidden = true;
        box.dataset.kind = '';
        return;
    }
    box.dataset.kind = kind;
    box.hidden = false;
    const groups = [...new Set(S.devices.map(d => d.group).filter(Boolean))];
    box.innerHTML = {
        app: `<div class="bp-row">
            <select id="bulkApp" aria-label="Приложение"><option value="">загружаю список с телефонов…</option></select>
            <button class="sm" onclick="bulkAppDo('launch')">Открыть</button>
            <button class="sm" onclick="bulkAppDo('stop')">Закрыть</button>
            <button class="sm danger" onclick="bulkAppDo('clear', event)"><span>Очистить данные</span></button></div>
          <small class="dim">Очистка данных сбросит вход в аккаунт.</small>`,
        url: `<div class="bp-row"><input id="bulkOpen" type="url" placeholder="https://…" aria-label="Ссылка"
              onkeydown="if(event.key==='Enter')bulkOpen()">
            <button class="sm primary" onclick="bulkOpen()">Открыть</button></div>`,
        text: `<div class="bp-row"><input id="bulkText" placeholder="${esc(t('frazy.chto_pechatat'))}" aria-label="${esc(t('frazy.text_aria'))}"
              onkeydown="if(event.key==='Enter')bulkSendText()">
            <button class="sm primary" onclick="bulkSendText()">${esc(t('frazy.vvesti'))}</button>
            <button class="sm" onclick="phraseSave()" title="${esc(t('frazy.zapomnit_title'))}">${esc(t('frazy.zapomnit'))}</button></div>
          <div class="ph" id="bulkPhrases">${phrasesHtml()}</div>`,
        tags: bulkTagsHtml(),
        group: `<div class="bp-row"><input id="bulkGroup" list="bulkGroups" aria-label="Группа"
              placeholder="имя группы, пусто — убрать" onkeydown="if(event.key==='Enter')bulkSetGroup()">
            <datalist id="bulkGroups">${groups.map(g => `<option value="${esc(g)}">`).join('')}</datalist>
            <button class="sm primary" onclick="bulkSetGroup()">Назначить</button></div>`,
        res: `<small class="dim" id="bulkResInfo">считаю размеры…</small>
          <div class="bp-row">
            <input id="bulkResW" type="number" min="320" max="4000" placeholder="ширина" aria-label="Ширина"
                   oninput="bulkResWidthChanged()">
            <span>×</span>
            <input id="bulkResH" type="number" min="320" max="4000" placeholder="высота" aria-label="Высота">
            <input id="bulkResD" type="number" min="80" max="800" placeholder="плотность (необязательно)" aria-label="Плотность">
          </div>
          <div class="bp-row">
            <label><input type="checkbox" id="bulkResKeep" checked> сохранить пропорции</label>
            <button class="sm primary" onclick="bulkResApply()">Применить</button>
            <button class="sm" onclick="bulkResReset()">Вернуть как было</button></div>
          <small class="dim">Проверьте на одном телефоне: на некоторых прошивках после смены обрывается трансляция экрана — «Вернуть как было» всегда доступно.</small>`,
        lines: `<textarea id="bulkLines" rows="5" placeholder="по строке на телефон: логин, ссылка, текст"
              aria-label="Строки" oninput="bulkLinesPreview()"></textarea>
          <div class="bp-row">
            <input type="file" accept=".txt,.csv" aria-label="Файл" onchange="bulkLinesLoad(this.files[0])">
            <select id="bulkLinesMode" aria-label="Как раздать" onchange="bulkLinesPreview()">
              <option value="order">по порядку</option><option value="cycle">по кругу</option>
              <option value="random">случайно</option></select>
            <label><input type="checkbox" id="bulkLinesClear"> стереть поле перед вводом</label></div>
          <div class="bp-row">
            <input id="bulkLinesSep" placeholder="делить строку по (например ;)" aria-label="Разделитель">
            <input id="bulkLinesTpl" placeholder="шаблон, например {1}@mail.ru" aria-label="Шаблон">
            <button class="sm primary" onclick="bulkSendLines()">Ввести</button></div>
          <small class="dim" id="bulkLinesInfo"></small>`,
        contacts: `<div class="bp-row">
            <input id="bulkCtPrefix" placeholder="начало номера, например +7999" aria-label="Начало номера">
            <input id="bulkCtLen" type="number" value="11" min="7" max="15" aria-label="Длина номера">
            <input id="bulkCtCount" type="number" value="20" min="1" max="1000" aria-label="Сколько">
            <button class="sm primary" onclick="bulkContactsGenerate()">Случайные, у каждого свои</button></div>
          <div class="bp-row">
            <input type="file" accept=".txt,.csv" aria-label="Файл" onchange="bulkContactsFile(this.files[0])">
            <button class="sm primary" id="bulkCtAddBtn" style="display:none" onclick="bulkContactsAddFromFile()"></button>
            <button class="sm danger" onclick="bulkContactsClear(event)"><span>Очистить все контакты</span></button></div>
          <small class="dim" id="bulkCtInfo">Файл: «номер» или «имя;номер» по строке. Проверьте на одном телефоне: не все прошивки дают писать контакты.</small>`,
    }[kind];
    const first = box.querySelector('input, select');
    if (first) first.focus();
    if (kind === 'text') { phrasesRender(); phrasesLoad(); }
    if (kind === 'app') bulkLoadApps();
    if (kind === 'res') bulkResLoad();
    if (kind === 'lines') bulkLinesPreview();
    bulkLock();
}

function bulkSendText() {
    const v = $('bulkText').value;
    if (v) bulkAction({type: 'text', value: v}, 'Текст');
}

function bulkOpen() {
    const v = $('bulkOpen').value.trim();
    if (!v) return;
    if (/^[a-z]+:\/\//i.test(v)) bulkAction({type: 'url', url: v}, 'Ссылка');
    else bulkAction({type: 'launch', package: v}, 'Запуск');   // вписали пакет руками
}

/* Список приложений с самих телефонов: «VK — на 38 из 40». Сначала
   те, что стоят везде, — их и открывают на всей ферме. */
async function bulkLoadApps() {
    const sel = $('bulkApp');
    const serials = bulkTargets();
    if (!sel || !serials.length) return;
    try {
        const res = await api('/api/bulk/packages?serials=' + encodeURIComponent(serials.join(',')));
        if (!$('bulkApp')) return;   // окно уже закрыли
        const named = appDistinct(res.apps.map(a => Object.assign({label: appLabel(a.package)}, a)));
        sel.innerHTML = named.length
            ? named.map(a => `<option value="${esc(a.package)}" title="${esc(a.package)}">${
                esc(a.label)} — ${a.count === res.total ? 'на всех' : `на ${a.count} из ${res.total}`}</option>`).join('')
            : '<option value="">на телефонах нет установленных приложений</option>';
    } catch (e) {
        sel.innerHTML = `<option value="">не удалось получить список: ${esc(e.message)}</option>`;
    }
}

function bulkAppDo(kind, ev) {
    const pkg = ($('bulkApp') || {}).value;
    if (!pkg) return toast('выберите приложение', 'bad');
    const name = recApp(pkg);
    if (kind === 'launch') return bulkAction({type: 'launch', package: pkg}, `Открыть ${name}`);
    if (kind === 'stop') return bulkAction({type: 'stop', package: pkg}, `Закрыть ${name}`);
    const n = bulkTargets().length;
    if (!armConfirm(ev.currentTarget, `Очистить на ${n} ${declOfNum(n, ['телефоне', 'телефонах', 'телефонах'])}? Вход пропадёт`)) return;
    bulkAction({type: 'shell', cmd: `pm clear ${pkg}`}, `Очистка ${name}`);
}

/* ---------------------------------------------------------------- теги

   В отличие от группы, тегов у телефона много. Меняем только названные:
   «добавить vk» не трогает остальные теги. Это пометки, а не действие на
   телефоне, поэтому берём всех выбранных — и занятых сценарием тоже. */

function allTags() {
    return [...new Set(S.devices.flatMap(d => d.tags || []))].sort((a, b) => a.localeCompare(b, 'ru'));
}

function bulkTagsHtml() {
    const sel = S.devices.filter(d => S.selected.has(d.serial));
    const count = {};
    sel.forEach(d => (d.tags || []).forEach(t => { count[t] = (count[t] || 0) + 1; }));
    const have = Object.keys(count).sort((a, b) => a.localeCompare(b, 'ru'));
    return `<div class="bp-row"><input id="bulkTag" list="bulkTagList" aria-label="Теги" maxlength="200"
          placeholder="тег, можно несколько через запятую" onkeydown="if(event.key==='Enter')bulkTags('add')">
        <datalist id="bulkTagList">${allTags().map(t => `<option value="${esc(t)}">`).join('')}</datalist>
        <button class="sm primary" onclick="bulkTags('add')">Добавить</button>
        <button class="sm" onclick="bulkTags('remove')">Снять</button></div>
      ${have.length ? `<div class="phrases"><small class="dim">У выбранных:</small>${have.map(t => `<span class="phrase">
        <button class="sm" onclick="$('bulkTag').value=this.dataset.t" data-t="${esc(t)}"
                title="Подставить в поле">${esc(t)} · ${count[t]}</button>
        <button class="sm x" data-t="${esc(t)}" onclick="bulkTags('remove', [this.dataset.t])"
                aria-label="Снять тег «${esc(t)}» у выбранных" title="Снять у выбранных">×</button></span>`).join('')}</div>`
        : '<small class="dim">Тегов пока нет. До 10 на телефон.</small>'}`;
}

async function bulkTags(kind, list) {
    const tags = list || ($('bulkTag').value || '').split(',').map(t => t.trim()).filter(Boolean);
    if (!tags.length) return toast('впишите тег', 'bad');
    const serials = [...S.selected];
    if (!serials.length) return toast('выберите телефоны', 'bad');
    try {
        await post('/api/bulk/tags', {serials, add: kind === 'add' ? tags : [], remove: kind === 'remove' ? tags : []});
        toast(`${kind === 'add' ? 'теги добавлены' : 'теги сняты'}: ${serials.length} тел.`, 'ok');
        await pollDevices();
        const box = $('bulkPanel');
        if (box && box.dataset.kind === 'tags') {
            box.innerHTML = bulkTagsHtml();
            $('bulkTag').focus();
        }
    } catch (e) {
        toast(e.message, 'bad');
    }
}

function renderTagFilter() {
    const sel = $('tagFilter');
    if (!sel) return;
    const tags = allTags();
    if (FLEET.tag && !tags.includes(FLEET.tag)) FLEET.tag = '';   // тег сняли со всех
    sel.hidden = !tags.length;
    const key = tags.join('|');
    if (sel.dataset.key === key) return;
    sel.dataset.key = key;
    sel.innerHTML = '<option value="">Все теги</option>'
        + tags.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('');
    sel.value = FLEET.tag || '';
}

function setTagFilter(value) {
    FLEET.tag = value;
    S.selected.clear();
    S.devSig = '';
    renderFleet();
}

async function bulkSetGroup() {
    try {
        await post('/api/bulk/group', {serials: [...S.selected], group: $('bulkGroup').value});
        toast(`${$('bulkGroup').value.trim() ? 'группа назначена' : 'группа убрана'}: ${S.selected.size} тел.`, 'ok');
        closeModal();
        pollDevices();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

async function bulkReboot(ev) {
    const n = bulkTargets().length;
    if (!armConfirm(ev.currentTarget, `Перезагрузить ${n} ${declOfNum(n, ['телефон', 'телефона', 'телефонов'])}?`)) return;
    bulkRun('Перезагрузка', bulkTargets(), list => post('/api/bulk/reboot', {serials: list}));
}

function bulkFilePick(kind) {
    const input = $('bulkFile');
    input.accept = kind === 'install' ? '.apk' : '';
    input.onchange = () => input.files[0] && bulkUpload(bulkTargets(), input.files[0]);
    input.click();
}

/* Файл с компьютера на телефоны: APK ставится, остальное — в «Загрузки».
   Установка на 40 телефонов идёт минутами — строка «устанавливаю на 37
   телефонов…» со счётчиком времени висит в окне до итога. */
async function bulkUpload(serials, file) {
    if (!serials.length) return toast('телефоны заняты или не в сети', 'bad');
    const apk = /\.apk$/i.test(file.name);
    const what = `${apk ? 'Установка' : 'Файл'} ${file.name}`;
    const progress = n => (apk
        ? t('bulk.ustanavlivayu', {file: file.name, n, tel: bulkTel(n)})
        : t('bulk.otpravlyayu', {file: file.name, n, tel: bulkTel(n)}));
    const res = await bulkRun(what, serials, list => api(`/api/bulk/${apk ? 'install' : 'push'}`
        + `?serials=${encodeURIComponent(list.join(','))}&name=${encodeURIComponent(file.name)}`,
    {method: 'POST', body: file}), progress);
    /* Новое приложение должно появиться в пульте без перезагрузки. */
    if (res && apk && window.PULT) serials.forEach(s => { delete PULT.apps[s]; if (PULT.appsFor === s) PULT.appsFor = ''; });
    return res;
}

/* Одна дорога для пульта и для плиток фермы; файлы — по очереди. */
async function uploadFiles(serials, files) {
    if (!serials.length) return toast('телефоны заняты или не в сети', 'bad');
    for (const file of files) {
        if (BULK_RUN.busy) return toast(t('bulk.uzhe_idet'), 'bad');
        await bulkUpload(serials, file);
    }
}

/* ------------------------------------------------------- быстрые фразы

   Группы фраз живут на ферме (GET/PUT /api/phrases): одни и те же заготовки
   видны с любого компьютера. В браузере — только состояние в памяти. */

/* горячие клавиши фраз: начало */
/* F1–F9 вводят первую–девятую быструю фразу активной группы на выбранных
   телефонах, пока открыта панель «Ввести текст». С модификаторами не
   срабатывают: Ctrl+F5 браузера не должен печатать фразу. */
function phraseForHotkey(ev, list) {
    if (ev.ctrlKey || ev.altKey || ev.metaKey || ev.shiftKey) return null;
    const m = /^F([1-9])$/.exec(ev.key || '');
    return m ? (list[Number(m[1]) - 1] || null) : null;
}
/* горячие клавиши фраз: конец */

/* группы фраз: начало */
/* Чистые помощники: состояние {groups:[{id,name,items}], active} не меняют,
   а возвращают новое. Лимиты те же, что на сервере (phrase_store.py). */
const PHR_MAX_GROUPS = 30, PHR_MAX_ITEMS = 100, PHR_MAX_PHRASE = 500, PHR_MAX_NAME = 40;

function phrClone(state) {
    return JSON.parse(JSON.stringify(state));
}

function phrGroup(state, id) {
    const groups = (state && state.groups) || [];
    return groups.find(g => g.id === (id == null ? state.active : id)) || groups[0] || null;
}

function phrCountItems(state) {
    return ((state && state.groups) || []).reduce((n, g) => n + g.items.length, 0);
}

/* {state, ok, reason}: reason — empty | dup | limit */
function phrAddItem(state, text) {
    const s = phrClone(state);
    const g = phrGroup(s);
    const v = String(text == null ? '' : text).trim().slice(0, PHR_MAX_PHRASE).trim();
    if (!g || !v) return {state: s, ok: false, reason: 'empty'};
    if (g.items.includes(v)) return {state: s, ok: false, reason: 'dup'};
    if (g.items.length >= PHR_MAX_ITEMS) return {state: s, ok: false, reason: 'limit'};
    g.items.push(v);
    return {state: s, ok: true, reason: ''};
}

function phrRemoveItem(state, index) {
    const s = phrClone(state);
    const g = phrGroup(s);
    if (g && index >= 0 && index < g.items.length) g.items.splice(index, 1);
    return s;
}

/* Вставить фразу обратно на прежнее место (отмена удаления). */
function phrInsertItem(state, index, text) {
    const s = phrClone(state);
    const g = phrGroup(s);
    if (g && !g.items.includes(text) && g.items.length < PHR_MAX_ITEMS) {
        g.items.splice(Math.max(0, Math.min(index, g.items.length)), 0, text);
    }
    return s;
}

/* Новая группа становится активной. id приходит снаружи (случайный). */
function phrAddGroup(state, id, name) {
    const s = phrClone(state);
    if (s.groups.length >= PHR_MAX_GROUPS) return {state: s, ok: false, id: null};
    s.groups.push({id, name: String(name || '').trim().slice(0, PHR_MAX_NAME) || 'Группа', items: []});
    s.active = id;
    return {state: s, ok: true, id};
}

function phrRenameGroup(state, id, name) {
    const s = phrClone(state);
    const g = phrGroup(s, id);
    const v = String(name == null ? '' : name).trim().slice(0, PHR_MAX_NAME).trim();
    if (g && v) g.name = v;
    return s;
}

/* Последнюю группу не удаляем. Активной становится соседняя. */
function phrDeleteGroup(state, id) {
    const s = phrClone(state);
    const i = s.groups.findIndex(g => g.id === id);
    if (i < 0 || s.groups.length < 2) return s;
    s.groups.splice(i, 1);
    if (s.active === id) s.active = s.groups[Math.min(i, s.groups.length - 1)].id;
    return s;
}

function phrSetActive(state, id) {
    const s = phrClone(state);
    if (s.groups.some(g => g.id === id)) s.active = id;
    return s;
}

/* Соседняя вкладка по кругу: dir = -1 | 1. */
function phrNeighbor(state, dir) {
    const n = state.groups.length;
    const i = state.groups.findIndex(g => g.id === state.active);
    return n ? state.groups[(Math.max(i, 0) + dir + n) % n].id : null;
}

/* Имя для новой группы: «Группа N» с первым свободным номером. */
function phrFreeName(state, pattern) {
    const used = new Set(state.groups.map(g => g.name));
    let n = state.groups.length + 1;
    while (used.has(pattern.replace('{n}', n))) n++;
    return pattern.replace('{n}', n);
}

/* Переезд из браузера: список из localStorage уходит в первую группу, если
   на ферме фраз ещё нет. null — переезжать нечего. */
function phrMigrate(server, localList) {
    if (!server || !Array.isArray(server.groups) || !server.groups.length) return null;
    if (phrCountItems(server) > 0) return null;
    const seen = new Set(), items = [];
    for (const x of Array.isArray(localList) ? localList : []) {
        const v = typeof x === 'string' ? x.trim().slice(0, PHR_MAX_PHRASE).trim() : '';
        if (v && !seen.has(v)) { seen.add(v); items.push(v); }
    }
    if (!items.length) return null;
    const s = phrClone(server);
    s.groups[0].items = items.slice(0, PHR_MAX_ITEMS);
    return s;
}
/* группы фраз: конец */

/* ---- состояние и сохранение ---- */

const PH = {
    state: null,         // то, что видит человек
    saved: null,         // последнее подтверждённое фермой
    error: '',
    loading: false,
    renaming: null,
    ver: 0,              // растёт при каждой правке; ответ старого сохранения новее не затирает
    timer: null,
    inflight: null,
};

function phrasesActiveItems() {
    const g = PH.state && phrGroup(PH.state);
    return g ? g.items : [];
}

async function phrasesLoad() {
    if (PH.loading) return;
    PH.loading = true;
    PH.error = '';
    phrasesRender();
    try {
        const server = await api('/api/phrases');
        let local = [];
        try { local = JSON.parse(localStorage.getItem(PHRASES_KEY) || '[]'); } catch (e) { local = []; }
        PH.saved = server;
        PH.state = phrClone(server);
        const moved = phrMigrate(server, local);
        if (moved) {
            PH.state = moved;
            PH.ver++;
            PH.loading = false;
            if (await phrasesFlush()) {
                try { localStorage.removeItem(PHRASES_KEY); } catch (e) { /* приватный режим */ }
                toast(t('frazy.pereehali', {name: phrGroup(PH.saved).name}), 'ok');
            }
        } else if (Array.isArray(local) && !local.length) {
            try { localStorage.removeItem(PHRASES_KEY); } catch (e) { /* нечего чистить */ }
        }
    } catch (e) {
        if (!PH.state) PH.error = e.message;
        else toast(t('frazy.ne_zagruzilis', {err: e.message}), 'bad');
    }
    PH.loading = false;
    phrasesRender();
}

/* Правка: показываем сразу, на ферму уходит через паузу одним запросом. */
function phrasesChange(next) {
    PH.state = next;
    PH.ver++;
    clearTimeout(PH.timer);
    PH.timer = setTimeout(phrasesFlush, 400);
    phrasesRender();
}

/* true — на ферме лежит то же, что на экране; false — запись не прошла и
   экран вернулся к последнему подтверждённому. */
async function phrasesFlush() {
    clearTimeout(PH.timer);
    PH.timer = null;
    if (PH.inflight) await PH.inflight;
    if (!PH.state) return false;
    const sent = PH.state, ver = PH.ver;
    if (JSON.stringify(sent) === JSON.stringify(PH.saved)) return true;
    let ok = true;
    PH.inflight = api('/api/phrases', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(sent),
    }).then(saved => {
        PH.saved = saved;
        if (PH.ver === ver) PH.state = phrClone(saved);
    }).catch(e => {
        ok = false;
        PH.state = phrClone(PH.saved);
        PH.ver++;
        PH.renaming = null;
        toast(t('frazy.ne_sohranilos', {err: e.message}), 'bad');
    }).finally(() => { PH.inflight = null; });
    await PH.inflight;
    phrasesRender();
    return ok;
}

/* ---- вид ---- */

function phrasesHtml() {
    return `<div class="ph-tabs" id="phTabs" role="tablist" aria-label="${esc(t('frazy.gruppy_aria'))}"></div>
      <div class="ph-hint" id="phHint"></div>
      <div class="ph-list" id="phList"></div>
      <div class="ph-add">
        <input id="phAdd" maxlength="${PHR_MAX_PHRASE}" placeholder="${esc(t('frazy.dobavit_placeholder'))}"
               aria-label="${esc(t('frazy.dobavit_placeholder'))}" oninput="phrasesAddHint()"
               onkeydown="if(event.key==='Enter'){event.preventDefault();phrasesAdd()}">
        <small class="dim ph-count" id="phCount"></small>
        <button class="sm" id="phAddBtn" onclick="phrasesAdd()">${esc(t('frazy.dobavit'))}</button>
      </div>
      <div class="ph-foot" id="phFoot">
        <button class="sm" id="phRename" onclick="phrasesRenameStart()">${esc(t('frazy.pereimenovat'))}</button>
        <button class="sm" id="phLoad" title="${esc(t('frazy.zagruzit_title'))}"
                onclick="$('phFile').click()">${esc(t('frazy.zagruzit'))}</button>
        <button class="sm" id="phSave" onclick="phrasesExport()">${esc(t('frazy.skachat'))}</button>
        <button class="sm danger" id="phDel" onclick="phrasesDeleteGroup(event)"><span>${esc(t('frazy.udalit_gruppu'))}</span></button>
        <input type="file" id="phFile" accept=".txt,.csv" hidden aria-label="${esc(t('frazy.zagruzit'))}"
               onchange="phrasesImport(this.files[0]); this.value=''">
      </div>`;
}

function phrasesRender() {
    const box = document.getElementById('bulkPhrases');
    if (!box) return;
    const tabs = $('phTabs'), list = $('phList'), hint = $('phHint'), foot = $('phFoot');
    if (!PH.state) {
        tabs.innerHTML = '';
        foot.hidden = true;
        $('phAdd').disabled = $('phAddBtn').disabled = true;
        hint.innerHTML = PH.error
            ? `<span class="ph-err">${esc(t('frazy.oshibka', {err: PH.error}))}</span>
               <button class="sm" onclick="phrasesLoad()">${esc(t('frazy.povtorit'))}</button>`
            : `<span class="ph-skel">${esc(t('frazy.zagruzka'))}</span>`;
        list.innerHTML = '';
        return;
    }
    const st = PH.state, active = phrGroup(st);
    foot.hidden = false;
    $('phAdd').disabled = $('phAddBtn').disabled = false;
    tabs.innerHTML = st.groups.map(g => {
        if (g.id === PH.renaming) {
            return `<input class="ph-rename" id="phRenameInput" value="${esc(g.name)}" maxlength="${PHR_MAX_NAME}"
                      aria-label="${esc(t('frazy.nazvanie_aria'))}" data-id="${esc(g.id)}">`;
        }
        const on = g.id === active.id;
        return `<button class="ph-tab${on ? ' on' : ''}" role="tab" aria-selected="${on}" tabindex="${on ? 0 : -1}"
                  data-id="${esc(g.id)}" title="${esc(t('frazy.pereimenovat_title'))}">${esc(g.name)}<small>${g.items.length}</small></button>`;
    }).join('') + `<button class="ph-plus" id="phPlus" title="${esc(t('frazy.novaya_gruppa'))}"
                     aria-label="${esc(t('frazy.novaya_gruppa'))}" ${st.groups.length >= PHR_MAX_GROUPS ? 'disabled' : ''}>+</button>`;
    hint.textContent = t('frazy.podskazka', {name: active.name});
    list.innerHTML = active.items.length
        ? active.items.map((p, i) => `<span class="ph-chip">
            <button class="ph-say" data-i="${i}" title="${esc(i < 9 ? t('frazy.vvesti_klavisha', {key: 'F' + (i + 1)}) : t('frazy.vvesti_title'))}">${i < 9 ? `<kbd>F${i + 1}</kbd>` : ''}<span>${esc(p)}</span></button>
            <button class="ph-x" data-i="${i}" aria-label="${esc(t('frazy.udalit_frazu'))}" title="${esc(t('frazy.udalit_frazu'))}">×</button></span>`).join('')
        : `<span class="ph-empty">${esc(t('frazy.pusto'))}</span>`;
    disableWithReason($('phDel'), st.groups.length < 2, t('frazy.poslednyaya'));
    disableWithReason($('phSave'), !active.items.length, t('frazy.v_gruppe_pusto'));
    disableWithReason($('phAddBtn'), active.items.length >= PHR_MAX_ITEMS, t('frazy.limit_fraz'));
    phrasesAddHint();
    if (PH.renaming) {
        const inp = $('phRenameInput');
        if (inp) { inp.focus(); inp.select(); }
    }
}

function phrasesAddHint() {
    const el = $('phCount'), inp = $('phAdd');
    if (!el || !inp) return;
    const n = inp.value.trim() ? phrCount(inp.value) : 0;
    el.textContent = n > 1 ? t('frazy.variantov', {n}) : '';
}

function phrasesFocusAdd() {
    const inp = $('phAdd');
    if (inp) inp.focus();
}

function phrasesAdd(text) {
    const inp = $('phAdd');
    const v = text != null ? text : (inp ? inp.value : '');
    if (!PH.state) return;
    const res = phrAddItem(PH.state, v);
    if (!res.ok) {
        toast(res.reason === 'empty' ? t('frazy.vpishite_frazu')
            : res.reason === 'dup' ? t('frazy.uzhe_est') : t('frazy.limit_fraz'), 'bad');
        return;
    }
    if (inp && text == null) inp.value = '';
    phrasesChange(res.state);
}

/* «★ запомнить» у основного поля: текст уходит в активную группу. */
function phraseSave() {
    const v = $('bulkText').value.trim();
    if (!v) return toast(t('frazy.vpishite'), 'bad');
    phrasesAdd(v);
}

function phrasesSwitch(id, focusTab) {
    if (!PH.state || id == null) return;
    PH.renaming = null;
    phrasesChange(phrSetActive(PH.state, id));
    const g = phrGroup(PH.state);
    if (focusTab) {
        const tab = document.querySelector(`#phTabs .ph-tab[data-id="${CSS.escape(id)}"]`);
        if (tab) tab.focus();
    } else if (!g.items.length) {
        phrasesFocusAdd();
    }
}

function phrasesNewGroup() {
    if (!PH.state) return;
    const id = 'g' + Math.random().toString(16).slice(2, 10);
    const res = phrAddGroup(PH.state, id, phrFreeName(PH.state, t('frazy.imya_gruppy', {n: '{n}'})));
    if (!res.ok) return toast(t('frazy.limit_grupp'), 'bad');
    PH.renaming = id;
    phrasesChange(res.state);
}

function phrasesRenameStart() {
    if (!PH.state) return;
    PH.renaming = PH.state.active;
    phrasesRender();
}

function phrasesRenameDone(id, value, commit) {
    if (PH.renaming !== id) return;
    PH.renaming = null;
    if (commit) phrasesChange(phrRenameGroup(PH.state, id, value));
    else phrasesRender();
    const tab = document.querySelector(`#phTabs .ph-tab[data-id="${CSS.escape(id)}"]`);
    if (tab && commit !== 'blur') tab.focus();
}

function phrasesDeleteGroup(ev) {
    const btn = ev.currentTarget;
    if (!PH.state || !armConfirm(btn, t('frazy.udalit_podtverdit'))) return;
    const g = phrGroup(PH.state);
    delete btn.dataset.armed;
    btn.classList.remove('armed');
    (btn.querySelector('span') || btn).textContent = btn.dataset.label;
    phrasesChange(phrDeleteGroup(PH.state, g.id));
    toast(t('frazy.gruppa_udalena', {name: g.name}), 'ok');
}

async function phrasesExport() {
    if (!PH.state) return;
    await phrasesFlush();
    const a = document.createElement('a');
    a.href = '/api/phrases/export?group=' + encodeURIComponent(PH.state.active);
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

async function phrasesImport(file) {
    if (!file || !PH.state) return;
    let text;
    try {
        const buf = await file.arrayBuffer();
        try {
            text = new TextDecoder('utf-8', {fatal: true}).decode(buf);
        } catch (e) {
            text = new TextDecoder('windows-1251').decode(buf);
        }
    } catch (e) {
        return toast(t('frazy.ne_prochitan'), 'bad');
    }
    try {
        await phrasesFlush();
        const res = await post('/api/phrases/import', {group: PH.state.active, text, filename: file.name});
        const {added, ...saved} = res;
        PH.saved = saved;
        PH.state = phrClone(saved);
        PH.ver++;
        phrasesRender();
        toast(added > 0 ? t('frazy.dobavleno', {n: added}) : t('frazy.nichego_novogo'), added > 0 ? 'ok' : '');
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* События вкладок и плашек — одним обработчиком на панель. */
document.addEventListener('click', ev => {
    const box = ev.target.closest && ev.target.closest('#bulkPhrases');
    if (!box) return;
    const tab = ev.target.closest('.ph-tab');
    if (tab) return phrasesSwitch(tab.dataset.id);
    if (ev.target.closest('#phPlus')) return phrasesNewGroup();
    const x = ev.target.closest('.ph-x');
    if (x) {
        const i = Number(x.dataset.i), text = phrasesActiveItems()[i];
        phrasesChange(phrRemoveItem(PH.state, i));
        toast(t('frazy.fraza_udalena'), '', {label: t('frazy.vernut'),
            onClick: () => phrasesChange(phrInsertItem(PH.state, i, text))});
        return;
    }
    const say = ev.target.closest('.ph-say');
    if (say) bulkAction({type: 'text', value: phrasesActiveItems()[Number(say.dataset.i)]}, t('frazy.fraza'));
});

document.addEventListener('dblclick', ev => {
    const tab = ev.target.closest && ev.target.closest('#phTabs .ph-tab');
    if (!tab || !PH.state) return;
    phrasesSwitch(tab.dataset.id, true);
    phrasesRenameStart();
});

document.addEventListener('keydown', ev => {
    const inp = ev.target.closest && ev.target.closest('#phRenameInput');
    if (inp) {
        if (ev.key === 'Enter') { ev.preventDefault(); phrasesRenameDone(inp.dataset.id, inp.value, true); }
        else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); phrasesRenameDone(inp.dataset.id, '', false); }
        return;
    }
    const tab = ev.target.closest && ev.target.closest('#phTabs .ph-tab');
    if (!tab || !PH.state) return;
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
        ev.preventDefault();
        phrasesSwitch(phrNeighbor(PH.state, ev.key === 'ArrowRight' ? 1 : -1), true);
    } else if (ev.key === 'F2') {
        ev.preventDefault();
        phrasesRenameStart();
    }
});

document.addEventListener('focusout', ev => {
    const inp = ev.target.closest && ev.target.closest('#phRenameInput');
    if (inp) phrasesRenameDone(inp.dataset.id, inp.value, 'blur');
});

document.addEventListener('keydown', ev => {
    const box = document.getElementById('bulkPhrases');
    if (ev.repeat) return;                                         // зажатая клавиша не шлёт фразу снова и снова
    if (!box || box.offsetParent === null) return;                 // панели с фразами не видно
    if (ev.target.closest && ev.target.closest('input, textarea, select, [contenteditable]')) return;
    if (ev.target.closest && ev.target.closest('#phTabs') && ev.key === 'F2') return;
    const text = phraseForHotkey(ev, phrasesActiveItems());
    if (!text) return;
    ev.preventDefault();
    bulkAction({type: 'text', value: text}, t('frazy.fraza'));
});

/* -------------------------------------------------------------- группы */

function renderGroupFilter() {
    const sel = $('groupFilter');
    if (!sel) return;
    const groups = [...new Set(S.devices.map(d => d.group).filter(Boolean))].sort();
    sel.hidden = !groups.length;
    const run = $('groupRunBtn');
    if (run) run.hidden = !groups.length;
    const key = groups.join('|');
    if (sel.dataset.key === key) return;
    sel.dataset.key = key;
    sel.innerHTML = '<option value="">Все группы</option>'
        + groups.map(g => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
    sel.value = FLEET.group || '';
}

function setGroupFilter(value) {
    FLEET.group = value;
    S.selected.clear();
    S.devSig = '';
    renderFleet();
}

window.bulkMenu = bulkMenu;
window.syncRoute = syncRoute;
window.stopSync = stopSync;
