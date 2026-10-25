/* «Добавить шаг» — один выбор, разложенный по тому, что человек хочет
   сделать: действие, повторять, если на экране, иногда, другое. Раньше
   блоки жили в трёх местах (выделение, раскрытый шаг, «Логика» в
   библиотеке), и найти «повторять» можно было, только зная, где искать.

   addStepPlan — чистая: по месту вставки решает, какие пункты показать и
   какие выключить (с причиной). Её проверяет backend/tests/test_addstep_js.py.

   c = {sel: сколько шагов выбрано, inLoop: место вставки внутри повтора,
        depth: глубина места вставки, depthMax, phone: открыт ли телефон}

   Выбраны шаги — пункты-блоки берут их внутрь (recSelBlock), а действия и
   «другое» не показываются: им нечего делать с выделением. */
function addStepPlan(c) {
    const wrap = (c.sel || 0) > 0;
    const deep = !wrap && (c.depth || 0) >= c.depthMax ? 'deep' : null;
    const item = (key, off) => ({key, off: off || null});
    /* Разделы слева, карточки справа — порядок меню: сначала то, что
       добавляют чаще всего (действия и свои команды), потом логика. */
    const groups = [];
    if (!wrap) groups.push({key: 'action', items: [item('presets'), item('wait'), item('wait_gone')]});
    if (!wrap) groups.push({key: 'mine', items: [item('mine')]});
    const repeat = [item('loop', deep), item('until', deep)];
    if (!wrap && c.inLoop) repeat.push(item('break'));
    groups.push({key: 'repeat', items: repeat});
    /* «Условия» — один пункт слева, внутри подзаголовки (sub): на экране,
       на телефоне, по шансу. Факты о телефоне телефон не требуют —
       проверка идёт на прогоне. */
    const sub = (s, it) => Object.assign(it, {sub: s});
    const cond = [sub('seen', item('if_seen', deep)), sub('seen', item('if_not', deep))];
    if (!wrap) cond.push(sub('seen', item('anchor', c.phone ? null : 'phone')));
    ['phone_app', 'phone_no_app', 'phone_older', 'phone_battery', 'phone_offline', 'phone_space', 'phone_account']
        .forEach(k => cond.push(sub('phone', item(k, deep))));
    cond.push(sub('chance', item('chance', deep)));
    groups.push({key: 'cond', items: cond});
    if (!wrap) groups.push({key: 'other', items: [item('budget'), item('finish')]});
    return {wrap, groups};
}

/* Ключи строк — буквально: test_strings ищет t('…') в коде. */
function addStepGroupName(key) {
    return key === 'action' ? t('rec.dob_deystvie') : key === 'mine' ? t('rec.dob_moi')
        : key === 'repeat' ? t('rec.dob_povtoryat')
        : key === 'cond' ? t('rec.dob_usl') : t('rec.dob_drugoe');
}

function addStepSubName(key) {
    return key === 'seen' ? t('rec.dob_sub_screen') : key === 'phone' ? t('rec.dob_sub_phone') : t('rec.dob_sub_chance');
}

const ADD_STEP_GROUP_ICON = {action: 'pointer', mine: 'zap', repeat: 'repeat', cond: 'eye', other: 'layers'};

function addStepItemText(key) {
    switch (key) {
        case 'loop': return {icon: 'repeat', title: t('rec.dob_loop'), desc: t('rec.dob_loop_d')};
        case 'until': return {icon: 'search', title: t('rec.dob_until'), desc: t('rec.dob_until_d')};
        case 'break': return {icon: 'stop', title: t('rec.vyyti_iz_povtora'), desc: t('rec.l_break_d')};
        case 'if_seen': return {icon: 'eye', title: t('rec.l_esli'), desc: t('rec.l_esli_d')};
        case 'if_not': return {icon: 'eye-off', title: t('rec.l_esli_net'), desc: t('rec.l_esli_net_d')};
        case 'anchor': return {icon: 'crosshair', title: t('device.proverka_ekrana'),
            desc: t('device.stsenariy_proverit_chto_doshel')};
        case 'chance': return {icon: 'dices', title: t('rec.dob_chance'), desc: t('rec.dob_chance_d')};
        case 'wait': return {icon: 'eye', title: t('rec.dob_wait'), desc: t('rec.dob_wait_d')};
        case 'wait_gone': return {icon: 'eye-off', title: t('rec.dob_wait_gone'), desc: t('rec.dob_wait_gone_d')};
        case 'call': return {icon: 'layers', title: t('rec.l_call'), desc: t('rec.l_call_d')};
        case 'phone_app': return {icon: 'phone', title: t('rec.dob_tel_app'), desc: t('rec.dob_tel_app_d')};
        case 'phone_no_app': return {icon: 'phone', title: t('rec.dob_tel_no_app'), desc: t('rec.dob_tel_no_app_d')};
        case 'phone_older': return {icon: 'refresh', title: t('rec.dob_tel_older'), desc: t('rec.dob_tel_older_d')};
        case 'phone_battery': return {icon: 'battery', title: t('rec.dob_tel_battery'), desc: t('rec.dob_tel_battery_d')};
        case 'phone_offline': return {icon: 'wifi', title: t('rec.dob_tel_offline'), desc: t('rec.dob_tel_offline_d')};
        case 'phone_space': return {icon: 'download', title: t('rec.dob_tel_space'), desc: t('rec.dob_tel_space_d')};
        case 'phone_account': return {icon: 'shield', title: t('rec.dob_tel_account'), desc: t('rec.dob_tel_account_d')};
        case 'budget': return {icon: 'shield', title: t('rec.dob_budget'), desc: t('rec.dob_budget_d')};
        default: return {icon: 'check', title: t('rec.l_finish'), desc: t('rec.l_finish_d')};
    }
}

function addStepOffText(off) {
    return off === 'phone' ? t('rec.dob_off_phone') : t('rec.dob_off_gluboko');
}

/* Значок готового действия — по первому шагу: так «Открыть приложение» и
   «Пауза» различаются глазом, не читая. */
const ADD_STEP_PRESET_ICON = {
    launch_app: 'app', stop_app: 'app-close', shell: 'terminal', open_url: 'external', unlock: 'unlock',
    key: 'home', sleep: 'timer', screenshot: 'camera', swipe: 'swipe', type: 'text-input', ensure_app: 'check-square',
    double_tap: 'pointer', wait: 'eye', wait_gone: 'eye-off', proxy: 'wifi',
};

/* Значок по самому действию, а не по его первому шагу: «Свайп влево» с
   вертикальной стрелкой и «Тап по краю» с плюсом (запасной значок) читались
   как ошибка. Первый шаг остаётся запасным путём для новых действий. */
const ADD_STEP_PRESET_KEY_ICON = {
    launch_app: 'app', stop_app: 'app-close', restart_app: 'refresh', clear_app: 'trash',
    ensure_app: 'check-square', open_url: 'external', unlock: 'unlock', home: 'home',
    sleep: 'timer', sleep_range: 'timer', screenshot: 'camera',
    scroll_down: 'down', scroll_up: 'up', next_page: 'right',
    swipe_up: 'up', swipe_down: 'down', swipe_left: 'left', swipe_right: 'right',
    pull_refresh: 'refresh', tap_right_edge: 'right', tap_left_edge: 'left', double_like: 'target',
    scroll_feed_minutes: 'repeat', watch_video: 'video',
    search_enter: 'search', login_fields: 'shield', type_variants: 'text-input', clear_field: 'x',
    new_ip: 'refresh', wifi_on: 'wifi', wifi_off: 'wifi', airplane_on: 'moon', airplane_off: 'wifi',
    proxy_account: 'plug', proxy_off: 'plug', mute: 'volume-low', screen_rotate_lock: 'rotate',
    shell: 'terminal',
};

/* compact — готовые действия: название без пояснения (оно в подсказке).
   Пятнадцать карточек с абзацем текста под каждой читались как статья. */
function addStepCard(onclick, icon, title, desc, off, compact, sec) {
    const note = off ? addStepOffText(off) : desc;
    /* Подсказка — только когда пояснение спрятано (компактная карточка):
       иначе серый тултип повторял текст карточки слово в слово. */
    const tip = compact && !off ? ` title="${esc(note)}"` : '';
    return `<button type="button" class="addpick-card ${compact ? 'compact' : ''}" onclick="${onclick}"${off ? ' disabled' : ''}${tip}>
        <span class="addpick-ic">${recIcon(icon)}</span>
        <span class="addpick-tx"><b>${esc(title)}</b>${compact && !off ? '' : `<span>${esc(note)}</span>`}${sec ? `<span class="addpick-sec">${esc(sec)}</span>` : ''}</span>
      </button>`;
}

/* «Мои»: свои команды и сценарии — вставить шагом «Запустить сценарий»
   (call). Раньше это пряталось в «Другое → Запустить сценарий» вторым окном. */
function addStepOwn() {
    return (S.scenarios || []).filter(x => /^[a-z][a-z0-9_]{0,47}$/.test(x.key)
        && x.key !== (REC.edit ? REC.edit.key : null) && !x.error && !x.template);
}

function addStepMineCard(x, sec) {
    return addStepCard(`recLogicCall('${esc(x.key)}')`, x.command ? 'zap' : 'layers',
        x.name || x.key, x.command ? t('rec.dob_komanda') : t('rec.dob_stsenariy'), null, true, sec);
}

function addStepMineHtml() {
    const own = addStepOwn();
    const card = x => addStepMineCard(x);
    const cmds = own.filter(x => x.command), rest = own.filter(x => !x.command);
    if (!own.length) return `<p class="addpick-empty">${esc(t('rec.dob_moi_pusto'))}</p>`;
    return (cmds.length ? '' : `<p class="addpick-hint">${esc(t('rec.dob_komand_net'))}</p>`) + (cmds.length ? `<h5 class="addpick-sub">${esc(t('cmd.komandy'))}</h5><div class="addpick-grid">${cmds.map(card).join('')}</div>` : '')
        + (rest.length ? `<h5 class="addpick-sub">${esc(t('rec.dob_stsenarii'))}</h5><div class="addpick-grid">${rest.map(card).join('')}</div>` : '');
}

const ADD_STEP_TAB_KEY = 'farm.addstep.tab';
const ADD_STEP_RECENT_KEY = 'farm.addstep.recent';
const ADD_STEP_RECENT_MAX = 4;
const ADD_STEP_CHIP_KEY = 'farm.addstep.chip';
/* «Частые»: недавние + эти готовые действия, всего не больше 8 карточек. */
const ADD_STEP_POPULAR = ['launch_app', 'double_like', 'scroll_feed_minutes', 'sleep_range', 'type_variants', 'new_ip', 'swipe_up', 'home'];
const ADD_STEP_FREQ_MAX = 8;

/* Разделы вкладки «Действие» — в этом порядке; старый ответ сервера без
   поля group целиком попадает в «Система». */
const ADD_STEP_SECTIONS = ['apps', 'gestures', 'feed', 'input', 'network', 'wait', 'system'];

function addStepSectionName(key) {
    switch (key) {
        case 'apps': return t('rec.grp_apps');
        case 'gestures': return t('rec.grp_gestures');
        case 'feed': return t('rec.grp_feed');
        case 'input': return t('rec.grp_input');
        case 'network': return t('rec.grp_network');
        case 'wait': return t('rec.grp_wait');
        default: return t('rec.grp_system');
    }
}

/* Слова для поиска: названия в интерфейсе одни, а ищут по-разному. */
const ADD_STEP_KEYWORDS = {
    loop: 'повторять повтор цикл круг раз минут снова по кругу',
    until: 'повторять пока не найдёшь цикл искать ждать появится крутить',
    break: 'выйти из повтора прервать остановить цикл хватит',
    if_seen: 'если есть видно виден на экране кнопка надпись условие',
    if_not: 'если нет не видно пропало отсутствует на экране условие',
    anchor: 'проверка экрана убедиться тот экран якорь',
    chance: 'иногда шанс вероятность случайно процент не каждый раз',
    phone_app: 'если приложение есть установлено телефон',
    phone_no_app: 'если приложения нет не установлено телефон',
    phone_older: 'версия ниже старое обновить приложение телефон',
    phone_battery: 'заряд батарея аккумулятор мало телефон',
    phone_offline: 'интернет сеть нет связи вайфай телефон',
    phone_space: 'место память мало свободно телефон',
    phone_account: 'аккаунт не привязан вк инстаграм тикток телеграм телефон',
    budget: 'потолок лимит сутки не больше ограничение',
    finish: 'закончить завершить остановить стоп ошибка успех конец',
    wait: 'ждать ожидание появится дождаться пока',
    wait_gone: 'ждать ожидание исчезнет пропадёт убрать дождаться пока',
};

/* ё и е считаем одной буквой, регистр не важен. */
function addStepNorm(text) {
    return String(text == null ? '' : text).toLowerCase().replace(/ё/g, 'е');
}

/* Чистая: cards [{key, group, title, desc, words}] → те, где нашлись ВСЕ слова
   запроса (подстрокой в названии, пояснении или ключевых словах; короткие — по началу слова), в исходном
   порядке. Пустой запрос — пустой список: вкладки показывает вызывающий. */
function addStepSearch(query, cards) {
    const words = addStepNorm(query).split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    return (cards || []).filter(c => {
        const hay = addStepNorm([c.title, c.desc, c.words].filter(Boolean).join(' '));
        const hayWords = hay.split(/[^a-zа-я0-9]+/).filter(Boolean);
        /* Короткое слово ищем по началу слова: «ip» — подстрока в «swipe», и
           «Свайп вверх» выскакивал бы на запрос про IP. От четырёх букв
           подстрока безопасна и ловит формы слова («лайк» в «лайкнуть»). */
        return words.every(w => hayWords.some(h => h.startsWith(w)) || (w.length >= 4 && hay.includes(w)));
    });
}

/* Все карточки окна — одним списком: из него и вкладки, и поиск. */
let ADD_STEP_CARDS = [];

function addStepRecentKeys() {
    const list = window.store ? store.get(ADD_STEP_RECENT_KEY, []) : [];
    return Array.isArray(list) ? list.filter(k => typeof k === 'string') : [];
}

function addStepRecentPush(key) {
    if (!window.store || !key) return;
    try {
        store.set(ADD_STEP_RECENT_KEY, [key, ...addStepRecentKeys().filter(k => k !== key)].slice(0, ADD_STEP_RECENT_MAX));
    } catch (e) { /* без памяти обходимся */ }
}

function addStepBuildCards(plan, presets) {
    const out = [];
    for (const group of plan.groups) {
        for (const it of group.items) {
            if (it.key === 'presets') {
                (presets || []).forEach((preset, index) => {
                    const first = (preset.steps || [])[0];
                    const icon = ADD_STEP_PRESET_KEY_ICON[preset.key]
                        || (first && ADD_STEP_PRESET_ICON[first.kind]) || 'plus';
                    const sect = ADD_STEP_SECTIONS.includes(preset.group) ? preset.group : 'system';
                    out.push({key: 'p:' + preset.key, preset: preset.key, group: sect, tab: 'action', title: preset.title, desc: preset.desc,
                        words: (preset.keywords || []).join(' '), sec: addStepSectionName(sect),
                        html: sec => addStepCard(`recLibPick(${index})`, icon, preset.title, preset.desc, null, true, sec)});
                });
            } else if (it.key === 'mine') {
                addStepOwn().forEach(x => out.push({key: 'm:' + x.key, group: 'mine', tab: 'mine', title: x.name || x.key,
                    desc: x.command ? t('rec.dob_komanda') : t('rec.dob_stsenariy'), words: x.key,
                    sec: addStepGroupName('mine'), html: sec => addStepMineCard(x, sec)}));
            } else {
                const text = addStepItemText(it.key);
                const inWait = it.key === 'wait' || it.key === 'wait_gone';
                out.push({key: it.key, group: inWait ? 'wait' : group.key, tab: group.key, title: text.title, desc: text.desc,
                    words: ADD_STEP_KEYWORDS[it.key] || '', off: it.off,
                    sec: inWait ? addStepSectionName('wait') : it.sub ? addStepSubName(it.sub) : addStepGroupName(group.key),
                    sub: it.sub,
                    html: sec => addStepCard(`recAddPick('${it.key}')`, text.icon, text.title, text.desc, it.off, false, sec)});
            }
        }
    }
    return out;
}

function addStepFrequent(mine) {
    const recent = addStepRecentKeys().map(k => mine.find(c => c.preset === k)).filter(Boolean).slice(0, ADD_STEP_RECENT_MAX);
    const out = [...recent];
    for (const k of ADD_STEP_POPULAR) {
        const c = mine.find(x => x.preset === k);
        if (c && !out.includes(c) && out.length < ADD_STEP_FREQ_MAX) out.push(c);
    }
    return out;
}

/* Вкладка «Действие»: ряд чипов-фильтров и одна сетка выбранной группы —
   не простыня из сорока карточек. */
function addStepActionPane(cards) {
    const mine = cards.filter(c => c.tab === 'action');
    const lists = [{key: 'freq', name: t('rec.dob_chastye'), list: addStepFrequent(mine)}];
    for (const sect of ADD_STEP_SECTIONS) {
        const list = mine.filter(c => c.group === sect);
        if (list.length) lists.push({key: sect, name: addStepSectionName(sect), list});
    }
    const saved = window.store ? store.get(ADD_STEP_CHIP_KEY, '') : '';
    const active = lists.some(l => l.key === saved) ? saved : 'freq';
    /* Вкладки в один ряд с подчёркиванием, без цифр: восемь «таблеток» со
       счётчиками в два ряда читались как россыпь, а число карточек выбору не
       помогает. */
    const chips = lists.map(l => `<button type="button" class="addpick-chip" role="tab" data-chip="${l.key}"
        aria-pressed="${l.key === active}" aria-selected="${l.key === active}" onclick="addStepChip('${l.key}')">${esc(l.name)}</button>`).join('');
    const grids = lists.map(l => `<div class="addpick-grid" data-chipgrid="${l.key}"${l.key === active ? '' : ' hidden'}>${l.list.map(c => c.html()).join('')}</div>`).join('');
    return `<div class="addpick-chips" role="tablist" onkeydown="addStepChipKey(event)">${chips}</div>${grids}`;
}

function addStepChip(key) {
    document.querySelectorAll('.addpick-chip').forEach(b => {
        const on = b.dataset.chip === key;
        b.setAttribute('aria-pressed', String(on));
        b.setAttribute('aria-selected', String(on));
        if (on && b.scrollIntoView) b.scrollIntoView({block: 'nearest', inline: 'nearest'});
    });
    document.querySelectorAll('[data-chipgrid]').forEach(g => { g.hidden = g.dataset.chipgrid !== key; });
    try { if (window.store) store.set(ADD_STEP_CHIP_KEY, key); } catch (e) { /* без памяти обходимся */ }
}

/* Стрелки ←→ листают вкладки групп: ряд длиннее окна, и мышью до дальних неудобно. */
function addStepChipKey(ev) {
    if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
    const tabs = [...document.querySelectorAll('.addpick-chip')];
    const at = tabs.findIndex(b => b.getAttribute('aria-selected') === 'true');
    const next = tabs[at + (ev.key === 'ArrowRight' ? 1 : -1)];
    if (!next) return;
    ev.preventDefault();
    next.click();
    next.focus();
}

/* Условия: подзаголовки «На экране», «На телефоне», «По шансу». */
function addStepCondPane(cards) {
    return ['seen', 'phone', 'chance'].map(sub => {
        const list = cards.filter(c => c.tab === 'cond' && c.sub === sub);
        return list.length ? `<h5 class="addpick-sub">${esc(addStepSubName(sub))}</h5>
            <div class="addpick-grid">${list.map(c => c.html()).join('')}</div>` : '';
    }).join('');
}

function addStepHtml(plan, presets) {
    const head = plan.wrap
        ? `<p class="addpick-note">${esc(t('rec.dob_vybrano', {n: REC.sel.size}))}</p>` : '';
    const keys = plan.groups.map(g => g.key);
    const saved = window.store ? store.get(ADD_STEP_TAB_KEY, '') : '';
    const active = keys.includes(saved) ? saved : keys[0];
    ADD_STEP_CARDS = addStepBuildCards(plan, presets);
    const nav = plan.groups.map(g => `<button type="button" role="tab" data-tab="${g.key}"
        aria-selected="${g.key === active}" onclick="addStepTab('${g.key}')">${recIcon(ADD_STEP_GROUP_ICON[g.key])}
        <span>${esc(addStepGroupName(g.key))}</span></button>`).join('');
    const panes = plan.groups.map(group => {
        const cards = ADD_STEP_CARDS.filter(c => c.tab === group.key);
        const hint = group.key === 'action' ? `<p class="addpick-hint">${esc(t('rec.dob_deystvie_d'))}</p>` : '';
        const body = group.key === 'mine' ? addStepMineHtml()
            : group.key === 'action' ? addStepActionPane(ADD_STEP_CARDS)
            : group.key === 'cond' ? addStepCondPane(ADD_STEP_CARDS)
            : `<div class="addpick-grid">${cards.map(c => c.html()).join('')}</div>`;
        return `<section class="addpick-g" data-pane="${group.key}"${group.key === active ? '' : ' hidden'}>
        <h4>${esc(addStepGroupName(group.key))}</h4>${hint}${body}</section>`;
    }).join('');
    const search = `<div class="addpick-search">${recIcon('search')}
        <input type="search" id="addSearch" autocomplete="off" spellcheck="false"
               placeholder="${esc(t('rec.dob_poisk_ph'))}" aria-label="${esc(t('rec.dob_poisk_aria'))}"
               oninput="addStepFind(this.value)" onkeydown="addStepSearchKey(event)">
        <button type="button" class="addpick-clear" id="addSearchClear" hidden
                aria-label="${esc(t('rec.dob_poisk_clear'))}" onclick="addStepSearchReset()">${recIcon('x')}</button></div>`;
    return `${head}${search}<div class="addpick" id="addMain"><nav class="addpick-nav" role="tablist">${nav}</nav>
      <div class="addpick-pane">${panes}</div></div><div class="addpick-found" id="addFound" hidden></div>`;
}

function addStepTab(key) {
    document.querySelectorAll('.addpick-nav [data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === key)));
    document.querySelectorAll('.addpick-g[data-pane]').forEach(p => { p.hidden = p.dataset.pane !== key; });
    if (window.store) store.set(ADD_STEP_TAB_KEY, key);
}

/* Пока в поле есть текст — вместо вкладок один плоский список. */
function addStepFind(value) {
    const main = document.getElementById('addMain'), found = document.getElementById('addFound');
    const clear = document.getElementById('addSearchClear');
    if (!main || !found) return;
    const on = String(value || '').trim() !== '';
    if (clear) clear.hidden = !String(value || '');
    main.hidden = on;
    found.hidden = !on;
    if (!on) { found.innerHTML = ''; return; }
    const list = addStepSearch(value, ADD_STEP_CARDS);
    found.innerHTML = list.length
        ? `<h4>${esc(t('rec.dob_najdeno', {n: list.length}))}</h4>
           <div class="addpick-grid">${list.map(c => c.html(c.sec)).join('')}</div>`
        : `<p class="addpick-empty">${esc(t('rec.dob_nichego'))}</p>
           <button type="button" class="sm" onclick="addStepSearchReset()">${esc(t('rec.dob_sbrosit'))}</button>`;
}

function addStepSearchReset() {
    const input = document.getElementById('addSearch');
    if (!input) return;
    input.value = '';
    addStepFind('');
    input.focus();
}

function addStepSearchKey(ev) {
    if (ev.key === 'Escape' && ev.target.value) {
        /* Первый Esc очищает поле, диалог остаётся. */
        ev.preventDefault();
        ev.stopPropagation();
        addStepSearchReset();
    } else if (ev.key === 'Enter') {
        const first = document.querySelector('#addFound .addpick-card:not(:disabled)');
        if (first) { ev.preventDefault(); first.click(); }
    }
}
