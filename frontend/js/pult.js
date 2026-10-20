/* Пульт телефона. С фермы телефон открывают, чтобы им управлять: экран во
   всю высоту, справа — кнопки, приложения, текст, файлы, запись и последние
   запуски. Конструктор (рабочее место записи) появляется по «Записать
   сценарий», при правке и обучении — и пока он нужен, пульт спрятан.

   Поле текста, «живая клавиатура» и полоса «запуск ждёт» не дублируются:
   это те же узлы, что под экраном в конструкторе, их переносят в пульт и
   обратно (pultPlace). Два поля ввода с одним смыслом путали бы. */

const PULT = {apps: {}, jobsSig: null, appsFor: '', rec: null, recTimer: null};

/* Какие узлы переезжают в пульт: id → слот в пульте. */
/* «Стоп-кадр» и «В окне» в пульте уезжают в док под экраном: полоса над
   экраном ради двух кнопок съедала высоту телефона. */
const PULT_MOVES = [['deviceHeldBar', 'held'], ['padText', 'text'], ['kbLabel', 'kb'],
    ['btnStream', 'stream'], ['btnScrcpy', 'stream']];

function pultOn() {
    const work = $('work');
    return !!(work && work.classList.contains('pult-on'));
}

/* Пульт, если конструктор не нужен: не пишут, не правят, не учат. */
function pultSync() {
    const work = $('work');
    if (!work || !window.REC) return;
    /* Правка или обучение сами по себе пульт не прячут: открыли телефон с
       фермы — показываем пульт, а к начатой правке ведёт кнопка внизу
       («Продолжить правку»). Раньше вход с фермы попадал прямо в конструктор. */
    const on = !(REC.builder || REC.on);
    if (work.classList.contains('pult-on') !== on) {
        work.classList.toggle('pult-on', on);
        pultPlace(on);
        if (!on && REC.view === 'scheme' && window.recSchemeSpine) recSchemeSpine();
        if (window.recOverlaySync) recOverlaySync();
    }
    if (on) pultRender();
    if (window.syncInteractive) syncInteractive();   // в пульте экран живой сразу
}

function pultPlace(on) {
    PULT_MOVES.forEach(([id, slot]) => {
        const node = $(id);
        if (!node) return;
        if (!node._home) node._home = {parent: node.parentNode, next: node.nextSibling};
        if (on) {
            const target = document.querySelector(`.pult-slot[data-slot="${slot}"]`);
            if (target) target.appendChild(node);
        } else {
            node._home.parent.insertBefore(node, node._home.next);
        }
    });
}

/* «Записать сценарий»: новый сценарий и сразу запись. Если recNew открыл
   диалог (восстановить черновик, выбрать телефон) — запись не начинаем:
   кликать по экрану под диалогом нельзя, человек нажмёт «Запись» сам. */
function recBegin(command) {
    if (!command && (REC.edit || REC.teach)) {   // вернуться к начатой правке, а не начинать новую
        REC.builder = true;
        pultSync();
        return;
    }
    recNew(!!command);
    if (REC.builder && S.view === 'device' && !$('modal').classList.contains('on')) recStart();
}

/* Из конструктора обратно к пульту. Шаги не теряются — остаются черновиком. */
function pultBack() {
    if (REC.on) recPause();
    REC.builder = false;
    pultSync();
}

/* ------------------------------------------------------------ содержимое */

/* Заготовки с бликом на месте чипов, пока данных нет: раньше пустые
   заголовки мигали «команд нет» / «Загружаю…», а потом подменялись. */
function pultSkelChips(widths) {
    return widths.map(w => `<span class="sk sk-chip" style="--w:${w}px"></span>`).join('');
}

function pultRender() {
    const device = S.devices.find(d => d.serial === S.active);
    $('pult').classList.toggle('loading', !device);
    if (!device) return;
    setText($('pultName'), device.name);
    $('pultName').title = device.name;
    const bits = [];
    if (device.battery != null) bits.push(`${device.battery}%${device.charging ? ' ⚡' : ''}`);
    if (device.temperature != null) bits.push(`${Math.round(device.temperature)}°`);
    if (device.group) bits.push(device.group);
    (device.accounts || []).forEach(a => bits.push(PLATFORM_NAMES[a.platform] || a.platform));
    if (device.rest) bits.unshift(t('power.pult_otdyhaet', {reason: device.rest}));
    if (!device.online) bits.unshift(t('pult.ne_v_seti'));
    else if (device.busy_job) bits.unshift(t('pult.idet_zapusk'));
    setText($('pultMeta'), bits.join(' · '));
    $('pultMeta').title = bits.join(' · ');
    pultTagsRender(device);

    const continues = REC.steps.length;
    setText($('btnRecBegin').querySelector('span'), REC.edit ? t('pult.prodolzhit_pravku')
        : continues ? t('pult.prodolzhit_zapis', {n: continues}) : t('pult.zapisat_stsenariy'));
    $('btnRecBegin').title = REC.edit ? t('pult.prodolzhit_pravku_title', {name: REC.edit.meta.name || REC.edit.key}) : '';

    if (PULT.appsFor !== device.serial && device.online) pultLoadApps(device.serial);
    if (PULT.recFor !== device.serial) pultRecRestore(device.serial);
    pultJobs();
    pultCommands();
}

/* Теги — прямо под именем телефона: здесь о них и думают («этот прогрет»).
   Массово — через «Действия → Теги» на ферме. */
function pultTagsRender(device) {
    const box = $('pultTags');
    const tags = device.tags || [];
    const key = device.serial + '|' + tags.join('|');
    if (box.dataset.key === key) return;
    box.dataset.key = key;
    box.innerHTML = tags.map(tg => `<span class="tagchip pult-tag"><svg class="ic" aria-hidden="true"><use href="#i-tag"/></svg>${esc(tg)}<button class="pult-tag-x"
            aria-label="${esc(t('pult.snyat_teg', {teg: tg}))}" title="${esc(t('pult.snyat_teg', {teg: tg}))}"
            onclick="pultTagRemove(this.dataset.t)" data-t="${esc(tg)}">×</button></span>`).join('')
        + `<button class="sm pult-tag-add" onclick="pultTagAdd()" title="${esc(t('pult.teg_title'))}">
            <svg class="ic" aria-hidden="true"><use href="#i-tag"/></svg>${esc(tags.length ? t('pult.esche_teg') : t('pult.plus_teg'))}</button>`;
}

async function pultTagsSave(tags) {
    try {
        await post(`/api/devices/${S.active}/tags`, {tags});
        await pollDevices();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

function pultTagAdd() {
    const device = S.devices.find(d => d.serial === S.active);
    if (!device) return;
    promptModal(t('pult.novyy_teg'), t('pult.teg_primer'), '', t('pult.dobavit'), value => {
        const tag = String(value || '').trim();
        if (tag) pultTagsSave([...(device.tags || []), tag]);
    });
}

function pultTagRemove(tag) {
    const device = S.devices.find(d => d.serial === S.active);
    if (device) pultTagsSave((device.tags || []).filter(tg => tg !== tag));
}

/* Приложения: сперва быстрый список по именам пакетов, потом сервер
   подтягивает настоящие названия (как на экране телефона). */
const PULT_APP_SEARCH_FROM = 12;
const PULT_BRAND_PKG = /^(com|org)\.(samsung|sec|google|miui|xiaomi|huawei|oppo|coloros|oplus|vivo|realme|oneplus|motorola|sonymobile|lge|qualcomm|mediatek)\b/;

async function pultLoadApps(serial) {
    PULT.appsFor = serial;
    pultAppsTab('own');
    const box = $('pultApps');
    if (!PULT.apps[serial]) {
        box.innerHTML = `<div class="pult-app-skel" aria-label="${esc(t('pult.zagruzhayu'))}">${
            pultSkelChips([64, 96, 80, 72, 104, 60, 88])}</div>`;
        try {
            const [all, own] = await Promise.all([api(`/api/devices/${serial}/packages`),
                api(`/api/devices/${serial}/packages?own=1`).catch(() => [])]);
            PULT.apps[serial] = all;
            PULT.own = Object.assign(PULT.own || {}, {[serial]: new Set(own)});
        } catch (e) {
            PULT.appsFor = '';
            box.innerHTML = `<span class="dim">${esc(t('pult.ne_zagruzilis', {error: e.message}))}</span>`;
            return;
        }
    }
    if (S.active !== serial) return;
    PULT.query = '';
    pultAppsRender(serial);
    pultAppLabels(serial);
}

async function pultAppLabels(serial) {
    if ((PULT.labelsFor || {})[serial]) return;
    PULT.labelsFor = Object.assign(PULT.labelsFor || {}, {[serial]: true});
    try {
        const rows = await api(`/api/devices/${serial}/apps`);
        PULT.labels = PULT.labels || {};
        PULT.labels[serial] = Object.fromEntries(rows.filter(r => r.label).map(r => [r.package, r.label]));
        /* Сервер отдаёт, что успел за 6 с, остальное доберёт в кэш: один
           повтор — и «Camera»/«Gallery» становятся «Камера»/«Галерея». */
        PULT.labelRetry = PULT.labelRetry || {};
        if (rows.some(r => !r.label) && !PULT.labelRetry[serial]) {
            PULT.labelRetry[serial] = true;
            setTimeout(() => {
                PULT.labelsFor[serial] = false;
                if (S.active === serial) pultAppLabels(serial);
            }, 2500);
        }
    } catch (e) {
        PULT.labelsFor[serial] = false;   // не вышло — в следующий раз попробуем снова
        return;
    }
    if (S.active === serial) pultAppsRender(serial);
}

function pultAppName(serial, pkg) {
    const real = ((PULT.labels || {})[serial] || {})[pkg];
    return real || appLabel(pkg);
}

function pultAppsRender(serial) {
    const box = $('pultApps');
    const all = PULT.apps[serial] || [];
    if (!all.length) {
        box.innerHTML = `<span class="dim">${t('pult.svoih_prilozheniy_net')}</span>`;
        return;
    }
    const rows = all.map(pkg => ({pkg, name: pultAppName(serial, pkg)}));
    /* Одинаковые названия различаем хвостом пакета: «Заметки · samsung.notes». */
    const count = {};
    rows.forEach(r => { count[r.name.toLowerCase()] = (count[r.name.toLowerCase()] || 0) + 1; });
    /* «Свои» — поставленные человеком (pm list -3), «Системные» — остальные
       со значком: Настройки, Камера, Галерея. Раньше системные прятались за
       строкой «ещё системных: 31» в самом низу прокрутки — её не находили. */
    const own = (PULT.own || {})[serial];
    rows.forEach(r => {
        r.dup = count[r.name.toLowerCase()] > 1;
        r.sys = own ? !own.has(r.pkg) : PULT_BRAND_PKG.test(r.pkg);
    });
    const nOwn = rows.filter(r => !r.sys).length;
    setText(document.querySelector('#pultAppsSeg [data-n="own"]'), String(nOwn));
    setText(document.querySelector('#pultAppsSeg [data-n="sys"]'), String(rows.length - nOwn));
    rows.sort((a, b) => (REC_APPS[a.pkg] ? 0 : 1) - (REC_APPS[b.pkg] ? 0 : 1)
        || a.name.localeCompare(b.name, 'ru'));

    if (!box.querySelector('.pult-app-list')) {
        box.innerHTML = '<input type="search" class="pult-app-q" hidden><div class="pult-app-list"></div>';
        const q = box.querySelector('.pult-app-q');
        q.addEventListener('input', () => {
            PULT.query = q.value;
            pultAppsRender(S.active);
        });
    }
    const q = box.querySelector('.pult-app-q');
    const tabRows = rows.filter(r => (PULT.tab === 'sys') === r.sys);
    q.hidden = tabRows.length <= PULT_APP_SEARCH_FROM;
    q.placeholder = t('pult.poisk_prilozheniya');
    q.setAttribute('aria-label', t('pult.poisk_prilozheniya'));
    if (q.value !== (PULT.query || '')) q.value = PULT.query || '';

    const needle = (PULT.query || '').trim().toLowerCase();
    const match = r => !needle || r.name.toLowerCase().includes(needle) || r.pkg.toLowerCase().includes(needle);
    const shown = tabRows.filter(match);
    const chip = r => `<button class="chip" data-live data-pkg="${esc(r.pkg)}" title="${esc(r.pkg)}">${pultAvatar(r.name, r.pkg)}${esc(r.name)}${
        r.dup ? ` <small class="dim">${esc(appTail(r.pkg))}</small>` : ''}</button>`;
    let html = shown.map(chip).join('');
    if (!shown.length) html = `<span class="dim">${t('pult.nichego_ne_nashlos')}</span>`;
    const list = box.querySelector('.pult-app-list');
    list.innerHTML = html;
    list.onclick = ev => {
        const btn = ev.target.closest('button');
        if (!btn) return;
        if (btn.dataset.pkg) {
            act({type: 'launch', package: btn.dataset.pkg});
        }
    };
    if (window.syncInteractive) syncInteractive();
}

/* Кружок с буквой вместо иконки приложения: иконок сервер не отдаёт, а
   ряд одинаковых серых слов не различался глазом. Цвет — из токенов
   состояний по хешу пакета, у одного приложения всегда один. */
const PULT_AV_TONES = ['accent', 'busy', 'warn', 'bad', 'text2'];

function pultAvatar(name, pkg) {
    let h = 0;
    for (const ch of pkg) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    const letter = (String(name).trim()[0] || '?').toUpperCase();
    return `<i class="av" style="--av:var(--${PULT_AV_TONES[h % PULT_AV_TONES.length]})" aria-hidden="true">${esc(letter)}</i>`;
}

/* «Свои» / «Системные» / «Открытые» — один раздел. Открытые — то, что
   висит в недавних, их можно закрыть. */
function pultAppsTab(kind) {
    const open = kind === 'open';
    if (!open) {
        PULT.tab = kind;
        PULT.query = '';
        if (S.active && PULT.apps[S.active]) pultAppsRender(S.active);
    }
    document.querySelectorAll('#pultAppsSeg button').forEach(b =>
        b.setAttribute('aria-selected', String(b.dataset.k === kind)));
    $('pultApps').hidden = open;
    $('pultRecents').hidden = !open;
    if (open) pultRecents();
}

/* Открытые приложения (бэкстек), в том числе системные: закрыть можно
   каждое отдельно или все сразу. Список читается по кнопке, не опросом. */
async function pultRecents() {
    const serial = S.active, box = $('pultRecents');
    if (!serial || !box) return;
    if (!box.querySelector('.chip')) box.innerHTML = pultSkelChips([88, 64, 104]);
    let pkgs;
    try {
        pkgs = await api(`/api/devices/${serial}/recents`);
    } catch (e) {
        box.innerHTML = `<span class="pult-hint">${t('pult.ne_prochitat')}</span>`;
        return;
    }
    if (S.active !== serial) return;
    if (!pkgs.length) {
        box.innerHTML = `<span class="pult-hint">${t('pult.nichego_ne_otkryto')}</span>`;
        return;
    }
    const chip = p => `<button class="chip closable" data-live data-close="${esc(p)}"
        title="${esc(t('pult.zakryt'))}">${pultAvatar(pultAppName(serial, p), p)}${esc(pultAppName(serial, p))}<svg class="ic" aria-hidden="true"><use href="#i-x"/></svg></button>`;
    box.innerHTML = pkgs.map(chip).join('')
        + `<button class="chip ghost-chip" data-live data-close-all>${esc(t('pult.zakryt_vse'))}</button>`;
    box.onclick = async ev => {
        const btn = ev.target.closest('button');
        if (!btn) return;
        const list = btn.hasAttribute('data-close-all') ? pkgs : btn.dataset.close ? [btn.dataset.close] : [];
        for (const pkg of list) await act({type: 'close_recent', package: pkg});
        if (list.length > 1) toast(t('pult.zakryto_n', {n: list.length}), 'ok');
        pultRecents();
    };
    if (window.syncInteractive) syncInteractive();
}

/* Команды — кнопки в пульте: одно нажатие запускает короткую запись на этом
   телефоне. Список берётся из уже загруженных сценариев, без запросов. */
function pultCommands() {
    if (!S.scenariosLoaded) return;   // заготовки из разметки стоят, пока список не пришёл
    const cmds = (S.scenarios || []).filter(s => s.command);
    const sig = cmds.map(s => s.key + s.name).join('|') + '#' + S.active;
    if (sig === PULT.cmdSig) return;
    PULT.cmdSig = sig;
    if (!cmds.length) $('pultCmds').innerHTML = `<span class="pult-hint">${t('cmd.pusto')}</span>`;
    else $('pultCmds').innerHTML = cmds.map(s => `<button class="chip cmd" data-live data-cmd="${esc(s.key)}"
        title="${esc(s.description || '')}"><svg class="ic" aria-hidden="true"><use href="#i-zap"/></svg>${esc(s.name)}</button>`).join('');
    $('pultCmds').onclick = async ev => {
        const key = ev.target.closest('button') && ev.target.closest('button').dataset.cmd;
        if (!key || !S.active) return;
        try {
            await post('/api/run', {scenario: key, serials: [S.active]});
            toast(t('cmd.zapusheno', {name: (cmds.find(s => s.key === key) || {}).name || key}), 'ok');
        } catch (e) {
            toast(e.message, 'bad');
        }
    };
    if (window.syncInteractive) syncInteractive();
}

function pultJobs() {
    if (!S.jobsLoaded) return;
    const jobs = (S.jobs || []).filter(j => j.serial === S.active)
        .sort((a, b) => (b.created_at || 0) - (a.created_at || 0)).slice(0, 5);
    const sig = jobs.map(j => j.id + j.status).join();
    if (sig === PULT.jobsSig) return;
    PULT.jobsSig = sig;
    $('pultJobs').innerHTML = jobs.length
        ? jobs.map(j => `<button class="pult-job st-${esc(j.status)}"
              onclick="showView('jobs');pickJob('${esc(j.id)}')">
              <i aria-hidden="true"></i><span>${esc(j.scenario_name)}</span>
              <small>${esc(jobStatusWord(j.status))} · ${new Date(j.created_at * 1000)
                  .toLocaleTimeString('ru', {hour: '2-digit', minute: '2-digit'})}</small></button>`).join('')
        : `<span class="dim">${t('pult.esche_ne_zapuskali')}</span>`;
}

/* --------------------------------------------------------------- действия */

async function pultRotate() {
    const r = await act({type: 'rotate'});
    if (r) toast(r.landscape ? t('pult.povernut_albomnyy') : t('pult.povernut_knizhnyy'));
}

/* Буфер обмена компьютера → поле на телефоне. Браузер спросит разрешение. */
async function pultPaste() {
    let value = '';
    try {
        value = await navigator.clipboard.readText();
    } catch (e) {
        toast(t('pult.bufer_nedostupen'), 'bad');
        return;
    }
    if (!value) return toast(t('pult.bufer_pust'), 'bad');
    await act({type: 'text', value});
    toast(t('pult.vstavleno'));
}

function pultDownload(url) {
    const a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function pultShot() {
    if (S.active) pultDownload(`/api/devices/${S.active}/screenshot`);
}

function pultFiles(files) {
    if (S.active && files && files.length) uploadFiles([S.active], [...files]);
}

async function pultRecord() {
    const btn = $('btnPultRec');
    if (!S.active) return;
    if (PULT.rec) {
        if (PULT.recStopping) return;   // стоп уже летит: второй дёрнул бы pull/rm того же файла
        PULT.recStopping = true;
        clearInterval(PULT.recTimer);
        btn.disabled = true;
        setText(btn.querySelector('span'), t('pult.sohranyayu'));
        try {
            const res = await post(`/api/devices/${PULT.rec}/record/stop`);
            pultDownload(res.url);
            toast(t('pult.video_sohraneno'), 'ok');
        } catch (e) {
            toast(e.message, 'bad');
        }
        pultRecReset();
        return;
    }
    try {
        const res = await post(`/api/devices/${S.active}/record`);
        PULT.rec = S.active;
        PULT.recStart = Date.now();
        PULT.recLimit = res.limit || 180;
        btn.classList.add('on');
        PULT.recTimer = setInterval(pultRecTick, 1000);
        pultRecTick();
    } catch (e) {
        toast(e.message, 'bad');
    }
}

/* Запись могла начаться до перезагрузки страницы или на другом телефоне —
   спрашиваем сервер, иначе кнопка «Видео» упиралась бы в «запись уже идёт». */
async function pultRecRestore(serial) {
    PULT.recFor = serial;
    if (PULT.rec && PULT.rec !== serial) {
        clearInterval(PULT.recTimer);
        PULT.rec = null;
    }
    let st;
    try {
        st = await api(`/api/devices/${serial}/record`);
    } catch (e) {
        return;
    }
    if (S.active !== serial) return;
    if (!st.recording) {
        if (!PULT.recStopping) pultRecReset();
        return;
    }
    PULT.rec = serial;
    PULT.recStart = st.since * 1000;
    PULT.recLimit = st.limit || 180;
    $('btnPultRec').classList.add('on');
    clearInterval(PULT.recTimer);
    PULT.recTimer = setInterval(pultRecTick, 1000);
    pultRecTick();
}

function pultRecTick() {
    const s = Math.floor((Date.now() - PULT.recStart) / 1000);
    setText($('btnPultRec').querySelector('span'),
        t('pult.ostanovit_video', {time: `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`}));
    /* Android сам обрывает запись через 3 минуты — забираем, что успело. */
    if (s >= PULT.recLimit) pultRecord();
}

function pultRecReset() {
    clearInterval(PULT.recTimer);
    PULT.rec = null;
    PULT.recStopping = false;
    const btn = $('btnPultRec');
    btn.disabled = false;
    btn.classList.remove('on');
    setText(btn.querySelector('span'), '');   // в доке — значок; подпись только пока пишем
}

/* Файл можно бросить и на зону в пульте, и прямо на экран телефона. */
function pultDropZone(el) {
    if (!el) return;
    el.addEventListener('dragover', ev => {
        if (!pultOn() || !ev.dataTransfer || ![...ev.dataTransfer.types].includes('Files')) return;
        ev.preventDefault();
        el.classList.add('drag');
    });
    el.addEventListener('dragleave', () => el.classList.remove('drag'));
    el.addEventListener('drop', ev => {
        el.classList.remove('drag');
        if (!pultOn() || !ev.dataTransfer || !ev.dataTransfer.files.length) return;
        ev.preventDefault();
        pultFiles(ev.dataTransfer.files);
    });
}

pultDropZone($('pultDrop'));
pultDropZone(document.querySelector('#mirror .stage'));

/* Полям пульта (метаданные, запуски) хватает данных, которые уже опрашивают
   ферма и журнал: здесь только перерисовка, без запросов. */
setInterval(() => {
    if (S.view === 'device' && pultOn() && !document.hidden) pultRender();
}, 2000);
