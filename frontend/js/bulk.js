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

function bulkReport(what, res) {
    if (res.queued && !res.done && !res.failed) {
        toast(`${what}: запланировано на ${res.queued} тел. · ${JITTER_MODES[BULK.mode].label}`, 'ok');
    } else if (res.failed) {
        const first = Object.entries(res.results).find(([, r]) => !r.ok);
        toast(`${what}: ${res.done} ок, ${res.failed} с ошибкой — ${first[1].error}`, 'bad');
    } else {
        toast(`${what}: готово на ${res.done}`, 'ok');
    }
}

async function bulkAction(action, what) {
    const serials = bulkTargets();
    if (!serials.length) return toast('выберите телефоны в сети', 'bad');
    try {
        bulkReport(what, await post('/api/bulk/action', {serials, action, jitter: bulkJitter()}));
    } catch (e) {
        toast(e.message, 'bad');
    }
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
    <div class="bulk-sect">Управление</div>
    <div class="bulk-grid">
      ${tile('startSync();closeModal()', 'crosshair', 'Управлять синхронно', 'клик на одном — повтор на всех')}
      ${tile("bulkAction({type:'key',name:'HOME'},'Домой')", 'home', 'Домой', 'свернуть всё')}
      ${tile("bulkAction({type:'unlock'},'Разбудить')", 'unlock', 'Разбудить', 'включить и разблокировать')}
      ${tile('bulkReboot(event)', 'power', 'Перезагрузить', 'телефоны выпадут на минуту')}
      ${tile("bulkAction({type:'screen_off'},'Погасить экран')", 'moon', 'Погасить экран', 'телефон останется в сети')}
      ${tile('bulkShots()', 'image', 'Скриншоты', 'что сейчас на экранах')}
      ${tile('prepareSelected()', 'sliders', 'Подготовить', 'без анимаций, экран не гаснет')}
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
      ${tile("bulkPanel('group')", 'layers', 'Группа', groups.length ? 'назначить или убрать' : 'например, «VK-10»', 'group')}
      ${tile("bulkPanel('tags')", 'layers', 'Теги', 'добавить или снять, например «прогрет»', 'tags')}
    </div>
    <div class="bulk-panel" id="bulkPanel" hidden></div>
    <input type="file" id="bulkFile" hidden>`;
    $('mActs').innerHTML = `<label class="bulk-jitter" title="Соцсети не видят одинаковых действий в одну секунду">
        Разброс ${jitterSelectHtml()}</label>
      <span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    $('modal').querySelector('.sheet').classList.add('wide');
    openModal();
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
    $('modal').querySelector('.sheet').classList.add('wide');
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
        text: `<div class="bp-row"><input id="bulkText" placeholder="что напечатать" aria-label="Текст"
              onkeydown="if(event.key==='Enter')bulkSendText()">
            <button class="sm primary" onclick="bulkSendText()">Ввести</button>
            <button class="sm" onclick="phraseSave()" title="Запомнить как быструю фразу">★ запомнить</button></div>
          <div class="phrases" id="bulkPhrases">${phrasesHtml()}</div>`,
        tags: bulkTagsHtml(),
        group: `<div class="bp-row"><input id="bulkGroup" list="bulkGroups" aria-label="Группа"
              placeholder="имя группы, пусто — убрать" onkeydown="if(event.key==='Enter')bulkSetGroup()">
            <datalist id="bulkGroups">${groups.map(g => `<option value="${esc(g)}">`).join('')}</datalist>
            <button class="sm primary" onclick="bulkSetGroup()">Назначить</button></div>`,
    }[kind];
    const first = box.querySelector('input, select');
    if (first) first.focus();
    if (kind === 'app') bulkLoadApps();
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
        sel.innerHTML = res.apps.length
            ? res.apps.map(a => `<option value="${esc(a.package)}" title="${esc(a.package)}">${
                esc(recApp(a.package).replace(/[«»]/g, ''))} — ${a.count === res.total ? 'на всех' : `на ${a.count} из ${res.total}`}</option>`).join('')
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
    if (!armConfirm(ev.currentTarget, 'Нажмите ещё раз — вход в аккаунт пропадёт')) return;
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
    if (!armConfirm(ev.currentTarget, 'нажмите ещё раз — телефоны перезагрузятся')) return;
    try {
        bulkReport('Перезагрузка', await post('/api/bulk/reboot', {serials: bulkTargets()}));
    } catch (e) {
        toast(e.message, 'bad');
    }
}

function bulkFilePick(kind) {
    const input = $('bulkFile');
    input.accept = kind === 'install' ? '.apk' : '';
    input.onchange = () => input.files[0] && bulkUpload(kind, input.files[0]);
    input.click();
}

async function bulkUpload(kind, file) {
    const serials = bulkTargets().join(',');
    const what = kind === 'install' ? 'Установка' : 'Файл';
    toast(`${what}: загружаю ${file.name}…`);
    try {
        const res = await api(`/api/bulk/${kind}?serials=${encodeURIComponent(serials)}`
            + `&name=${encodeURIComponent(file.name)}`, {method: 'POST', body: file});
        bulkReport(what, res);
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* Файлы с компьютера на телефоны: APK ставится, остальное — в «Загрузки».
   Одна дорога для пульта и для плиток фермы. */
async function uploadFiles(serials, files) {
    if (!serials.length) return toast('телефоны заняты или не в сети', 'bad');
    for (const file of files) {
        const apk = /\.apk$/i.test(file.name);
        const what = `${apk ? 'Установка' : 'Файл'} ${file.name}`;
        toast(`${what}: загружаю на ${serials.length} тел.…`);
        try {
            bulkReport(what, await api(`/api/bulk/${apk ? 'install' : 'push'}`
                + `?serials=${encodeURIComponent(serials.join(','))}&name=${encodeURIComponent(file.name)}`,
                {method: 'POST', body: file}));
            /* Новое приложение должно появиться в пульте без перезагрузки. */
            if (apk && window.PULT) serials.forEach(s => { delete PULT.apps[s]; if (PULT.appsFor === s) PULT.appsFor = ''; });
        } catch (e) {
            toast(e.message, 'bad');
        }
    }
}

/* ------------------------------------------------------- быстрые фразы

   Хранятся в браузере: это личные заготовки оператора, а не данные фермы. */

function phrases() {
    return store.get(PHRASES_KEY, []);
}

function phrasesHtml() {
    return phrases().map((p, i) => `<span class="phrase">
      <button class="sm" onclick="bulkAction({type:'text',value:phrases()[${i}]},'Фраза')"
              title="Ввести на всех выбранных">${esc(p)}</button>
      <button class="sm x" onclick="phraseDrop(${i})" aria-label="Удалить фразу">×</button></span>`).join('');
}

function phraseSave() {
    const v = $('bulkText').value.trim();
    if (!v) return toast('впишите текст, потом ★', 'bad');
    const list = phrases().filter(p => p !== v);
    list.unshift(v);
    store.set(PHRASES_KEY, list.slice(0, 30));
    $('bulkPhrases').innerHTML = phrasesHtml();
}

function phraseDrop(i) {
    const list = phrases();
    list.splice(i, 1);
    store.set(PHRASES_KEY, list);
    $('bulkPhrases').innerHTML = phrasesHtml();
}

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
