/* Пульт телефона. С фермы телефон открывают, чтобы им управлять: экран во
   всю высоту, справа — кнопки, приложения, текст, файлы, запись и последние
   запуски. Конструктор (рабочее место записи) появляется по «Записать
   сценарий», при правке и обучении — и пока он нужен, пульт спрятан.

   Поле текста, «живая клавиатура» и полоса «запуск ждёт» не дублируются:
   это те же узлы, что под экраном в конструкторе, их переносят в пульт и
   обратно (pultPlace). Два поля ввода с одним смыслом путали бы. */

const PULT = {apps: {}, jobsSig: null, appsFor: '', rec: null, recTimer: null};

/* Какие узлы переезжают в пульт: id → слот в пульте. */
const PULT_MOVES = [['deviceHeldBar', 'held'], ['padText', 'text'], ['kbLabel', 'kb']];

function pultOn() {
    const work = $('work');
    return !!(work && work.classList.contains('pult-on'));
}

/* Пульт, если конструктор не нужен: не пишут, не правят, не учат. */
function pultSync() {
    const work = $('work');
    if (!work || !window.REC) return;
    const on = !(REC.builder || REC.on || REC.edit || REC.teach);
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
function recBegin() {
    recNew();
    if (REC.builder && S.view === 'device' && !$('modal').classList.contains('on')) recStart();
}

/* Из конструктора обратно к пульту. Шаги не теряются — остаются черновиком. */
function pultBack() {
    if (REC.on) recPause();
    if (REC.edit || REC.teach) {
        toast(t('pult.snachala_sohranite_pravku'), 'bad');
        return;
    }
    REC.builder = false;
    pultSync();
}

/* ------------------------------------------------------------ содержимое */

function pultRender() {
    const device = S.devices.find(d => d.serial === S.active);
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
    setText($('btnRecBegin').querySelector('span'),
        continues ? t('pult.prodolzhit_zapis', {n: continues}) : t('pult.zapisat_stsenariy'));

    if (PULT.appsFor !== device.serial && device.online) pultLoadApps(device.serial);
    if (PULT.recFor !== device.serial) pultRecRestore(device.serial);
    pultJobs();
}

/* Теги — прямо под именем телефона: здесь о них и думают («этот прогрет»).
   Массово — через «Действия → Теги» на ферме. */
function pultTagsRender(device) {
    const box = $('pultTags');
    const tags = device.tags || [];
    const key = device.serial + '|' + tags.join('|');
    if (box.dataset.key === key) return;
    box.dataset.key = key;
    box.innerHTML = tags.map(tg => `<span class="tagchip pult-tag">${esc(tg)}<button class="pult-tag-x"
            aria-label="${esc(t('pult.snyat_teg', {teg: tg}))}" title="${esc(t('pult.snyat_teg', {teg: tg}))}"
            onclick="pultTagRemove(this.dataset.t)" data-t="${esc(tg)}">×</button></span>`).join('')
        + `<button class="sm ghost pult-tag-add" onclick="pultTagAdd()">${esc(t('pult.plus_teg'))}</button>`;
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
    const box = $('pultApps');
    if (!PULT.apps[serial]) {
        box.innerHTML = `<span class="dim">${t('pult.zagruzhayu')}</span>`;
        try {
            PULT.apps[serial] = await api(`/api/devices/${serial}/packages`);
        } catch (e) {
            PULT.appsFor = '';
            box.innerHTML = `<span class="dim">${esc(t('pult.ne_zagruzilis', {error: e.message}))}</span>`;
            return;
        }
    }
    if (S.active !== serial) return;
    PULT.query = '';
    PULT.showSys = false;
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
    } catch (e) {
        PULT.labelsFor[serial] = false;   // не вышло — в следующий раз попробуем снова
        return;
    }
    if (S.active === serial) pultAppsRender(serial);
}

function pultAppName(serial, pkg) {
    const real = ((PULT.labels || {})[serial] || {})[pkg];
    return real || recApp(pkg).replace(/[«»]/g, '');
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
    rows.forEach(r => {
        r.dup = count[r.name.toLowerCase()] > 1;
        r.sys = !REC_APPS[r.pkg] && PULT_BRAND_PKG.test(r.pkg)
            && !((PULT.labels || {})[serial] || {})[r.pkg];
    });
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
    q.hidden = rows.length <= PULT_APP_SEARCH_FROM;
    q.placeholder = t('pult.poisk_prilozheniya');
    q.setAttribute('aria-label', t('pult.poisk_prilozheniya'));
    if (q.value !== (PULT.query || '')) q.value = PULT.query || '';

    const needle = (PULT.query || '').trim().toLowerCase();
    const match = r => !needle || r.name.toLowerCase().includes(needle) || r.pkg.toLowerCase().includes(needle);
    /* Системные обёртки производителей свёрнуты, пока человек не ищет. */
    const hidden = rows.filter(r => r.sys).length;
    const folded = !needle && !PULT.showSys;
    const shown = rows.filter(r => match(r) && !(folded && r.sys));
    const chip = r => `<button class="chip" data-live data-pkg="${esc(r.pkg)}" title="${esc(r.pkg)}">${esc(r.name)}${
        r.dup ? ` <small class="dim">${esc(r.pkg.split('.').slice(-2).join('.'))}</small>` : ''}</button>`;
    let html = shown.map(chip).join('');
    if (!shown.length) html = `<span class="dim">${t('pult.nichego_ne_nashlos')}</span>`;
    if (!needle && hidden) {
        html += `<button class="sm ghost pult-sys-toggle" data-sys-toggle>${esc(PULT.showSys
            ? t('pult.sistemnye_skryt') : t('pult.sistemnye_n', {n: hidden}))}</button>`;
    }
    const list = box.querySelector('.pult-app-list');
    list.innerHTML = html;
    list.onclick = ev => {
        const btn = ev.target.closest('button');
        if (!btn) return;
        if (btn.hasAttribute('data-sys-toggle')) {
            PULT.showSys = !PULT.showSys;
            pultAppsRender(S.active);
        } else if (btn.dataset.pkg) {
            act({type: 'launch', package: btn.dataset.pkg});
        }
    };
    if (window.syncInteractive) syncInteractive();
}

function pultJobs() {
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
    setText(btn.querySelector('span'), t('pult.video_ekrana'));
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
