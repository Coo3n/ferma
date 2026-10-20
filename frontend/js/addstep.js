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
    if (!wrap) groups.push({key: 'action', items: [item('presets')]});
    if (!wrap) groups.push({key: 'mine', items: [item('mine')]});
    const repeat = [item('loop', deep), item('until', deep)];
    if (!wrap && c.inLoop) repeat.push(item('break'));
    groups.push({key: 'repeat', items: repeat});
    const seen = [item('if_seen', deep), item('if_not', deep)];
    if (!wrap) seen.push(item('anchor', c.phone ? null : 'phone'));
    groups.push({key: 'seen', items: seen});
    /* Факты о телефоне — не о экране: свой раздел. Телефон для них не
       нужен — проверка идёт на прогоне. */
    groups.push({key: 'phone', items: ['phone_app', 'phone_no_app', 'phone_older', 'phone_battery',
        'phone_offline', 'phone_space', 'phone_account'].map(k => item(k, deep))});
    groups.push({key: 'chance', items: [item('chance', deep)]});
    if (!wrap) groups.push({key: 'other', items: [item('finish')]});
    return {wrap, groups};
}

/* Ключи строк — буквально: test_strings ищет t('…') в коде. */
function addStepGroupName(key) {
    return key === 'action' ? t('rec.dob_deystvie') : key === 'mine' ? t('rec.dob_moi')
        : key === 'repeat' ? t('rec.dob_povtoryat')
        : key === 'seen' ? t('rec.dob_esli') : key === 'phone' ? t('rec.dob_telefon')
        : key === 'chance' ? t('rec.dob_inogda') : t('rec.dob_drugoe');
}

const ADD_STEP_GROUP_ICON = {action: 'pointer', mine: 'zap', repeat: 'repeat', seen: 'eye', phone: 'phone', chance: 'dices', other: 'layers'};

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
        case 'call': return {icon: 'layers', title: t('rec.l_call'), desc: t('rec.l_call_d')};
        case 'phone_app': return {icon: 'phone', title: t('rec.dob_tel_app'), desc: t('rec.dob_tel_app_d')};
        case 'phone_no_app': return {icon: 'phone', title: t('rec.dob_tel_no_app'), desc: t('rec.dob_tel_no_app_d')};
        case 'phone_older': return {icon: 'refresh', title: t('rec.dob_tel_older'), desc: t('rec.dob_tel_older_d')};
        case 'phone_battery': return {icon: 'battery', title: t('rec.dob_tel_battery'), desc: t('rec.dob_tel_battery_d')};
        case 'phone_offline': return {icon: 'wifi', title: t('rec.dob_tel_offline'), desc: t('rec.dob_tel_offline_d')};
        case 'phone_space': return {icon: 'download', title: t('rec.dob_tel_space'), desc: t('rec.dob_tel_space_d')};
        case 'phone_account': return {icon: 'shield', title: t('rec.dob_tel_account'), desc: t('rec.dob_tel_account_d')};
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
};

/* compact — готовые действия: название без пояснения (оно в подсказке).
   Пятнадцать карточек с абзацем текста под каждой читались как статья. */
function addStepCard(onclick, icon, title, desc, off, compact) {
    const note = off ? addStepOffText(off) : desc;
    /* Подсказка — только когда пояснение спрятано (компактная карточка):
       иначе серый тултип повторял текст карточки слово в слово. */
    const tip = compact && !off ? ` title="${esc(note)}"` : '';
    return `<button type="button" class="addpick-card ${compact ? 'compact' : ''}" onclick="${onclick}"${off ? ' disabled' : ''}${tip}>
        <span class="addpick-ic">${recIcon(icon)}</span>
        <span class="addpick-tx"><b>${esc(title)}</b>${compact && !off ? '' : `<span>${esc(note)}</span>`}</span>
      </button>`;
}

/* «Мои»: свои команды и сценарии — вставить шагом «Запустить сценарий»
   (call). Раньше это пряталось в «Другое → Запустить сценарий» вторым окном. */
function addStepMineHtml() {
    const own = (S.scenarios || []).filter(x => /^[a-z][a-z0-9_]{0,47}$/.test(x.key)
        && x.key !== (REC.edit ? REC.edit.key : null) && !x.error && !x.template);
    const card = x => addStepCard(`recLogicCall('${esc(x.key)}')`, x.command ? 'zap' : 'layers',
        x.name || x.key, x.command ? t('rec.dob_komanda') : t('rec.dob_stsenariy'), null, true);
    const cmds = own.filter(x => x.command), rest = own.filter(x => !x.command);
    if (!own.length) return `<p class="addpick-empty">${esc(t('rec.dob_moi_pusto'))}</p>`;
    return (cmds.length ? '' : `<p class="addpick-hint">${esc(t('rec.dob_komand_net'))}</p>`) + (cmds.length ? `<h5 class="addpick-sub">${esc(t('cmd.komandy'))}</h5><div class="addpick-grid">${cmds.map(card).join('')}</div>` : '')
        + (rest.length ? `<h5 class="addpick-sub">${esc(t('rec.dob_stsenarii'))}</h5><div class="addpick-grid">${rest.map(card).join('')}</div>` : '');
}

const ADD_STEP_TAB_KEY = 'farm.addstep.tab';

function addStepHtml(plan, presets) {
    const head = plan.wrap
        ? `<p class="addpick-note">${esc(t('rec.dob_vybrano', {n: REC.sel.size}))}</p>` : '';
    const keys = plan.groups.map(g => g.key);
    const saved = window.store ? store.get(ADD_STEP_TAB_KEY, '') : '';
    const active = keys.includes(saved) ? saved : keys[0];
    const nav = plan.groups.map(g => `<button type="button" role="tab" data-tab="${g.key}"
        aria-selected="${g.key === active}" onclick="addStepTab('${g.key}')">${recIcon(ADD_STEP_GROUP_ICON[g.key])}
        <span>${esc(addStepGroupName(g.key))}</span></button>`).join('');
    const panes = plan.groups.map(group => {
        const cards = group.items.map(it => {
            if (it.key === 'presets') {
                return (presets || []).map((preset, index) => {
                    const first = (preset.steps || [])[0];
                    const icon = (first && ADD_STEP_PRESET_ICON[first.kind]) || 'plus';
                    return addStepCard(`recLibPick(${index})`, icon, preset.title, preset.desc, null, true);
                }).join('');
            }
            if (it.key === 'mine') return '';
            const text = addStepItemText(it.key);
            return addStepCard(`recAddPick('${it.key}')`, text.icon, text.title, text.desc, it.off);
        }).join('');
        const hint = group.key === 'action' ? `<p class="addpick-hint">${esc(t('rec.dob_deystvie_d'))}</p>` : '';
        const body = group.key === 'mine' ? addStepMineHtml() : `<div class="addpick-grid">${cards}</div>`;
        return `<section class="addpick-g" data-pane="${group.key}"${group.key === active ? '' : ' hidden'}>
        <h4>${esc(addStepGroupName(group.key))}</h4>${hint}${body}</section>`;
    }).join('');
    return `${head}<div class="addpick"><nav class="addpick-nav" role="tablist">${nav}</nav>
      <div class="addpick-pane">${panes}</div></div>`;
}

function addStepTab(key) {
    document.querySelectorAll('.addpick-nav [data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === key)));
    document.querySelectorAll('.addpick-g[data-pane]').forEach(p => { p.hidden = p.dataset.pane !== key; });
    if (window.store) store.set(ADD_STEP_TAB_KEY, key);
}
